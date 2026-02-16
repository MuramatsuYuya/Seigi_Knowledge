"""
PDF OCR System - History Manager Lambda

Handles chat history queries and management.
Separate from knowledge querier to keep concerns isolated.
"""

import json
import boto3
import os
import logging
from datetime import datetime, timezone, timedelta
from botocore.exceptions import ClientError
from botocore.config import Config
from boto3.dynamodb.conditions import Key
from decimal import Decimal
from urllib.parse import quote

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ===== Configuration =====
DYNAMODB_REGION = os.environ.get("DYNAMODB_REGION", "us-west-2")
DATA_S3_BUCKET = os.environ.get("DATA_S3_BUCKET")
config = Config(
    connect_timeout=int(os.environ.get("HTTP_CONNECT_TIMEOUT", "10")),
    read_timeout=int(os.environ.get("HTTP_READ_TIMEOUT", "60")),
    retries={'max_attempts': int(os.environ.get("HTTP_RETRIES", "3"))}
)

# JST timezone (UTC+9)
JST = timezone(timedelta(hours=9))

# ===== Environment Variables =====
DYNAMODB_CHAT_HISTORY_TABLE = os.environ.get("DYNAMODB_CHAT_HISTORY_TABLE")

# Lazy-create AWS resources
_dynamodb = None
_chat_history_table = None
_s3_client = None


def get_s3_client():
    """Get or create S3 client"""
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client('s3', region_name=DYNAMODB_REGION, config=config)
    return _s3_client


def generate_presigned_url(s3_key, expiration=604800):
    """
    Generate a new presigned URL for an S3 object.
    
    Args:
        s3_key: S3 object key (e.g., 'PDF/filename.pdf')
        expiration: URL expiration time in seconds (default: 7 days)
    
    Returns:
        Presigned URL string
    """
    if not DATA_S3_BUCKET:
        logger.error("DATA_S3_BUCKET environment variable is not set")
        return None
    
    try:
        s3_client = get_s3_client()
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': DATA_S3_BUCKET, 'Key': s3_key},
            ExpiresIn=expiration
        )
        logger.info(f"Generated presigned URL for bucket={DATA_S3_BUCKET}, key={s3_key}")
        return url
    except Exception as e:
        logger.error(f"Error generating presigned URL for bucket={DATA_S3_BUCKET}, key={s3_key}: {e}")
        return None


