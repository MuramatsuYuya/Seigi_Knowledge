"""
Folder Management Lambda Function

This Lambda function handles all folder and file operations:
- GET /api/folders: Get folder tree with registration status
- POST /api/folder-management: Create or delete folders
- GET /api/s3-presigned-urls: Generate presigned URLs for file upload
- POST /api/trigger-processing: Trigger automatic processing for uploaded files

Environment Variables:
    - S3_BUCKET: S3 bucket name
    - DYNAMODB_FOLDER_CONFIG_TABLE: DynamoDB table for folder configuration
    - WORKER_LAMBDA_ARN: Worker Lambda ARN for processing
    - AWS_REGION: AWS region
"""

import json
import logging
import os
import boto3
from datetime import datetime, timezone, timedelta
from botocore.exceptions import ClientError
from folder_tree_helper import get_folder_tree

# Initialize AWS clients
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')
stepfunctions_client = boto3.client('stepfunctions')

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
S3_BUCKET = os.environ.get('S3_BUCKET')
DYNAMODB_FOLDER_CONFIG_TABLE = os.environ.get('DYNAMODB_FOLDER_CONFIG_TABLE')
WORKER_LAMBDA_ARN = os.environ.get('WORKER_LAMBDA_ARN')
STATE_MACHINE_ARN = os.environ.get('STATE_MACHINE_ARN', '')
AWS_REGION = os.environ.get('AWS_REGION', 'us-west-2')

# DynamoDB table
folder_config_table = dynamodb.Table(DYNAMODB_FOLDER_CONFIG_TABLE) if DYNAMODB_FOLDER_CONFIG_TABLE else None

# JST timezone (UTC+9)
JST = timezone(timedelta(hours=9))


def get_folder_tree_with_registration_status():
    """
    Get folder tree from S3 and enrich with registration status from DynamoDB
    
    Returns:
        List of folder objects with is_registered and default_job_id fields
    """
    try:
        # Get folder tree from S3
        folders = get_folder_tree()
        
        if not folder_config_table:
            logger.warning("DYNAMODB_FOLDER_CONFIG_TABLE not configured")
            # Return folders without registration status
            for folder in folders:
                add_registration_status(folder, {})
            return folders
        
        # Get all registered folders from DynamoDB
        logger.info("Fetching registered folders from DynamoDB")
        response = folder_config_table.scan()
        registered_folders = {}
        
        for item in response.get('Items', []):
            folder_path = item.get('folder_path')
            registered_folders[folder_path] = {
                'default_job_id': item.get('default_job_id'),
                'latest_job_id': item.get('latest_job_id')
            }
        
        # Handle pagination
        while 'LastEvaluatedKey' in response:
            response = folder_config_table.scan(
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            for item in response.get('Items', []):
                folder_path = item.get('folder_path')
                registered_folders[folder_path] = {
                    'default_job_id': item.get('default_job_id'),
                    'latest_job_id': item.get('latest_job_id')
                }
        
        logger.info(f"Found {len(registered_folders)} registered folders")
        
        # Add registration status to each folder
        for folder in folders:
            add_registration_status(folder, registered_folders)
        
        return folders
        
    except Exception as e:
        logger.error(f"Error getting folder tree with registration status: {e}", exc_info=True)
        raise


def filter_registered_folders(folder, registered_folders):
    """
    Recursively filter folder tree to show only registered folders and their parents
    Returns the folder if it or any of its descendants are registered, None otherwise
    
    Args:
        folder: Folder object
        registered_folders: Dict of registered folder paths
    
    Returns:
        Filtered folder object or None
    """
    folder_path = folder.get('path')
    is_registered = folder_path in registered_folders
    
    # Recursively filter children
    filtered_children = []
    if 'children' in folder and folder['children']:
        for child in folder['children']:
            filtered_child = filter_registered_folders(child, registered_folders)
            if filtered_child:
                filtered_children.append(filtered_child)
    
    # Include this folder if:
    # 1. It's registered, OR
    # 2. It has registered descendants (parent folder case)
    if is_registered or filtered_children:
        folder_copy = folder.copy()
        folder_copy['children'] = filtered_children
        add_registration_status(folder_copy, registered_folders)
        return folder_copy
    
    return None


def add_registration_status(folder, registered_folders):
    """
    Recursively add registration status to folder and its children
    
    Args:
        folder: Folder object
        registered_folders: Dict of registered folder paths
    """
    folder_path = folder.get('path')
    
    if folder_path in registered_folders:
        folder['is_registered'] = True
        folder['default_job_id'] = registered_folders[folder_path].get('default_job_id')
    else:
        folder['is_registered'] = False
        folder['default_job_id'] = None
    
    # Recursively process children
    if 'children' in folder and folder['children']:
        for child in folder['children']:
            add_registration_status(child, registered_folders)


def create_folder(folder_path):
    """
    Create a folder in S3 by creating a marker file
    
    Args:
        folder_path: Folder path without PDF/ prefix (e.g., "フォルダ1/新フォルダ")
    
    Returns:
        (success: bool, message: str)
    """
    try:
        marker_key = f"PDF/{folder_path}/.folder_marker"
        
        logger.info(f"Creating folder marker: {marker_key}")
        
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=marker_key,
            Body=b"",
            ContentType="application/octet-stream"
        )
        
        logger.info(f"Successfully created folder: {folder_path}")
        return True, "フォルダを作成しました"
        
    except ClientError as e:
        logger.error(f"Error creating folder: {e}")
        return False, f"フォルダの作成に失敗しました: {str(e)}"


