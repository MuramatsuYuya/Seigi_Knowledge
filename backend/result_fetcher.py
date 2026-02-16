"""
PDF OCR System - Result Fetcher Lambda

Fetches job status and results from DynamoDB and S3.
Returns presigned URLs for transcript and knowledge files.
Supports both v1 (flat) and v2 (hierarchical) structures.
"""

import json
import boto3
import os
import logging
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS Clients
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

# Environment variables
DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']
S3_BUCKET = os.environ['S3_BUCKET']

# DynamoDB table
jobs_table = dynamodb.Table(DYNAMODB_TABLE)


def generate_presigned_url(bucket_name, object_key, expiration=3600):
    """Generate presigned URL for S3 object"""
    try:
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': object_key},
            ExpiresIn=expiration
        )
        return url
    except ClientError as e:
        logger.error(f"Error generating presigned URL: {e}")
        return None


def get_job_status(job_id):
    """Get job status from DynamoDB (v1 - flat structure)"""
    try:
        response = jobs_table.query(
            KeyConditionExpression='job_id = :job_id',
            ExpressionAttributeValues={
                ':job_id': job_id
            }
        )
        return response.get('Items', [])
    except ClientError as e:
        logger.error(f"Error querying DynamoDB: {e}")
        return []


def get_job_status_by_folder_path(folder_path):
    """
    Get job status from DynamoDB by folder_path (v2 - hierarchical structure)
    Uses GSI: folder_path-index (with pagination support)
    
    Returns: list of items grouped by job_id
    """
    try:
        items = []
        last_evaluated_key = None
        
        while True:
            query_params = {
                'IndexName': 'folder_path-index',
                'KeyConditionExpression': Key('folder_path').eq(folder_path)
            }
            if last_evaluated_key:
                query_params['ExclusiveStartKey'] = last_evaluated_key
            
            response = jobs_table.query(**query_params)
            items.extend(response.get('Items', []))
            
            last_evaluated_key = response.get('LastEvaluatedKey')
            if not last_evaluated_key:
                break
        
        logger.info(f"Found {len(items)} items for folder_path: {folder_path}")
        return items
        
    except ClientError as e:
        logger.error(f"Error querying DynamoDB GSI: {e}")
        return []


def get_job_status_v2(job_id, folder_path):
    """
    Get job status from DynamoDB (v2 - with folder_path)
    Uses composite key: job_id (PK) + folder_path#file_name (SK)
    """
    try:
        logger.info(f"[get_job_status_v2] Querying job_id: {job_id}, folder_path: {folder_path}")
        
        # Query by job_id and filter by folder_path prefix in sort key
        if folder_path:
            # Use KeyConditionExpression to filter by sort key prefix
            response = jobs_table.query(
                KeyConditionExpression='job_id = :job_id AND begins_with(#sk, :folder_prefix)',
                ExpressionAttributeNames={
                    '#sk': 'folder_path#file_name'
                },
                ExpressionAttributeValues={
                    ':job_id': job_id,
                    ':folder_prefix': f"{folder_path}#"
                }
            )
        else:
            # No folder_path filter
            response = jobs_table.query(
                KeyConditionExpression='job_id = :job_id',
                ExpressionAttributeValues={
                    ':job_id': job_id
                }
            )
        
        items = response.get('Items', [])
        
        logger.info(f"[get_job_status_v2] Found {len(items)} items")
        if items:
            logger.info(f"[get_job_status_v2] Sample item: {json.dumps(items[0], default=str)}")
        
        return items
        
    except ClientError as e:
        logger.error(f"[get_job_status_v2] Error querying DynamoDB: {e}")
        return []


def get_file_content(s3_key):
    """Get file content from S3"""
    try:
        response = s3_client.get_object(Bucket=S3_BUCKET, Key=s3_key)
        content = response['Body'].read().decode('utf-8')
        return content
    except ClientError as e:
        logger.error(f"Error reading from S3: {e}")
        return None