def decimal_to_native(obj):
    """
    Convert DynamoDB Decimal types to native Python types for JSON serialization.
    """
    if isinstance(obj, list):
        return [decimal_to_native(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: decimal_to_native(v) for k, v in obj.items()}
    elif isinstance(obj, Decimal):
        # Convert to int if it's a whole number, otherwise float
        if obj % 1 == 0:
            return int(obj)
        else:
            return float(obj)
    else:
        return obj


def get_chat_history_table():
    """Lazy-initialize DynamoDB table"""
    global _dynamodb, _chat_history_table
    if _dynamodb is None:
        _dynamodb = boto3.resource('dynamodb', region_name=DYNAMODB_REGION)
    if _chat_history_table is None:
        if not DYNAMODB_CHAT_HISTORY_TABLE:
            logger.warning('DYNAMODB_CHAT_HISTORY_TABLE not configured')
            return None
        _chat_history_table = _dynamodb.Table(DYNAMODB_CHAT_HISTORY_TABLE)
    return _chat_history_table


def get_chat_history_summaries(chat_session_id=None, mode=None):
    """
    Retrieve all chat history summaries grouped by chat_session_id.
    Each chat_session_id represents one conversation session.
    Args:
        chat_session_id: Optional specific session ID to filter
        mode: Optional mode filter ('default', 'verification', 'specification')
    Returns: list of conversation summaries sorted by timestamp (newest first)
    """
    try:
        table = get_chat_history_table()
        if not table:
            return []

        # Scan all messages without filtering (get all history)
        response = table.scan()

        messages = response.get('Items', [])
        logger.info(f"Retrieved {len(messages)} total messages from chat history")
        
        # Group messages by chat_session_id with mode filtering
        sessions = {}
        for message in messages:
            session_id = message.get('chat_session_id', 'unknown')
            
            # Filter by mode prefix
            if mode:
                if mode == 'verification' and not session_id.startswith('verification_'):
                    continue
                elif mode == 'specification' and not session_id.startswith('specification_'):
                    continue
                elif mode == 'default' and (session_id.startswith('verification_') or session_id.startswith('specification_')):
                    continue
            
            if session_id not in sessions:
                sessions[session_id] = []
            sessions[session_id].append(message)
        
        logger.info(f"Found {len(sessions)} unique chat sessions")
        
        # Create summaries for each session
        summaries = []
        for session_id, session_messages in sessions.items():
            # Sort messages by timestamp (oldest first for processing)
            session_messages.sort(key=lambda x: x.get('timestamp', ''))
            
            # Find the first user message as the conversation starter
            first_user_message = None
            message_count = len(session_messages)
            
            for msg in session_messages:
                if msg.get('role') == 'user':
                    first_user_message = msg
                    break
            
            if first_user_message:
                summaries.append({
                    'chat_session_id': session_id,
                    'first_question': first_user_message.get('content', ''),
                    'timestamp': first_user_message.get('timestamp', ''),
                    'message_id': first_user_message.get('message_id', ''),
                    'message_count': message_count
                })
        
        # Sort summaries by timestamp (newest first)
        summaries.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        logger.info(f"Created {len(summaries)} conversation summaries")
        return summaries

    except ClientError as e:
        logger.error(f"Error retrieving chat history summaries: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error retrieving chat history summaries: {e}")
        return []


def get_chat_history_by_id(message_id):
    """
    Retrieve full conversation for a specific message_id's chat_session_id.
    Returns ALL messages in that chat session.
    Returns: dict with 'messages' (array of all messages), 'sources', 'chat_session_id', 'selected_folder_paths', 'selected_job_id'
    """
    try:
        table = get_chat_history_table()
        if not table:
            return None

        # Scan all messages to find the one with this message_id
        response = table.scan()
        all_messages = response.get('Items', [])
        
        # Find the message with the given message_id
        target_message = None
        for msg in all_messages:
            if msg.get('message_id') == message_id:
                target_message = msg
                break
        
        if not target_message:
            logger.warning(f"Message not found: {message_id}")
            return None
        
        # Get chat_session_id from the message
        chat_session_id = target_message.get('chat_session_id')
        if not chat_session_id:
            logger.warning(f"Message {message_id} has no chat_session_id")
            return None
        
        # Filter messages by chat_session_id
        session_messages = [msg for msg in all_messages if msg.get('chat_session_id') == chat_session_id]
        
        # Sort by timestamp (oldest first for display)
        session_messages.sort(key=lambda x: x.get('timestamp', ''))
        
        logger.info(f"Retrieved {len(session_messages)} messages for session {chat_session_id}")
        
        # Extract folder selection info from first user message
        selected_folder_paths = None
        selected_job_id = None
        
        for msg in session_messages:
            if msg.get('role') == 'user':
                if 'selected_folder_paths' in msg:
                    selected_folder_paths = msg.get('selected_folder_paths')
                    logger.info(f"Found selected_folder_paths in first user message: {selected_folder_paths}")
                if 'selected_job_id' in msg:
                    selected_job_id = msg.get('selected_job_id')
                    logger.info(f"Found selected_job_id in first user message: {selected_job_id}")
                break  # Only check first user message
        
        # Collect all sources from all assistant messages
        sources_dict = {}
        for msg in session_messages:
            if msg.get('role') == 'assistant' and 'sources' in msg:
                sources = msg.get('sources', [])
                if isinstance(sources, list):
                    for source in sources:
                        if isinstance(source, dict):
                            s3_key = source.get('s3Key')
                            
                            if s3_key and s3_key not in sources_dict:
                                # Generate fresh presigned URL
                                presigned_url = generate_presigned_url(s3_key)
                                
                                if presigned_url:
                                    file_name = source.get('fileName') or source.get('pdfFileName') or s3_key.split('/')[-1]
                                    source_copy = {
                                        'fileName': file_name,
                                        's3Key': s3_key,
                                        'presignedUrl': presigned_url
                                    }
                                    sources_dict[s3_key] = source_copy
        
        # Build response with ALL messages in the session
        result = {
            'chat_session_id': chat_session_id,
            'messages': session_messages,
            'sources': list(sources_dict.values()),
            'message_count': len(session_messages)
        }
        
        # Add folder selection info if available
        if selected_folder_paths:
            result['selected_folder_paths'] = selected_folder_paths
        if selected_job_id:
            result['selected_job_id'] = selected_job_id
        
        logger.info(f"Retrieved history with {len(session_messages)} messages and {len(result['sources'])} sources")
        if selected_folder_paths:
            logger.info(f"Session had selected_folder_paths: {selected_folder_paths}")
        
        return result

    except ClientError as e:
        logger.error(f"Error retrieving chat history detail: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error retrieving chat history detail: {e}")
        return None


def update_feedback(message_id, rating=None, comment=None):
    """
    Update rating and/or comment for a message in DynamoDB.
    
    Args:
        message_id: The message ID to update
        rating: Integer 1-10 or None
        comment: Comment text or None
    
    Returns:
        dict with success status or error
    """
    try:
        table = get_chat_history_table()
        if not table:
            logger.error("Chat history table not configured")
            return {'success': False, 'error': 'テーブルが設定されていません'}
        
        # Scan to find the message (since message_id is not the primary key)
        response = table.scan()
        all_messages = response.get('Items', [])
        
        # Find message with matching message_id
        target_message = None
        for msg in all_messages:
            if msg.get('message_id') == message_id:
                target_message = msg
                break
        
        if not target_message:
            logger.warning(f"Message not found: {message_id}")
            return {'success': False, 'error': 'メッセージが見つかりません'}
        
        # DynamoDB requires primary key to update
        # We need job_id and message_id as the key
        job_id = target_message.get('job_id')
        
        if not job_id:
            logger.error(f"Message {message_id} has no job_id")
            return {'success': False, 'error': 'ジョブIDが見つかりません'}
        
        # Build the update expression dynamically
        update_parts = []
        expression_values = {}
        expression_attribute_names = {}
        
        if rating is not None:
            update_parts.append('rating = :rating')
            expression_values[':rating'] = rating
        
        if comment is not None:
            # Use placeholder for 'comment' as it may be a reserved word
            update_parts.append('#c = :comment')
            expression_values[':comment'] = comment
            expression_attribute_names['#c'] = 'comment'
        
        if not update_parts:
            logger.warning(f"No updates specified for message {message_id}")
            return {'success': False, 'error': '更新内容が指定されていません'}
        
        # Add updated_at timestamp
        update_parts.append('updated_at = :updated_at')
        expression_values[':updated_at'] = datetime.now(JST).isoformat()
        
        # Build the Key for the item (message_id as sort key with job_id as partition key)
        key = {
            'job_id': job_id,
            'message_id': message_id
        }
        
        update_expression = 'SET ' + ', '.join(update_parts)
        
        logger.info(f"Update expression: {update_expression}")
        logger.info(f"Expression values: {expression_values}")
        logger.info(f"Expression attribute names: {expression_attribute_names}")
        logger.info(f"Update key: {key}")
        
        # Execute update
        kwargs = {
            'Key': key,
            'UpdateExpression': update_expression,
            'ExpressionAttributeValues': expression_values,
            'ReturnValues': 'ALL_NEW'
        }
        
        # Only add ExpressionAttributeNames if we have any
        if expression_attribute_names:
            kwargs['ExpressionAttributeNames'] = expression_attribute_names
        
        response = table.update_item(**kwargs)
        
        logger.info(f"Update successful for message {message_id}")
        updated_item = response.get('Attributes', {})
        updated_item = decimal_to_native(updated_item)
        
        return {
            'success': True,
            'message': 'フィードバックが保存されました',
            'updated_item': updated_item
        }
        
    except ClientError as e:
        logger.error(f"Error updating feedback: {e}")
        return {'success': False, 'error': f'DynamoDBエラー: {str(e)[:100]}'}
    except Exception as e:
        logger.error(f"Unexpected error updating feedback: {e}")
        return {'success': False, 'error': f'エラーが発生しました: {str(e)[:100]}'}



def search_chat_history(chat_session_id, search_query, mode=None):
    """
    Search chat history for messages containing search_query.
    Args:
        chat_session_id: Chat session ID (optional)
        search_query: Search query string
        mode: Mode filter ('default', 'verification', 'specification')
    Returns: list of matching conversations with snippets
    
    Note: Searches across ALL sessions for the search query,
    then groups results by session and conversation
    """

    try:
        table = get_chat_history_table()
        if not table:
            return []

        # Scan ALL messages in the table (not just this session)
        # to find all conversations containing the search query
        logger.info(f"[search_chat_history] Scanning table for query: {search_query}")
        
        # Use scan instead of query to search across all sessions
        response = table.scan()
        messages = response.get('Items', [])
        
        # Handle pagination if needed
        while 'LastEvaluatedKey' in response:
            response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
            messages.extend(response.get('Items', []))
        
        logger.info(f"[search_chat_history] Scanned {len(messages)} total messages")
        search_lower = search_query.lower()
        
        # Group messages by session and timestamp (to reconstruct conversations)
        # Dictionary: session_id -> timestamp -> list of messages
        sessions_by_id = {}
        
        for message in messages:
            session_id = message.get('chat_session_id', '')
            
            # Filter by mode prefix
            if mode:
                if mode == 'verification' and not session_id.startswith('verification_'):
                    continue
                elif mode == 'specification' and not session_id.startswith('specification_'):
                    continue
                elif mode == 'default' and (session_id.startswith('verification_') or session_id.startswith('specification_')):
                    continue
            
            timestamp = message.get('timestamp', '')
            
            if session_id not in sessions_by_id:
                sessions_by_id[session_id] = {}
            if timestamp not in sessions_by_id[session_id]:
                sessions_by_id[session_id][timestamp] = []
            
            sessions_by_id[session_id][timestamp].append(message)
        
        logger.info(f"[search_chat_history] Grouped into {len(sessions_by_id)} sessions")
        
        # Find matching conversations
        matching_conversations = []
        
        for session_id in sorted(sessions_by_id.keys()):
            session_messages = sessions_by_id[session_id]
            
            # Sort by timestamp to reconstruct conversation flow
            sorted_times = sorted(session_messages.keys())
            
            current_conversation = None
            
            for timestamp in sorted_times:
                for message in session_messages[timestamp]:
                    role = message.get('role', '')
                    content = message.get('content', '')
                    message_id = message.get('message_id', '')
                    
                    if role == 'user':
                        # Start new conversation
                        if current_conversation:
                            matching_conversations.append(current_conversation)
                        
                        matches = search_lower in content.lower()
                        current_conversation = {
                            'first_question': content,
                            'timestamp': timestamp,
                            'message_id': message_id,
                            'message_count': 1,
                            'has_match': matches,
                            'matched_content': content if matches else None
                        }
                    elif role == 'assistant' and current_conversation:
                        matches = search_lower in content.lower()
                        if matches:
                            current_conversation['has_match'] = True
                            if not current_conversation['matched_content']:
                                current_conversation['matched_content'] = content
                        
                        current_conversation['message_count'] += 1
            
            # Add last conversation in this session if it matches
            if current_conversation:
                matching_conversations.append(current_conversation)
        
        # Filter to only those that match
        results = [c for c in matching_conversations if c['has_match']]
        logger.info(f"Found {len(results)} matching conversations for query: {search_query}")
        
        return results

    except ClientError as e:
        logger.error(f"Error searching chat history: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error searching chat history: {e}")
        return []


def lambda_handler(event, context):
    """
    POST /api/history
    
    Request body:
    {
        "chat_session_id": "xxxxxxxx-xxxx",  (required)
        "action": "get-history|get-history-detail|search",  (required)
        "message_id": "...",                  (required if action=get-history-detail)
        "search_query": "検索テキスト"         (required if action=search)
    }
    
    Response:
    {
        "statusCode": 200,
        "body": {
            "histories": [...],              (if action=get-history)
            "history": {...},                (if action=get-history-detail)
            "results": [...]                 (if action=search)
        }
    }
    """
    
    logger.info(f"Event received for action")
    
    try:
        # Parse request body
        if isinstance(event.get('body'), str):
            body = json.loads(event['body'])
        else:
            body = event.get('body', {})

        logger.info(f"Parsed body: {json.dumps(body)}")

        chat_session_id = (body.get('chat_session_id', '') or '').strip()
        action = (body.get('action', 'get-history') or 'get-history').strip().lower()
        
        logger.info(f"chat_session_id: {chat_session_id}, action: {action}")
        
        # Validate chat_session_id (required for most actions except update-feedback)
        if not chat_session_id and action != 'update-feedback':
            logger.error(f"Missing chat_session_id for action: {action}")
            return {
                'statusCode': 400,
                'headers': {
                    'Access-Control-Allow-Origin': '*',
                    'Content-Type': 'application/json'
                },
                'body': json.dumps({
                    'error': 'チャットセッションIDが指定されていません'
                })
            }
        
        # Handle different actions
        if action == 'get-history':
            mode = body.get('mode', 'default')
            logger.info(f"Getting history summaries for chat_session_id: {chat_session_id}, mode: {mode}")
            histories = get_chat_history_summaries(chat_session_id, mode=mode)
            
            logger.info(f"Returning {len(histories)} histories")
            
            # Convert Decimal to native types
            histories = decimal_to_native(histories)
            
            return {
                'statusCode': 200,
                'headers': {
                    'Access-Control-Allow-Origin': '*',
                    'Content-Type': 'application/json'
                },
                'body': json.dumps({
                    'histories': histories
                }, ensure_ascii=False)
            }
        
        elif action == 'get-history-detail':
            message_id = (body.get('message_id', '') or '').strip()
            if not message_id:
                logger.error("Missing message_id for get-history-detail action")
                return {
                    'statusCode': 400,
                    'headers': {
                        'Access-Control-Allow-Origin': '*',
                        'Content-Type': 'application/json'
                    },
                    'body': json.dumps({
                        'error': 'メッセージIDが指定されていません'
                    })
                }
            
            logger.info(f"Getting history detail for message_id: {message_id}")
            history_detail = get_chat_history_by_id(message_id)
            
            if not history_detail:
                return {
                    'statusCode': 404,
                    'headers': {
                        'Access-Control-Allow-Origin': '*',
                        'Content-Type': 'application/json'
                    },
                    'body': json.dumps({
                        'error': '履歴が見つかりません'
                    })
                }
            
            # Convert Decimal to native types
            history_detail = decimal_to_native(history_detail)
            
            return {
                'statusCode': 200,
                'headers': {
                    'Access-Control-Allow-Origin': '*',
                    'Content-Type': 'application/json'
                },
                'body': json.dumps({
                    'history': history_detail
                }, ensure_ascii=False)
            }
        
        elif action == 'search':
            search_query = (body.get('search_query', '') or '').strip()
            mode = body.get('mode', 'default')
            if not search_query:
                logger.error("Missing search_query for search action")
                return {
                    'statusCode': 400,
                    'headers': {
                        'Access-Control-Allow-Origin': '*',
                        'Content-Type': 'application/json'
                    },
                    'body': json.dumps({
                        'error': '検索キーワードが指定されていません'
                    })
                }
            
            logger.info(f"Searching history for: {search_query}, mode: {mode}")
            results = search_chat_history(chat_session_id, search_query, mode=mode)
            
            # Convert Decimal to native types
            results = decimal_to_native(results)
            
            return {
                'statusCode': 200,
                'headers': {
                    'Access-Control-Allow-Origin': '*',
                    'Content-Type': 'application/json'
                },
                'body': json.dumps({
                    'results': results
                }, ensure_ascii=False)
            }
        
        elif action == 'update-feedback':
            # Handle rating and comment updates
            message_id = (body.get('message_id', '') or '').strip()
            if not message_id:
                logger.error("Missing message_id for update-feedback action")
                return {
                    'statusCode': 400,
                    'headers': {
                        'Access-Control-Allow-Origin': '*',
                        'Content-Type': 'application/json'
                    },
                    'body': json.dumps({
                        'error': 'メッセージIDが指定されていません'
                    })
                }
            
            rating = body.get('rating')
            comment = body.get('comment')
            
            # Validate rating if provided
            if rating is not None:
                try:
                    rating = int(rating)
                    if rating < 1 or rating > 10:
                        raise ValueError("Rating must be between 1 and 10")
                except (ValueError, TypeError):
                    return {
                        'statusCode': 400,
                        'headers': {
                            'Access-Control-Allow-Origin': '*',
                            'Content-Type': 'application/json'
                        },
                        'body': json.dumps({
                            'error': '評価は1～10の数値である必要があります'
                        })
                    }
            
            logger.info(f"Updating feedback for message_id: {message_id}, rating: {rating}, comment: {comment}")
            result = update_feedback(message_id, rating=rating, comment=comment)
            
            if not result.get('success'):
                return {
                    'statusCode': 400,
                    'headers': {
                        'Access-Control-Allow-Origin': '*',
                        'Content-Type': 'application/json'
                    },
                    'body': json.dumps({
                        'error': result.get('error', 'フィードバック更新に失敗しました')
                    })
                }
            
            return {
                'statusCode': 200,
                'headers': {
                    'Access-Control-Allow-Origin': '*',
                    'Content-Type': 'application/json'
                },
                'body': json.dumps({
                    'message': result.get('message', 'フィードバックが保存されました'),
                    'updated_item': result.get('updated_item', {})
                }, ensure_ascii=False)
            }
        
        else:
            logger.error(f"Unknown action: {action}")
            return {
                'statusCode': 400,
                'headers': {
                    'Access-Control-Allow-Origin': '*',
                    'Content-Type': 'application/json'
                },
                'body': json.dumps({
                    'error': '不正なアクションです'
                })
            }

        
    except Exception as e:
        logger.error(f"Error processing request: {e}", exc_info=True)
        
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Full traceback: {error_details}")
        
        return {
            'statusCode': 500,
            'headers': {
                'Access-Control-Allow-Origin': '*',
                'Content-Type': 'application/json'
            },
            'body': json.dumps({
                'error': 'エラーが発生しました',
                'details': str(e)[:200],
                'traceback': error_details[:500]
            }, ensure_ascii=False)
        }