def delete_folder(folder_path):
    """
    Delete a folder from S3 if all descendants are empty (contain no files except .folder_marker)
    
    Args:
        folder_path: Folder path without PDF/ prefix
    
    Returns:
        (success: bool, message: str)
    """
    try:
        prefix = f"PDF/{folder_path}/"
        
        logger.info(f"Checking if folder can be deleted: {folder_path}")
        
        # Check for any files in this folder and all descendants
        # (excluding .folder_marker)
        response = s3_client.list_objects_v2(
            Bucket=S3_BUCKET,
            Prefix=prefix
        )
        
        has_non_marker_files = False
        if 'Contents' in response:
            for obj in response.get('Contents', []):
                key = obj['Key']
                # .folder_marker は除外
                if not key.endswith('/.folder_marker'):
                    logger.warning(f"Found non-marker file: {key}")
                    has_non_marker_files = True
                    break
        
        # ページネーション処理
        while 'IsTruncated' in response and response['IsTruncated']:
            response = s3_client.list_objects_v2(
                Bucket=S3_BUCKET,
                Prefix=prefix,
                ContinuationToken=response.get('NextContinuationToken')
            )
            if 'Contents' in response:
                for obj in response.get('Contents', []):
                    key = obj['Key']
                    if not key.endswith('/.folder_marker'):
                        logger.warning(f"Found non-marker file: {key}")
                        has_non_marker_files = True
                        break
            if has_non_marker_files:
                break
        
        if has_non_marker_files:
            logger.warning(f"Folder has non-marker files: {folder_path}")
            return False, "データが存在するため削除できません。配下のすべてのフォルダが空である必要があります。"
        
        # 配下のすべての .folder_marker を削除
        logger.info(f"Deleting all .folder_marker files under {folder_path}")
        response = s3_client.list_objects_v2(
            Bucket=S3_BUCKET,
            Prefix=prefix
        )
        
        marker_count = 0
        if 'Contents' in response:
            for obj in response.get('Contents', []):
                key = obj['Key']
                if key.endswith('/.folder_marker'):
                    s3_client.delete_object(Bucket=S3_BUCKET, Key=key)
                    marker_count += 1
                    logger.info(f"Deleted marker: {key}")
        
        # ページネーション処理
        while 'IsTruncated' in response and response['IsTruncated']:
            response = s3_client.list_objects_v2(
                Bucket=S3_BUCKET,
                Prefix=prefix,
                ContinuationToken=response.get('NextContinuationToken')
            )
            if 'Contents' in response:
                for obj in response.get('Contents', []):
                    key = obj['Key']
                    if key.endswith('/.folder_marker'):
                        s3_client.delete_object(Bucket=S3_BUCKET, Key=key)
                        marker_count += 1
                        logger.info(f"Deleted marker: {key}")
        
        logger.info(f"Successfully deleted folder {folder_path} ({marker_count} markers deleted)")
        return True, f"フォルダを削除しました（{marker_count}個のマーカーを削除）"
        
    except ClientError as e:
        logger.error(f"Error deleting folder: {e}")
        return False, f"フォルダの削除に失敗しました: {str(e)}"


