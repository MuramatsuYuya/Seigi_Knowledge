"""
Poll Status Lambda - Query Status Checker

Retrieves the status of an async knowledge query:
1. Queries DynamoDB by query_id
2. Returns current status (processing/completed/failed)
3. Returns answer and sources when completed
"""

import json
import boto3
import os
import logging
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS Clients
dynamodb = boto3.resource('dynamodb')

# Environment variables
QUERY_STATUS_TABLE = os.environ['QUERY_STATUS_TABLE']

# DynamoDB table
query_status_table = dynamodb.Table(QUERY_STATUS_TABLE)


def lambda_handler(event, context):
    """
    GET /api/knowledge-query/status/{query_id}
    
    Response (processing):
    {
        "status": "processing",
        "query": "質問テキスト",
        "created_at": "2024-11-20T12:00:00"
    }
    
    Response (completed):
    {
        "status": "completed",
        "query": "質問テキスト",
        "answer": "回答テキスト",
        "sources": [...],
        "created_at": "2024-11-20T12:00:00",
        "updated_at": "2024-11-20T12:00:30"
    }
    
    Response (failed):
    {
        "status": "failed",
        "query": "質問テキスト",
        "error": "エラーメッセージ",
        "created_at": "2024-11-20T12:00:00",
        "updated_at": "2024-11-20T12:00:30"
    }
    """
    try:
        logger.info(f"Event: {json.dumps(event)}")
        
        # Extract query_id from path parameters
        path_parameters = event.get('pathParameters', {})
        query_id = path_parameters.get('query_id')
        
        if not query_id:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'query_id is required'
                })
            }
        
        # Get status from DynamoDB
        response = query_status_table.get_item(
            Key={'query_id': query_id}
        )
        
        if 'Item' not in response:
            return {
                'statusCode': 404,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Query not found',
                    'message': f'No query found with id: {query_id}'
                })
            }
        
        item = response['Item']
        
        # Build response based on status
        status = item.get('status', 'unknown')
        result = {
            'status': status,
            'query': item.get('query', ''),
            'created_at': item.get('created_at', ''),
            'updated_at': item.get('updated_at', '')
        }
        
        # Add status-specific fields
        if status == 'completed':
            result['answer'] = item.get('answer', '')
            result['sources'] = item.get('sources', [])
            # Include message_id for feedback functionality
            if item.get('message_id'):
                result['message_id'] = item.get('message_id')
        elif status == 'failed':
            result['error'] = item.get('error', 'Unknown error')
        
        logger.info(f"Query status: query_id={query_id}, status={status}")
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(result, ensure_ascii=False)
        }
        
    except ClientError as e:
        logger.error(f"DynamoDB error: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Database error',
                'message': str(e)
            })
        }
    except Exception as e:
        logger.error(f"Error polling status: {e}", exc_info=True)
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