def get_knowledge_chunks(job_id, base_name, folder_path=None):
    """
    Get knowledge chunks from S3, either as single file or multiple chunks.
    Supports both v1 (flat) and v2 (hierarchical) structures.
    
    Args:
        job_id: Job ID
        base_name: Base filename without extension
        folder_path: Optional folder path for v2 structure
    
    Tries to find:
    1. v2: Knowledge/{folder_path}/{job_id}/{base_name}_001.txt, ...
    2. v1: Knowledge/{job_id}/{base_name}_001.txt, ...
    3. Fallback: Single file
    
    Returns combined content with chunk headers if multiple files found.
    """
    if folder_path:
        # v2 structure
        prefix = f"Knowledge/{folder_path}/{job_id}/{base_name}"
        logger.info(f"Looking for v2 knowledge chunks with prefix: {prefix}")
    else:
        # v1 structure
        prefix = f"Knowledge/{job_id}/{base_name}"
        logger.info(f"Looking for v1 knowledge chunks with prefix: {prefix}")
    
    try:
        # List all files with the base name prefix
        response = s3_client.list_objects_v2(
            Bucket=S3_BUCKET,
            Prefix=prefix
        )
        
        if 'Contents' not in response:
            logger.warning(f"No knowledge files found for prefix: {prefix}")
            return None
        
        # Filter for .txt files (not .metadata.json)
        txt_files = [
            obj['Key'] for obj in response['Contents']
            if obj['Key'].endswith('.txt') and not obj['Key'].endswith('.metadata.json')
        ]
        
        if not txt_files:
            logger.warning(f"No .txt files found for prefix: {prefix}")
            return None
        
        # Check if we have chunked files (e.g., {base_name}_001.txt)
        chunked_files = [f for f in txt_files if '_' in f.split('/')[-1].replace('.txt', '')]
        
        if chunked_files:
            # Sort chunked files by number
            chunked_files.sort()
            logger.info(f"Found {len(chunked_files)} knowledge chunks for {base_name}")
            
            # Combine all chunks with headers
            combined_content = []
            for file_key in chunked_files:
                # Extract filename without path and extension
                section_split = '---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------\n'
                filename = file_key.split('/')[-1].replace('.txt', '')
                
                # Get content
                content = get_file_content(file_key)
                if content:
                    combined_content.append(f"{section_split}")
                    combined_content.append(f"{filename}\n{content}")
            
            return "\n\n".join(combined_content) if combined_content else None
        
        else:
            # Single file format (old format)
            if folder_path:
                single_file_key = f"Knowledge/{folder_path}/{job_id}/{base_name}.txt"
            else:
                single_file_key = f"Knowledge/{job_id}/{base_name}.txt"
            logger.info(f"Using single knowledge file: {single_file_key}")
            return get_file_content(single_file_key)
    
    except ClientError as e:
        logger.error(f"Error listing/reading knowledge chunks: {e}")
        return None


def list_job_ids(folder_path):
    """
    List all available job IDs for a specific folder_path from S3 Prompts folder
    
    Args:
        folder_path: Folder path (required)
    
    Returns:
        List of job IDs
    """
    try:
        prefix = f'Prompts/{folder_path}/'
        logger.info(f"Listing job_ids for folder_path: {folder_path}")
        
        response = s3_client.list_objects_v2(
            Bucket=S3_BUCKET,
            Prefix=prefix,
            Delimiter='/'
        )
        
        job_ids = []
        if 'CommonPrefixes' in response:
            for prefix_obj in response['CommonPrefixes']:
                # Extract job_id from prefix
                # Format: 'Prompts/folder_path/job_id/'
                prefix_str = prefix_obj['Prefix']
                
                # Extract job_id: Prompts/folder_path/job_id/ -> job_id
                parts = prefix_str.replace(f'Prompts/{folder_path}/', '').rstrip('/').split('/')
                if parts and parts[0]:
                    job_ids.append(parts[0])
        
        # Sort in descending order (newest first)
        job_ids.sort(reverse=True)
        logger.info(f"Found {len(job_ids)} job IDs for folder: {folder_path}")
        return job_ids
    except ClientError as e:
        logger.error(f"Error listing job IDs: {e}")
        return []