def generate_presigned_urls(folder_path, filenames, user_id=None):
    """
    Generate presigned URLs for uploading files to S3
    
    Args:
        folder_path: Folder path without PDF/ prefix
        filenames: List of filenames
        user_id: User ID from Cognito authentication (optional for backward compatibility)
    
    Returns:
        {
            "is_registered": bool,
            "default_job_id": str or None,
            "urls": {filename: presigned_url}
        }
    """
    try:
        # Security: Validate file count and names
        MAX_FILES_PER_REQUEST = 50
        MAX_FILENAME_LENGTH = 255
        
        if len(filenames) > MAX_FILES_PER_REQUEST:
            raise ValueError(f"Too many files. Maximum {MAX_FILES_PER_REQUEST} files per request.")
        
        for filename in filenames:
            if len(filename) > MAX_FILENAME_LENGTH:
                raise ValueError(f"Filename too long: {filename}")
            # Basic sanitization - prevent path traversal
            if '..' in filename or '/' in filename or '\\' in filename:
                raise ValueError(f"Invalid filename: {filename}")
        
        if user_id:
            logger.info(f"User {user_id} requesting presigned URLs for folder: {folder_path}")
        
        # Check if folder is registered
        is_registered = False
        default_job_id = None
        
        if folder_config_table:
            try:
                response = folder_config_table.get_item(
                    Key={'folder_path': folder_path}
                )
                
                if 'Item' in response:
                    is_registered = True
                    default_job_id = response['Item'].get('default_job_id')
                    logger.info(f"Folder {folder_path} is registered with job_id: {default_job_id}")
                else:
                    logger.info(f"Folder {folder_path} is not registered")
                    
            except ClientError as e:
                logger.error(f"Error checking folder registration: {e}")
        
        # Generate presigned URLs with security constraints
        urls = {}
        for filename in filenames:
            s3_key = f"PDF/{folder_path}/{filename}"
            
            # Security: Set file size limit (50MB max)
            presigned_url = s3_client.generate_presigned_url(
                'put_object',
                Params={
                    'Bucket': S3_BUCKET,
                    'Key': s3_key,
                    'ContentType': 'application/pdf',
                    'ContentLength': 52428800  # 50MB limit
                },
                ExpiresIn=3600  # 1 hour
            )
            
            urls[filename] = presigned_url
            logger.info(f"Generated presigned URL for: {s3_key}" + (f" (user: {user_id})" if user_id else ""))
        
        return {
            'is_registered': is_registered,
            'default_job_id': default_job_id,
            'urls': urls
        }
        
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise
    except Exception as e:
        logger.error(f"Error generating presigned URLs: {e}", exc_info=True)
        raise


def trigger_processing(folder_path, job_id, uploaded_files, processing_mode='full'):
    """
    Trigger automatic processing for uploaded files using Step Functions
    
    Args:
        folder_path: Folder path
        job_id: Job ID (default_job_id)
        uploaded_files: List of uploaded filenames
        processing_mode: "full", "reknowledge", or "direct_pdf" (default: "full")
    
    Returns:
        Success message
    """
    try:
        logger.info(f"Triggering Step Functions processing for {len(uploaded_files)} files in {folder_path} with job_id: {job_id}, mode: {processing_mode}")
        
        if not STATE_MACHINE_ARN:
            # Fallback: Direct Lambda invocation (legacy mode)
            logger.warning("STATE_MACHINE_ARN not configured, falling back to direct Lambda invocation")
            return trigger_processing_direct(folder_path, job_id, uploaded_files, processing_mode)
        
        # Prepare file items for Step Functions
        file_items = []
        for idx, filename in enumerate(uploaded_files):
            file_key = f"PDF/{folder_path}/{filename}"
            is_last_file = (idx == len(uploaded_files) - 1)
            
            file_items.append({
                'mode': processing_mode,
                'job_id': job_id,
                'folder_path': folder_path,
                'file_key': file_key,
                'file_name': filename,
                'trigger_kb_sync': is_last_file
            })
        
        execution_input = {
            'files': file_items
        }
        
        # Start Step Functions execution
        execution_input_str = json.dumps(execution_input, ensure_ascii=False)
        
        response = stepfunctions_client.start_execution(
            stateMachineArn=STATE_MACHINE_ARN,
            name=f"upload-{job_id}-{datetime.now(JST).strftime('%Y%m%d%H%M%S')}",
            input=execution_input_str
        )
        
        execution_arn = response['executionArn']
        logger.info(f"Started Step Functions execution for upload: {execution_arn}")
        
        return f"{len(uploaded_files)}個のファイルの処理を開始しました (Step Functions)"
        
    except Exception as e:
        logger.error(f"Error triggering Step Functions processing: {e}", exc_info=True)
        raise


