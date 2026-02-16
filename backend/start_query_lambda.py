"""
Start Query Lambda - Async Knowledge Query Initiator

Starts an asynchronous knowledge base query:
1. Generates unique query_id
2. Saves initial status='processing' to DynamoDB
3. Invokes KnowledgeQuerierLambda asynchronously
4. Returns query_id to client for polling
"""

import json
import boto3
import os
import uuid
from datetime import datetime, timedelta
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS Clients
dynamodb = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')

# Environment variables
QUERY_STATUS_TABLE = os.environ['QUERY_STATUS_TABLE']
KNOWLEDGE_QUERIER_LAMBDA_ARN = os.environ['KNOWLEDGE_QUERIER_LAMBDA_ARN']

# DynamoDB table
query_status_table = dynamodb.Table(QUERY_STATUS_TABLE)


def lambda_handler(event, context):
    """
    POST /api/knowledge-query/start
    
    Request body:
    {
        "jobId": "20251120120000",
        "chat_session_id": "session-uuid",
        "query": "質問テキスト",
        "folder_paths": ["path1", "path2"],  // Optional
        "use_agent": true  // Optional
    }
    
    Response:
    {
        "query_id": "abc-123-def-456",
        "status": "processing"
    }
    """
    try:
        logger.info(f"Event: {json.dumps(event)}")
        
        # Parse request body
        if isinstance(event.get('body'), str):
            body = json.loads(event['body'])
        else:
            body = event.get('body', {})
        
        # Extract parameters
        job_id = body.get('jobId', '').strip()
        chat_session_id = body.get('chat_session_id', '').strip()
        query = body.get('query', '').strip()
        folder_paths = body.get('folder_paths', [])
        folder_default_job_ids = body.get('folder_default_job_ids', {})
        use_agent = body.get('use_agent', True)
        agent_type = body.get('agent_type', 'default')  # Agentタイプ: 'default', 'verification', 'specification'
        
        # Validation
        if not query:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Query is required'
                })
            }
        
        if not chat_session_id:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'chat_session_id is required'
                })
            }
        
        # Generate unique query_id
        query_id = str(uuid.uuid4())
        
        # Calculate TTL (1 hour from now)
        ttl_timestamp = int((datetime.now() + timedelta(hours=1)).timestamp())
        
        # Save initial status to DynamoDB
        query_status_table.put_item(Item={
            'query_id': query_id,
            'status': 'processing',
            'job_id': job_id or 'temp',
            'chat_session_id': chat_session_id,
            'query': query,
            'folder_paths': folder_paths,
            'use_agent': use_agent,
            'agent_type': agent_type,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat(),
            'ttl': ttl_timestamp
        })
        
        logger.info(f"Created query status: query_id={query_id}, status=processing")
        
        # Prepare payload for KnowledgeQuerierLambda
        querier_payload = {
            'query_id': query_id,  # Signal async mode
            'jobId': job_id,
            'chat_session_id': chat_session_id,
            'query': query,
            'folder_paths': folder_paths,
            'folder_default_job_ids': folder_default_job_ids,
            'use_agent': use_agent,
            'agent_type': agent_type
        }
        
        # Invoke KnowledgeQuerierLambda asynchronously
        lambda_client.invoke(
            FunctionName=KNOWLEDGE_QUERIER_LAMBDA_ARN,
            InvocationType='Event',  # Asynchronous invocation
            Payload=json.dumps(querier_payload)
        )
        
        logger.info(f"Invoked KnowledgeQuerierLambda asynchronously for query_id={query_id}")
        
        # Return query_id to client
        return {
            'statusCode': 202,  # Accepted
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'query_id': query_id,
                'status': 'processing'
            })
        }
        
    except Exception as e:
        logger.error(f"Error starting query: {e}", exc_info=True)
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