def lambda_handler(event, context):
    """
    Main Lambda handler
    
    Expected input:
    GET /results/{job_id} - Get specific job results (v1)
    GET /results?job_id={job_id}&folder_path={folder_path} - Get results with folder_path (v2)
    GET /results?folder_path={folder_path} - Get all results for folder (v2)
    GET /results?job_id={job_id}&folder_path={folder_path}&file_name={file_name} - Get single file content (v2)
    GET /results - List all available job IDs
    """
    try:
        # Extract job_id from path parameters
        path_parameters = event.get('pathParameters', {})
        job_id = path_parameters.get('job_id') if path_parameters else None
        
        # Extract query parameters for v2
        query_parameters = event.get('queryStringParameters', {}) or {}
        folder_path = query_parameters.get('folder_path')
        file_name = query_parameters.get('file_name')
        
        # Override job_id from query parameter if present
        if not job_id and query_parameters.get('job_id'):
            job_id = query_parameters.get('job_id')
        
        # Handle single file content request
        if job_id and folder_path and file_name:
            logger.info(f"Fetching single file content: job_id={job_id}, folder_path={folder_path}, file_name={file_name}")
            
            base_name = file_name.rsplit('.pdf', 1)[0] if file_name.lower().endswith('.pdf') else file_name
            
            # Transcript path: Transcript/{folder_path}/{job_id}/{base_name}.txt
            transcript_key = f"Transcript/{folder_path}/{job_id}/{base_name}.txt"
            transcript_content = get_file_content(transcript_key)
            
            # Knowledge content (handles chunked files)
            knowledge_content = get_knowledge_chunks(job_id, base_name, folder_path)
            
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'file_name': file_name,
                    'transcript': transcript_content,
                    'knowledge': knowledge_content
                })
            }
        
        # folder_path is required for job_id listing
        if not job_id and not folder_path:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'folder_path is required'
                })
            }
        
        # If only folder_path is provided, return job_ids for that folder
        if folder_path and not job_id:
            job_ids = list_job_ids(folder_path)
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'job_ids': job_ids,
                    'folder_path': folder_path
                })
            }
        
        logger.info(f"Fetching results for job_id: {job_id}, folder_path: {folder_path}")
        
        # Get prompts from S3
        if folder_path and job_id:
            # v2: Prompts/{folder_path}/{job_id}/
            transcript_prompt_key = f"Prompts/{folder_path}/{job_id}/transcript_prompt.txt"
            knowledge_prompt_key = f"Prompts/{folder_path}/{job_id}/knowledge_prompt.txt"
        elif job_id:
            # v1: Prompts/{job_id}/
            transcript_prompt_key = f"Prompts/{job_id}/transcript_prompt.txt"
            knowledge_prompt_key = f"Prompts/{job_id}/knowledge_prompt.txt"
        else:
            transcript_prompt_key = None
            knowledge_prompt_key = None
        
        transcript_prompt = get_file_content(transcript_prompt_key) if transcript_prompt_key else None
        knowledge_prompt = get_file_content(knowledge_prompt_key) if knowledge_prompt_key else None
        
        # Get job status from DynamoDB
        if folder_path and job_id:
            # v2: folder_path + job_id
            job_items = get_job_status_v2(job_id, folder_path)
        elif folder_path:
            # v2: folder_path のみ（すべての job_id）
            job_items = get_job_status_by_folder_path(folder_path)
        elif job_id:
            # v1: job_id のみ
            job_items = get_job_status(job_id)
        else:
            job_items = []
        
        if not job_items:
            return {
                'statusCode': 404,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Job not found'
                })
            }
        
        # Build response with file contents
        results = []
        
        # Limit content loading to prevent timeout
        # Only load full content if specifically requested or if there are few files
        load_full_content = len(job_items) <= 5  # Only auto-load for 5 or fewer files
        
        logger.info(f"[lambda_handler] Processing {len(job_items)} items, load_full_content: {load_full_content}")
        
        for item in job_items:
            file_name = item.get('file_name') or item.get('pdf_name')  # Backward compatibility
            status = item['status']
            file_key = item.get('file_key') or item.get('pdf_key')  # Backward compatibility
            item_folder_path = item.get('folder_path')  # v2 attribute
            item_job_id = item.get('job_id')  # Always present
            
            # Get base name without .pdf extension
            base_name = file_name.rsplit('.pdf', 1)[0] if file_name.lower().endswith('.pdf') else file_name
            
            result_item = {
                'file_name': file_name,
                'status': status,
                'last_update': item.get('last_update', ''),
                'message': item.get('message', ''),
                'transcript': None,
                'knowledge': None,
                'file_url': None,
                'folder_path': item_folder_path,  # v2
                'job_id': item_job_id
            }
            
            # Generate presigned URL for file if file_key exists
            if file_key:
                file_url = generate_presigned_url(S3_BUCKET, file_key, expiration=3600)
                if file_url:
                    result_item['file_url'] = file_url
            
            # If processing is done and we should load full content
            if status == 'done' and load_full_content:
                # Transcript path
                if item_folder_path:
                    # v2: Transcript/{folder_path}/{job_id}/{base_name}.txt
                    transcript_key = f"Transcript/{item_folder_path}/{item_job_id}/{base_name}.txt"
                else:
                    # v1: Transcript/{job_id}/{base_name}.txt
                    transcript_key = f"Transcript/{item_job_id}/{base_name}.txt"
                
                # Get transcript content
                transcript_content = get_file_content(transcript_key)
                
                # Get knowledge content (handles both chunked and single file, v1 and v2)
                knowledge_content = get_knowledge_chunks(item_job_id, base_name, item_folder_path)
                
                if transcript_content:
                    result_item['transcript'] = transcript_content
                
                if knowledge_content:
                    result_item['knowledge'] = knowledge_content
            
            results.append(result_item)
        
        logger.info(f"[lambda_handler] Returning {len(results)} results")
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'job_id': job_id,
                'folder_path': folder_path,
                'transcript_prompt': transcript_prompt,
                'knowledge_prompt': knowledge_prompt,
                'results': results,
                'total_files': len(results),
                'content_loaded': load_full_content
            })
        }
    
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Internal server error',
                'message': str(e)
            })
        }