def trigger_processing_direct(folder_path, job_id, uploaded_files, processing_mode='full'):
    """
    Legacy: Direct Worker Lambda invocation (fallback when Step Functions not available)
    
    Args:
        folder_path: Folder path
        job_id: Job ID (default_job_id)
        uploaded_files: List of uploaded filenames
        processing_mode: "full", "reknowledge", or "direct_pdf" (default: "full")
    
    Returns:
        Success message
    """
    try:
        logger.info(f"Triggering direct processing for {len(uploaded_files)} files in {folder_path} with job_id: {job_id}, mode: {processing_mode}")
        
        for idx, filename in enumerate(uploaded_files):
            file_key = f"PDF/{folder_path}/{filename}"
            
            # Determine if this is the last file (for KB sync trigger)
            is_last_file = (idx == len(uploaded_files) - 1)
            
            # Prepare event for worker Lambda
            event = {
                'mode': processing_mode,
                'job_id': job_id,
                'folder_path': folder_path,
                'file_key': file_key,
                'file_name': filename,
                'trigger_kb_sync': is_last_file
            }
            
            # Invoke worker Lambda asynchronously
            lambda_client.invoke(
                FunctionName=WORKER_LAMBDA_ARN,
                InvocationType='Event',  # Asynchronous
                Payload=json.dumps(event)
            )
            
            logger.info(f"Invoked worker Lambda for file: {filename} (KB sync: {is_last_file})")
        
        return f"{len(uploaded_files)}個のファイルの処理を開始しました (Direct Lambda)"
        
    except Exception as e:
        logger.error(f"Error triggering direct processing: {e}", exc_info=True)
        raise


