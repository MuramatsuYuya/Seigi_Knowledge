"""
Bedrock Knowledge Base Sync Lambda Function

This Lambda function is responsible for synchronizing the Knowledge Base
after all PDF processing is complete. It's invoked by the Step Functions
workflow when the final file has been processed.

Environment Variables:
    - KNOWLEDGE_BASE_ID: The ID of the Bedrock Knowledge Base
    - DATA_SOURCE_ID: The ID of the Data Source (S3 bucket)
    - DYNAMODB_TABLE: DynamoDB table for job status
    - AWS_REGION: AWS region

Input from Step Functions:
    {
        "job_id": "string",
        "trigger_kb_sync": true (only when this is the final file)
    }
"""

import json
import logging
import os
import boto3
from botocore.exceptions import ClientError

# Initialize AWS clients
bedrock_kb_client = boto3.client('bedrock-agent')
dynamodb = boto3.resource('dynamodb')
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
KNOWLEDGE_BASE_ID = os.environ.get('KNOWLEDGE_BASE_ID')
DATA_SOURCE_ID = os.environ.get('DATA_SOURCE_ID')
DYNAMODB_TABLE = os.environ.get('DYNAMODB_TABLE')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')


def update_dynamodb_status(job_id, status, details=None):
    """Update job status in DynamoDB"""
    try:
        table = dynamodb.Table(DYNAMODB_TABLE)
        update_expr = 'SET #status = :status'
        expr_values = {':status': status}
        expr_names = {'#status': 'status'}
        
        if details:
            update_expr += ', kb_sync_details = :details'
            expr_values[':details'] = details
        
        table.update_item(
            Key={'job_id': job_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values
        )
        logger.info(f"Updated job {job_id} status to {status}")
    except ClientError as e:
        logger.error(f"Error updating DynamoDB status for job {job_id}: {e}")


def start_kb_ingestion():
    """
    Start Bedrock Knowledge Base ingestion job
    
    This synchronizes the Knowledge Base with all knowledge files
    that were extracted and saved to S3 during PDF processing.
    
    Returns:
        dict: Response with ingestion_job_id if successful, None if KB already syncing
    """
    try:
        logger.info(f"Starting Knowledge Base ingestion - KB ID: {KNOWLEDGE_BASE_ID}, Data Source: {DATA_SOURCE_ID}")
        
        response = bedrock_kb_client.start_ingestion_job(
            knowledgeBaseId=KNOWLEDGE_BASE_ID,
            dataSourceId=DATA_SOURCE_ID
        )
        
        ingestion_job_id = response['ingestionJob']['ingestionJobId']
        ingestion_status = response['ingestionJob']['status']
        
        logger.info(f"Successfully started Knowledge Base ingestion job: {ingestion_job_id}, Status: {ingestion_status}")
        
        return {
            'ingestion_job_id': ingestion_job_id,
            'status': ingestion_status
        }
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_message = e.response.get('Error', {}).get('Message', str(e))
        
        # Log the error but don't fail - Knowledge Base sync is not critical
        logger.warning(f"Error starting Knowledge Base sync (Code: {error_code}): {error_message}")
        
        # Return a partial success response - processing didn't fail
        return {
            'ingestion_job_id': None,
            'status': 'error',
            'error_code': error_code,
            'error_message': error_message
        }


def register_folder_on_first_knowledge_completion(folder_path, job_id):
    """
    Register folder in folder_config table on first knowledge processing
    
    Args:
        folder_path: Folder path (e.g., "フォルダ1/フォルダ1-1")
        job_id: Job ID to set as default_job_id
    
    Returns:
        bool: Success status
    """
    try:
        # Get folder_config table name from environment
        folder_config_table_name = os.environ.get('DYNAMODB_FOLDER_CONFIG_TABLE')
        
        if not folder_config_table_name:
            logger.warning("DYNAMODB_FOLDER_CONFIG_TABLE not configured")
            return False
        
        folder_config_table = dynamodb.Table(folder_config_table_name)
        
        # Check if folder is already registered
        response = folder_config_table.get_item(
            Key={'folder_path': folder_path}
        )
        
        if 'Item' in response:
            # Already registered - just update latest_job_id
            folder_config_table.update_item(
                Key={'folder_path': folder_path},
                UpdateExpression='SET latest_job_id = :ljid',
                ExpressionAttributeValues={
                    ':ljid': job_id
                }
            )
            logger.info(f"Folder {folder_path} already registered. Updated latest_job_id to {job_id}")
            return True
        else:
            # First time - register with default_job_id
            folder_config_table.put_item(
                Item={
                    'folder_path': folder_path,
                    'default_job_id': job_id,
                    'latest_job_id': job_id
                }
            )
            logger.info(f"Registered folder {folder_path} with default_job_id: {job_id}")
            return True
        
    except Exception as e:
        logger.error(f"Error registering folder: {e}", exc_info=True)
        return False


def lambda_handler(event, context):
    """
    Lambda handler for Knowledge Base synchronization
    
    Args:
        event: Step Functions input event containing job_id, trigger_kb_sync, and optionally folder_path and is_new_folder
        context: Lambda context object
        
    Returns:
        dict: Response with status and details
    """
    try:
        logger.info(f"Received event: {json.dumps(event)}")
        
        # Extract parameters from Step Functions
        job_id = event.get('job_id')
        trigger_kb_sync = event.get('trigger_kb_sync', False)
        folder_path = event.get('folder_path')
        is_new_folder = event.get('is_new_folder', False)
        
        if not job_id:
            logger.error("job_id not provided in event")
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'error': 'job_id not provided',
                    'message': 'job_id is required in the event'
                })
            }
        
        if not trigger_kb_sync:
            logger.info(f"Knowledge Base sync not triggered for job {job_id}")
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'Knowledge Base sync not triggered',
                    'job_id': job_id
                })
            }
        
        if not KNOWLEDGE_BASE_ID or not DATA_SOURCE_ID:
            logger.error("KNOWLEDGE_BASE_ID or DATA_SOURCE_ID not configured")
            update_dynamodb_status(
                job_id,
                'failed',
                {
                    'error': 'KB sync configuration missing',
                    'message': 'KNOWLEDGE_BASE_ID or DATA_SOURCE_ID not set'
                }
            )
            return {
                'statusCode': 500,
                'body': json.dumps({
                    'error': 'Configuration error',
                    'message': 'KNOWLEDGE_BASE_ID or DATA_SOURCE_ID not configured'
                })
            }
        
        logger.info(f"Starting Knowledge Base sync for job: {job_id}")
        
        # Register folder if this is the first knowledge processing
        if is_new_folder and folder_path:
            logger.info(f"First knowledge processing detected for folder: {folder_path}")
            register_folder_on_first_knowledge_completion(folder_path, job_id)
        
        # Update DynamoDB to indicate KB sync in progress
        update_dynamodb_status(job_id, 'kb_sync_in_progress')
        
        # Start Knowledge Base ingestion
        kb_response = start_kb_ingestion()
        
        if kb_response.get('ingestion_job_id'):
            # Success - Knowledge Base sync started
            logger.info(f"Knowledge Base sync started successfully for job {job_id}")
            update_dynamodb_status(
                job_id,
                'kb_sync_started',
                {
                    'ingestion_job_id': kb_response['ingestion_job_id'],
                    'status': kb_response['status']
                }
            )
            
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'job_id': job_id,
                    'message': 'Knowledge Base sync started successfully',
                    'ingestion_job_id': kb_response['ingestion_job_id'],
                    'status': kb_response['status']
                })
            }
        else:
            # Warning - KB sync failed but processing continues
            logger.warning(f"Knowledge Base sync encountered an issue for job {job_id}")
            update_dynamodb_status(
                job_id,
                'kb_sync_error',
                {
                    'error_code': kb_response.get('error_code'),
                    'error_message': kb_response.get('error_message')
                }
            )
            
            return {
                'statusCode': 200,  # Return 200 to indicate processing success
                'body': json.dumps({
                    'job_id': job_id,
                    'message': 'Knowledge Base sync encountered an issue but processing completed',
                    'error_code': kb_response.get('error_code'),
                    'error_message': kb_response.get('error_message')
                })
            }
    
    except Exception as e:
        logger.error(f"Unexpected error in Knowledge Base sync: {str(e)}", exc_info=True)
        job_id = event.get('job_id', 'unknown')
        
        update_dynamodb_status(
            job_id,
            'kb_sync_error',
            {
                'error': 'Unexpected error',
                'message': str(e)
            }
        )
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': 'Internal server error',
                'message': str(e)
            })
        }