def lambda_handler(event, context):
    """
    Main Lambda handler for folder management
    
    Routes:
    - GET /api/folders: Get folder tree with registration status
    - POST /api/folder-management: Create or delete folders
    - GET /api/s3-presigned-urls: Generate presigned URLs for file upload
    - POST /api/trigger-processing: Trigger automatic processing
    """
    try:
        logger.info(f"Received event: {json.dumps(event, default=str)}")
        
        # Extract user information from Cognito authorizer
        request_context = event.get('requestContext', {})
        authorizer = request_context.get('authorizer', {})
        claims = authorizer.get('claims', {})
        
        user_id = claims.get('sub')  # Cognito User UUID
        username = claims.get('cognito:username', 'unknown')
        email = claims.get('email', 'unknown')
        
        if user_id:
            logger.info(f"Authenticated user: {username} (ID: {user_id}, Email: {email})")
        else:
            logger.warning("No user authentication information found in request")
        
        # Extract HTTP method and path
        http_method = event.get('httpMethod', event.get('requestContext', {}).get('http', {}).get('method', 'GET'))
        path = event.get('path', event.get('requestContext', {}).get('http', {}).get('path', ''))
        
        logger.info(f"Request: {http_method} {path}")
        
        # Route: GET /api/folders
        # Query parameter: registered_only=true で登録済みフォルダのみ返す(knowledge-query.html用)
        if http_method == 'GET' and path == '/api/folders':
            query_params = event.get('queryStringParameters') or {}
            registered_only = query_params.get('registered_only', '').lower() == 'true'
            
            folders = get_folder_tree_with_registration_status()
            
            # knowledge-query.html用: 登録済みフォルダのみフィルタリング
            if registered_only:
                logger.info("Filtering to show only registered folders")
                
                if not folder_config_table:
                    logger.warning("DYNAMODB_FOLDER_CONFIG_TABLE not configured, returning empty")
                    folders = []
                else:
                    # DynamoDBから登録済みフォルダを取得
                    response = folder_config_table.scan()
                    registered_folders = {}
                    for item in response.get('Items', []):
                        folder_path = item.get('folder_path')
                        registered_folders[folder_path] = {
                            'default_job_id': item.get('default_job_id'),
                            'latest_job_id': item.get('latest_job_id')
                        }
                    
                    # ページネーション処理
                    while 'LastEvaluatedKey' in response:
                        response = folder_config_table.scan(
                            ExclusiveStartKey=response['LastEvaluatedKey']
                        )
                        for item in response.get('Items', []):
                            folder_path = item.get('folder_path')
                            registered_folders[folder_path] = {
                                'default_job_id': item.get('default_job_id'),
                                'latest_job_id': item.get('latest_job_id')
                            }
                    
                    # フォルダツリーをフィルタリング
                    filtered_folders = []
                    for folder in folders:
                        filtered_folder = filter_registered_folders(folder, registered_folders)
                        if filtered_folder:
                            filtered_folders.append(filtered_folder)
                    folders = filtered_folders
                    logger.info(f"Filtered to {len(folders)} root folders with registered descendants")
            
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps(folders, ensure_ascii=False)
            }
        
        # Route: POST /api/folder-management
        if http_method == 'POST' and path == '/api/folder-management':
            body = json.loads(event.get('body', '{}'))
            action = body.get('action')
            folder_path = body.get('folder_path')
            
            if not action or not folder_path:
                return {
                    'statusCode': 400,
                    'headers': {'Content-Type': 'application/json'},
                    'body': json.dumps({
                        'error': 'Missing required parameters',
                        'message': 'action and folder_path are required'
                    }, ensure_ascii=False)
                }
            
            if action == 'create':
                success, message = create_folder(folder_path)
                status_code = 200 if success else 400
                
                return {
                    'statusCode': status_code,
                    'headers': {'Content-Type': 'application/json'},
                    'body': json.dumps({
                        'message': message,
                        'folder_path': folder_path
                    }, ensure_ascii=False)
                }
            
            elif action == 'delete':
                success, message = delete_folder(folder_path)
                status_code = 200 if success else 400
                
                return {
                    'statusCode': status_code,
                    'headers': {'Content-Type': 'application/json'},
                    'body': json.dumps({
                        'message': message,
                        'folder_path': folder_path
                    }, ensure_ascii=False)
                }
            
            else:
                return {
                    'statusCode': 400,
                    'headers': {'Content-Type': 'application/json'},
                    'body': json.dumps({
                        'error': 'Invalid action',
                        'message': 'action must be "create" or "delete"'
                    }, ensure_ascii=False)
                }
        
        # Route: GET /api/s3-presigned-urls
        if http_method == 'GET' and path == '/api/s3-presigned-urls':
            params = event.get('queryStringParameters', {})
            folder_path = params.get('folder_path')
            filenames_str = params.get('filenames', '')
            
            if not folder_path or not filenames_str:
                return {
                    'statusCode': 400,
                    'headers': {'Content-Type': 'application/json'},
                    'body': json.dumps({
                        'error': 'Missing required parameters',
                        'message': 'folder_path and filenames are required'
                    }, ensure_ascii=False)
                }
            
            filenames = [f.strip() for f in filenames_str.split(',')]
            
            # Pass user_id for audit logging
            try:
                result = generate_presigned_urls(folder_path, filenames, user_id=user_id)
            except ValueError as e:
                return {
                    'statusCode': 400,
                    'headers': {'Content-Type': 'application/json'},
                    'body': json.dumps({
                        'error': 'Validation error',
                        'message': str(e)
                    }, ensure_ascii=False)
                }
            
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps(result, ensure_ascii=False)
            }
        
        # Route: POST /api/trigger-processing
        if http_method == 'POST' and path == '/api/trigger-processing':
            body = json.loads(event.get('body', '{}'))
            folder_path = body.get('folder_path')
            job_id = body.get('job_id')
            uploaded_files = body.get('uploaded_files', [])
            processing_mode = body.get('processing_mode', 'full')  # New parameter
            
            # Validate processing_mode
            valid_modes = ['full', 'direct_pdf']
            if processing_mode not in valid_modes:
                return {
                    'statusCode': 400,
                    'headers': {'Content-Type': 'application/json'},
                    'body': json.dumps({
                        'error': 'Invalid processing_mode',
                        'message': f'processing_mode must be one of: {valid_modes}'
                    }, ensure_ascii=False)
                }
            
            if not all([folder_path, job_id, uploaded_files]):
                return {
                    'statusCode': 400,
                    'headers': {'Content-Type': 'application/json'},
                    'body': json.dumps({
                        'error': 'Missing required parameters',
                        'message': 'folder_path, job_id, and uploaded_files are required'
                    }, ensure_ascii=False)
                }
            
            message = trigger_processing(folder_path, job_id, uploaded_files, processing_mode)
            
            return {
                'statusCode': 202,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({
                    'message': message,
                    'folder_path': folder_path,
                    'job_id': job_id
                }, ensure_ascii=False)
            }
        
        # Unknown route
        return {
            'statusCode': 404,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({
                'error': 'Not found',
                'message': f'Route not found: {http_method} {path}'
            }, ensure_ascii=False)
        }
        
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({
                'error': 'Internal server error',
                'message': str(e)
            }, ensure_ascii=False)
        }
