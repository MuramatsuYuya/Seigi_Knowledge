"""
PDF OCR System - Knowledge Querier Lambda

Handles knowledge base queries using Bedrock Knowledge Base Retrieve & Generate API.
Supports job-based filtering and stores chat history in DynamoDB.
"""

import json
import boto3
import os
import logging
import re
import uuid
from datetime import datetime, timezone, timedelta
from botocore.exceptions import ClientError
from botocore.config import Config
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ===== 固定設定 =====
# Configurable regions and HTTP client config
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-west-2")
DYNAMODB_REGION = os.environ.get("DYNAMODB_REGION", "us-west-2")
config = Config(
    connect_timeout=int(os.environ.get("HTTP_CONNECT_TIMEOUT", "10")),
    read_timeout=int(os.environ.get("HTTP_READ_TIMEOUT", "60")),
    retries={'max_attempts': int(os.environ.get("HTTP_RETRIES", "3"))}
)

# JST timezone (UTC+9)
JST = timezone(timedelta(hours=9))

# ===== 環境変数 (読み取りは安全に行い、必須項目はランタイムで検証する) =====
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE")
DYNAMODB_CHAT_HISTORY_TABLE = os.environ.get("DYNAMODB_CHAT_HISTORY_TABLE")
DYNAMODB_FOLDER_CONFIG_TABLE = os.environ.get("DYNAMODB_FOLDER_CONFIG_TABLE")
QUERY_STATUS_TABLE = os.environ.get("QUERY_STATUS_TABLE")  # 非同期クエリステータステーブル
S3_BUCKET = os.environ.get("S3_BUCKET", "doctoknow-seigi25-data")
KNOWLEDGE_BASE_ID = os.environ.get("KNOWLEDGE_BASE_ID")
DATA_SOURCE_ID = os.environ.get("DATA_SOURCE_ID")
BEDROCK_MODEL_ARN = os.environ.get("BEDROCK_MODEL_ARN")
BEDROCK_AGENT_ID = os.environ.get("BEDROCK_AGENT_ID", "M89ZN5FKB4")  # Default Agent ID
BEDROCK_AGENT_ALIAS_ID = os.environ.get("BEDROCK_AGENT_ALIAS_ID", "TSTALIASID")  # Default Agent Alias ID
VERIFICATION_AGENT_ID = os.environ.get("VERIFICATION_AGENT_ID", "")  # Verification Plan Agent ID
VERIFICATION_AGENT_ALIAS_ID = os.environ.get("VERIFICATION_AGENT_ALIAS_ID", "")  # Verification Plan Agent Alias ID
SPECIFICATION_AGENT_ID = os.environ.get("SPECIFICATION_AGENT_ID", "")  # Specification Agent ID
SPECIFICATION_AGENT_ALIAS_ID = os.environ.get("SPECIFICATION_AGENT_ALIAS_ID", "")  # Specification Agent Alias ID
DEFAULT_JOB_ID = os.environ.get("JOBID", "")  # デフォルトジョブID (オプション)
MAX_CONTEXT_LENGTH = int(os.environ.get("MAX_CONTEXT_LENGTH", "10000"))  # 会話履歴の最大文字数

# Lazy-create AWS resources (create when needed to avoid import-time failures)
_dynamodb = None
_jobs_table = None
_chat_history_table = None
_folder_config_table = None
_s3_client = None
_bedrock_agent_runtime = None

# S3 URIs (use configured bucket)
KNOWLEDGE_BASE_PREFIX = f"s3://{S3_BUCKET}/Knowledge"
PDF_PREFIX = f"s3://{S3_BUCKET}/PDF"


def get_s3_client():
    """Lazy-create S3 client"""
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client('s3', region_name=BEDROCK_REGION, config=config)
    return _s3_client


def generate_presigned_url(bucket_name, object_key, expiration=3600):
    """
    Generate presigned URL for S3 object.
    Allows frontend to fetch PDF files directly from S3 without CORS issues.
    """
    try:
        s3_client = get_s3_client()
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': object_key},
            ExpiresIn=expiration
        )
        return url
    except Exception as e:
        logger.error(f"Error generating presigned URL: {e}")
        return None


def extract_job_id_and_pdf_from_uri(source_uri):
    """
    Extract job_id and PDF filename from source URI.
    URI format: s3://doctoknow-seigi25-data/Knowledge/{job_id}/filename.txt
    Returns: (job_id, pdf_filename.pdf)
    """
    try:
        # Extract path from S3 URI. Support configured bucket name.
        prefix = f"s3://{S3_BUCKET}/Knowledge/"
        
        if source_uri.startswith(prefix):
            path = source_uri.replace(prefix, "")
        else:
            # Fallback: try stripping a generic Knowledge/ segment
            path = source_uri.split("/Knowledge/", 1)[-1]
        
        parts = path.split("/", 1)
        
        if len(parts) == 2:
            job_id = parts[0]
            txt_filename = parts[1].split("/")[-1]
            # Convert .txt to .pdf
            pdf_filename = txt_filename.replace(".txt", ".pdf")
            return job_id, pdf_filename
        
        logger.warning(f"Could not extract job_id and filename from URI: {source_uri}")
        return None, None
    except Exception as e:
        logger.error(f"Error extracting job_id from URI: {e}")
        return None, None


def build_pdf_source_uri(job_id, pdf_filename):
    """Build PDF S3 URI from job_id and filename."""
    return f"{PDF_PREFIX}/{job_id}/{pdf_filename}"


def get_chat_history(job_id, chat_session_id):
    """
    Retrieve chat history for a specific chat_session_id from DynamoDB.
    Uses GSI (chat_session_id-index) for efficient querying.
    Returns: list of messages sorted by message_id (oldest first)
    """
    try:
        global _dynamodb, _chat_history_table
        if _dynamodb is None:
            _dynamodb = boto3.resource('dynamodb', region_name=DYNAMODB_REGION)
        if _chat_history_table is None:
            if not DYNAMODB_CHAT_HISTORY_TABLE:
                logger.warning('DYNAMODB_CHAT_HISTORY_TABLE not configured')
                return []
            _chat_history_table = _dynamodb.Table(DYNAMODB_CHAT_HISTORY_TABLE)

        # Query using GSI
        response = _chat_history_table.query(
            IndexName='chat_session_id-index',
            KeyConditionExpression=Key('chat_session_id').eq(chat_session_id),
            ScanIndexForward=True  # Oldest first
        )

        messages = response.get('Items', [])
        logger.info(f"Retrieved {len(messages)} messages for chat_session_id: {chat_session_id}")
        return messages

    except ClientError as e:
        logger.error(f"Error retrieving chat history: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error retrieving chat history: {e}")
        return []


def get_job_ids_from_folder_path(folder_path):
    """
    DynamoDB GSI (folder_path-index) から folder_path に対応するすべての job_id を取得 (v2)
    
    Args:
        folder_path: "フォルダ1/フォルダ1-1"
    
    Returns:
        list: [job_id1, job_id2, ...] (unique job_ids)
    """
    try:
        global _dynamodb, _jobs_table
        if _dynamodb is None:
            _dynamodb = boto3.resource('dynamodb', region_name=DYNAMODB_REGION)
        if _jobs_table is None:
            if not DYNAMODB_TABLE:
                logger.warning('DYNAMODB_TABLE not configured')
                return []
            _jobs_table = _dynamodb.Table(DYNAMODB_TABLE)
        
        # GSI クエリ: folder_path-index (ページネーション対応)
        job_ids = []
        last_evaluated_key = None
        
        while True:
            query_params = {
                'IndexName': 'folder_path-index',
                'KeyConditionExpression': Key('folder_path').eq(folder_path),
                'ProjectionExpression': 'job_id'
            }
            if last_evaluated_key:
                query_params['ExclusiveStartKey'] = last_evaluated_key
            
            response = _jobs_table.query(**query_params)
            job_ids.extend([item['job_id'] for item in response.get('Items', [])])
            
            last_evaluated_key = response.get('LastEvaluatedKey')
            if not last_evaluated_key:
                break
        
        # 重複除去
        unique_job_ids = list(set(job_ids))
        logger.info(f"Found {len(unique_job_ids)} unique job_ids for folder_path: {folder_path}")
        return unique_job_ids
        
    except ClientError as e:
        logger.error(f"Error querying folder_path-index: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error querying folder_path: {e}")
        return []


def build_context_with_history(chat_history, current_query):
    """
    Build Bedrock context with chat history and current query.
    Respects MAX_CONTEXT_LENGTH limit.
    Returns: formatted query string with history
    """
    try:
        history_text = ""
        total_length = 0

        # Process messages from oldest to newest
        for message in chat_history:
            role = message.get('role', 'unknown')
            content = message.get('content', '')
            timestamp = message.get('timestamp', '')

            # Extract HH:MM:SS from ISO timestamp
            time_str = ""
            if timestamp:
                try:
                    # ISO format: 2025-10-28T19:00:05+09:00
                    time_str = timestamp.split('T')[1].split('+')[0]
                except:
                    time_str = ""

            # Format: [HH:MM:SS] Role: content
            role_label = "ユーザー" if role == "user" else "アシスタント"
            message_text = f"[{time_str}] {role_label}: {content}\n"
            message_length = len(message_text)

            # Check if adding this message would exceed limit
            if total_length + message_length > MAX_CONTEXT_LENGTH:
                logger.info(f"Context length limit reached. Used {total_length} chars, would be {total_length + message_length}")
                break

            history_text += message_text
            total_length += message_length

        logger.info(f"Built context with {len(chat_history)} messages, total length: {total_length}")

        # Build final query format
        formatted_query = f"""<会話履歴>
{history_text}</会話履歴>
<質問>
ユーザー: {current_query}
</質問>
<出力形式>
適切な改行を設けること
プレーンテキストで出力すること。マークダウンなどで出力しないこと。
</出力形式>"""

        logger.info(f"Formatted query total length: {len(formatted_query)}")
        return formatted_query

    except Exception as e:
        logger.error(f"Error building context: {e}")
        # Return query with empty history on error
        return f"""<会話履歴>
</会話履歴>
<質問>
ユーザー: {current_query}
</質問>"""


def query_knowledge_base(query, folder_path_job_id_pairs):
    """
    Query the Knowledge Base with folder_path and job_id pairs filtering (v3 - hybrid + rerank).
    
    Args:
        query: 質問テキスト
        folder_path_job_id_pairs: [("フォルダ1/フォルダ1-1", "20251105120000"), ("フォルダ2", "20251105130000"), ...]
    
    Returns: (answer, sources)
    """
    logger.info(f"Querying Knowledge Base v3 (hybrid + rerank) with {len(folder_path_job_id_pairs)} folder_path/job_id pairs")
    
    try:
        # --- メタデータフィルタ構築 ---
        # 各folder_pathとjob_idのペアに対してフィルタを作成
        if len(folder_path_job_id_pairs) == 1:
            folder_path, job_id = folder_path_job_id_pairs[0]
            filter_config = {
                'andAll': [
                    {'equals': {'key': 'folder_path', 'value': folder_path}},
                    {'equals': {'key': 'job_id', 'value': job_id}}
                ]
            }
        else:
            # 複数のfolder_path/job_idペアをOR条件で結合
            filter_conditions = []
            for folder_path, job_id in folder_path_job_id_pairs:
                filter_conditions.append({
                    'andAll': [
                        {'equals': {'key': 'folder_path', 'value': folder_path}},
                        {'equals': {'key': 'job_id', 'value': job_id}}
                    ]
                })
            filter_config = {'orAll': filter_conditions}
        
        logger.info(f"Filter configuration v3: {json.dumps(filter_config, ensure_ascii=False)}")

        # --- Retrieval configuration with reranking ---
        retrieval_config = {
            'vectorSearchConfiguration': {
                'numberOfResults': 80,
                'overrideSearchType': 'HYBRID',  # ハイブリッド検索を明示
                'filter': filter_config,
                'rerankingConfiguration': {
                    'type': 'BEDROCK_RERANKING_MODEL',
                    'bedrockRerankingConfiguration': {
                        'numberOfRerankedResults': 20,  # リランキング後の結果数 (正しいパラメータ名)
                        'modelConfiguration': {
                            'modelArn': 'arn:aws:bedrock:us-west-2::foundation-model/cohere.rerank-v3-5:0'
                        }
                    }
                }
            }
        }

        # --- Orchestration configuration ---
        orchestration_config = {
            'queryTransformationConfiguration': {
                'type': 'QUERY_DECOMPOSITION'
            }
        }

        # --- Bedrock 呼び出し設定 ---
        bedrock_client = boto3.client("bedrock-agent-runtime", region_name=BEDROCK_REGION, config=config)

        kb_config = {
            'type': 'KNOWLEDGE_BASE',
            'knowledgeBaseConfiguration': {
                'knowledgeBaseId': KNOWLEDGE_BASE_ID,
                'modelArn': BEDROCK_MODEL_ARN,
                'retrievalConfiguration': retrieval_config,
                'orchestrationConfiguration': orchestration_config
            }
        }
        
        response = bedrock_client.retrieve_and_generate(
            input={'text': query},
            retrieveAndGenerateConfiguration=kb_config
        )

        # --- 結果抽出 ---
        answer = response.get('output', {}).get('text', '')
        return _extract_sources_from_response(response, answer)

    except ClientError as e:
        logger.error(f"Error querying Knowledge Base v3: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error v3: {e}")
        raise



def _extract_sources_from_response(response, answer):
    """
    Extract sources from Bedrock response (共通の処理)
    
    Returns: (answer, sources)
    """
    sources = []
    if 'citations' in response:
        for citation in response['citations']:
            retrieved_refs = citation.get('retrievedReferences', [])
            for ref in retrieved_refs:
                location = ref.get('location', {})
                s3_location = location.get('s3Location', {})
                source_uri = s3_location.get('uri', '')
                
                # Get metadata from Knowledge Base response
                metadata = ref.get('metadata', {})
                
                # Extract FileName and s3Key from metadata
                file_name = None
                file_s3_key = None
                
                # Check if metadata contains our custom attributes
                if 'FileName' in metadata:
                    file_name = metadata.get('FileName')
                if 's3Key' in metadata:
                    file_s3_key = metadata.get('s3Key')
                
                # Fallback: Extract from source_uri if metadata not available
                if not file_name or not file_s3_key:
                    if source_uri:
                        job_id_extracted, extracted_file_name = extract_job_id_and_pdf_from_uri(source_uri)
                        if not file_name:
                            file_name = extracted_file_name
                        if not file_s3_key and job_id_extracted:
                            file_s3_key = f"PDF/{job_id_extracted}/{extracted_file_name}"
                
                # Only add source if we have valid data
                if file_name and file_s3_key:
                    source_entry = {
                        'fileName': file_name,
                        's3Key': file_s3_key
                    }
                    
                    # Avoid duplicates by s3Key
                    if not any(s.get('s3Key') == file_s3_key for s in sources):
                        sources.append(source_entry)
                        logger.info(f"Added source: fileName={file_name}, s3Key={file_s3_key}")
    
    logger.info(f"Query completed: sources={len(sources)}")
    return answer, sources


def get_bedrock_agent_runtime():
    """Lazy-create Bedrock Agent Runtime client"""
    global _bedrock_agent_runtime
    if _bedrock_agent_runtime is None:
        _bedrock_agent_runtime = boto3.client(
            "bedrock-agent-runtime",
            region_name=BEDROCK_REGION,
            config=config
        )
    return _bedrock_agent_runtime


def invoke_agent_with_filter(query, folder_path_job_id_pairs, session_id, agent_type='default'):
    """
    Invoke Bedrock Agent with filter information.
    Agent will call Action Lambda (agent_kb_action.py) to perform filtered KB search.
    
    Args:
        query: User query text (without chat history)
        folder_path_job_id_pairs: List of (folder_path, job_id) tuples
        session_id: Chat session ID (used as Agent session ID)
        agent_type: Agent type ('default', 'verification', 'specification')
    
    Returns:
        (answer, sources)
    """
    logger.info(f"[Agent] Invoking Bedrock Agent (type={agent_type}) with {len(folder_path_job_id_pairs)} folder/job pairs")
    
    # Select Agent ID and Alias ID based on agent_type
    if agent_type == 'verification':
        agent_id = VERIFICATION_AGENT_ID or BEDROCK_AGENT_ID
        agent_alias_id = VERIFICATION_AGENT_ALIAS_ID or BEDROCK_AGENT_ALIAS_ID
        logger.info(f"[Agent] Using Verification Agent: {agent_id}/{agent_alias_id}")
    elif agent_type == 'specification':
        agent_id = SPECIFICATION_AGENT_ID or BEDROCK_AGENT_ID
        agent_alias_id = SPECIFICATION_AGENT_ALIAS_ID or BEDROCK_AGENT_ALIAS_ID
        logger.info(f"[Agent] Using Specification Agent: {agent_id}/{agent_alias_id}")
    else:
        agent_id = BEDROCK_AGENT_ID
        agent_alias_id = BEDROCK_AGENT_ALIAS_ID
        logger.info(f"[Agent] Using Default Agent: {agent_id}/{agent_alias_id}")
    
    try:
        # Prepare filter information for Agent using JSON format to preserve folder_path/job_id pairing
        # This ensures one-to-one correspondence even if folder names contain special characters
        
        # folder_path_job_id_pairsは辞書のリストまたはタプルのリストで渡される可能性があるため両方に対応
        normalized_pairs = []
        for pair in folder_path_job_id_pairs:
            if isinstance(pair, dict):
                # 辞書の場合: そのまま使用
                normalized_pairs.append({"folder_path": pair['folder_path'], "job_id": pair['job_id']})
            else:
                # タプルの場合: 辞書に変換
                fp, jid = pair
                normalized_pairs.append({"folder_path": fp, "job_id": jid})
        
        folder_job_pairs_json = json.dumps(normalized_pairs, ensure_ascii=False)
        
        logger.info(f"[Agent] Filter info (JSON): {folder_job_pairs_json}")
        
        # SessionAttributesでフィルタ情報を渡す(エージェントがこれを参照してAction Lambdaに渡す)
        # JSON形式で渡すことで、フォルダパスとjob_idの一対一対応を保証
        session_attributes = {
            'folder_job_pairs': folder_job_pairs_json  # JSON文字列で構造化データを渡す
        }
        
        logger.info(f"[Agent] Session attributes prepared with {len(folder_path_job_id_pairs)} folder/job pairs")
        
        # Get Bedrock Agent Runtime client
        bedrock_agent = get_bedrock_agent_runtime()
        
        # Invoke Agent with session attributes
        # queryをそのまま渡す(構造化不要 - session_attributesでフィルタ情報を渡す)
        logger.info(f"[Agent] Calling invoke_agent with agentId={agent_id}, sessionId={session_id}, query length={len(query)}")
        response = bedrock_agent.invoke_agent(
            agentId=agent_id,
            agentAliasId=agent_alias_id,
            sessionId=session_id,
            inputText=query,  # ユーザーの質問をそのまま渡す
            sessionState={
                'sessionAttributes': session_attributes
            },
            enableTrace=True  # トレース情報を有効化してAction Lambdaのレスポンスを取得
        )
        
        # Process Agent response (streaming)
        answer = ""
        sources = []
        action_response_body = None
        
        # Agent returns EventStream - need to process all event types
        event_stream = response.get('completion', [])
        
        for event in event_stream:
            event_keys = list(event.keys())
            logger.info(f"[Agent] Event type: {event_keys}")
            
            # チャンク(回答テキスト)
            if 'chunk' in event:
                chunk = event['chunk']
                if 'bytes' in chunk:
                    chunk_text = chunk['bytes'].decode('utf-8')
                    answer += chunk_text
                    logger.info(f"[Agent] Received chunk: {len(chunk_text)} bytes")
            
            # トレース情報(Action Lambdaのレスポンスを含む)
            if 'trace' in event:
                trace = event['trace'].get('trace', {})
                
                # トレース全体をログ出力(デバッグ用)
                logger.info(f"[Agent] Full trace keys: {list(trace.keys())}")
                logger.info(f"[Agent] Full trace content: {json.dumps(trace, ensure_ascii=False, default=str)[:2000]}")
                
                # orchestrationTrace内のinvocationInputとmodelInvocationOutputを確認
                if 'orchestrationTrace' in trace:
                    orch_trace = trace['orchestrationTrace']
                    logger.info(f"[Agent] orchestrationTrace keys: {list(orch_trace.keys())}")
                    
                    # モデルの推論入力を確認
                    if 'modelInvocationInput' in orch_trace:
                        model_input = orch_trace['modelInvocationInput']
                        logger.info(f"[Agent] Model invocation input: {json.dumps(model_input, ensure_ascii=False, default=str)[:1000]}")
                    
                    # モデルの推論出力を確認
                    if 'rationale' in orch_trace:
                        rationale = orch_trace['rationale']
                        logger.info(f"[Agent] Rationale: {json.dumps(rationale, ensure_ascii=False, default=str)[:1000]}")
                    
                    # Action Groupの呼び出し結果を取得
                    if 'observation' in orch_trace:
                        observation = orch_trace['observation']
                        logger.info(f"[Agent] Observation keys: {list(observation.keys())}")
                        
                        # actionGroupInvocationOutputからレスポンスボディを取得
                        if 'actionGroupInvocationOutput' in observation:
                            action_output = observation['actionGroupInvocationOutput']
                            text_body = action_output.get('text', '')
                            
                            if text_body:
                                logger.info(f"[Agent] Action Lambda response body: {text_body[:500]}...")
                                
                                # Action LambdaがJSON形式で返したレスポンスをパース
                                try:
                                    action_response_body = json.loads(text_body)
                                    logger.info(f"[Agent] Successfully parsed Action Lambda JSON response")
                                except json.JSONDecodeError as jde:
                                    logger.warning(f"[Agent] Failed to parse Action Lambda response as JSON: {jde}")
                        
                        # knowledgeBaseLookupOutputを確認(エージェントが直接KBを呼んでいる場合)
                        if 'knowledgeBaseLookupOutput' in observation:
                            kb_output = observation['knowledgeBaseLookupOutput']
                            logger.info(f"[Agent] Agent called KB directly (not using Action Group): {json.dumps(kb_output, ensure_ascii=False, default=str)[:500]}")
        
        logger.info(f"[Agent] Complete answer received: {len(answer)} characters")
        
        # Action Lambdaのレスポンスからsourcesを抽出
        if action_response_body:
            if 'sources' in action_response_body:
                sources = action_response_body['sources']
                logger.info(f"[Agent] Extracted {len(sources)} sources from Action Lambda response")
            
            # answerもAction Lambdaから取得する場合(現在のAgentは要約した回答を返すので通常は使わない)
            # if 'answer' in action_response_body and not answer:
            #     answer = action_response_body['answer']
        
        # フォールバック: Agentの回答自体がJSON形式の場合(旧実装との互換性)
        if not sources:
            try:
                if answer.strip().startswith('{') and answer.strip().endswith('}'):
                    parsed = json.loads(answer)
                    if 'answer' in parsed and 'sources' in parsed:
                        sources = parsed.get('sources', [])
                        answer = parsed.get('answer', '')
                        logger.info(f"[Agent] Fallback: Parsed {len(sources)} sources from answer JSON")
            except json.JSONDecodeError:
                logger.info("[Agent] Answer is plain text (expected behavior)")
        
        logger.info(f"[Agent] Query completed: answer_length={len(answer)}, sources={len(sources)}")
        return answer, sources
        
    except ClientError as e:
        logger.error(f"[Agent] Error invoking agent: {e}")
        raise
    except Exception as e:
        logger.error(f"[Agent] Unexpected error: {e}")
        raise


def save_chat_message(job_id, role, content, sources=None, chat_session_id=None, selected_folder_paths=None, selected_job_id=None):
    """Save chat message to DynamoDB history. Returns message_id."""
    # Generate message_id: timestamp + UUID
    timestamp = datetime.now(JST).isoformat()
    message_id = f"{timestamp}#{str(uuid.uuid4())}"

    item = {
        'job_id': job_id,
        'message_id': message_id,
        'role': role,  # 'user' or 'assistant'
        'content': content,
        'timestamp': timestamp,
        'ttl': int((datetime.now(JST) + timedelta(days=30)).timestamp())  # 30-day TTL
    }

    # Add chat_session_id if provided (required for new functionality)
    if chat_session_id:
        item['chat_session_id'] = chat_session_id

    # Save sources only for assistant responses
    if sources and role == 'assistant':
        item['sources'] = sources
    
    # Save folder selection info only for user messages (session metadata)
    if role == 'user' and selected_folder_paths:
        item['selected_folder_paths'] = selected_folder_paths
        logger.info(f"Saving selected_folder_paths: {selected_folder_paths}")
    
    if role == 'user' and selected_job_id:
        item['selected_job_id'] = selected_job_id
        logger.info(f"Saving selected_job_id: {selected_job_id}")

    # Lazy init chat_history_table
    global _dynamodb, _chat_history_table
    if _dynamodb is None:
        _dynamodb = boto3.resource('dynamodb', region_name=DYNAMODB_REGION)
    if _chat_history_table is None:
        if not DYNAMODB_CHAT_HISTORY_TABLE:
            logger.warning('DYNAMODB_CHAT_HISTORY_TABLE not configured; skipping history save')
            return None
        _chat_history_table = _dynamodb.Table(DYNAMODB_CHAT_HISTORY_TABLE)

    try:
        _chat_history_table.put_item(Item=item)
        logger.info(f"Saved chat message for job {job_id}, role: {role}, message_id: {message_id}, chat_session_id: {chat_session_id}")
        return message_id  # Return the message_id
    except ClientError as e:
        logger.error(f"Error saving chat message to DynamoDB: {e}")
        # Don't fail the entire request if history save fails
        return None


def validate_job_exists(job_id):
    """
    Validate that the job exists in DynamoDB.
    Returns job data (dict) if exists, None otherwise.
    """
    try:
        global _dynamodb, _jobs_table
        if _dynamodb is None:
            _dynamodb = boto3.resource('dynamodb', region_name=DYNAMODB_REGION)
        if _jobs_table is None:
            if not DYNAMODB_TABLE:
                logger.error('DYNAMODB_TABLE not configured')
                return None
            _jobs_table = _dynamodb.Table(DYNAMODB_TABLE)

        # Use Key condition expression for correct DynamoDB SDK usage
        response = _jobs_table.query(
            KeyConditionExpression=Key('job_id').eq(job_id),
            Limit=1
        )

        if response.get('Items'):
            job_data = response['Items'][0]
            logger.info(f"Job {job_id} validated with folder_path: {job_data.get('folder_path', 'N/A')}")
            return job_data
        else:
            logger.warning(f"Job {job_id} not found")
            return None
            return False
            
    except ClientError as e:
        logger.error(f"Error validating job: {e}")
        return False



def lambda_handler(event, context):
    """
    POST /api/knowledge-query (legacy sync mode)
    OR
    Async invocation from StartQueryLambda (async mode)
    
    Handles ONLY knowledge base queries. History operations are handled by separate history_manager Lambda.
    
    Request body (sync mode):
    {
        "jobId": "20251027120000",           (required)
        "chat_session_id": "xxxxxxxx-xxxx", (required)
        "query": "質問テキスト",               (required)
    }
    
    Request body (async mode):
    {
        "query_id": "abc-123-def",          (async mode signal)
        "jobId": "20251027120000",
        "chat_session_id": "xxxxxxxx-xxxx",
        "query": "質問テキスト",
        "folder_paths": [...],
        "use_agent": true
    }
    
    Response (sync):
    {
        "statusCode": 200,
        "body": {
            "answer": "回答テキスト",
            "sources": [...]
        }
    }
    
    Response (async):
    {
        "statusCode": 200
    }
    """
    
    logger.info(f"Event: {json.dumps(event)}")
    
    # 非同期モード検出
    query_id = event.get('query_id')
    
    if query_id:
        logger.info(f"Async mode detected: query_id={query_id}")
        return handle_async_query(event, query_id)
    else:
        logger.info("Sync mode (legacy)")
        return handle_sync_query(event)


def handle_sync_query(event):
    """Handle synchronous query (legacy mode)"""
    
    try:
        # Parse request body
        if isinstance(event.get('body'), str):
            body = json.loads(event['body'])
        else:
            body = event.get('body', {})

        job_id = (body.get('jobId', '') or '').strip()
        folder_path = (body.get('folder_path', '') or '').strip()  # 単一フォルダパス（後方互換性）
        folder_paths = body.get('folder_paths', [])  # 複数フォルダパス対応
        folder_default_job_ids = body.get('folder_default_job_ids', {})  # フォルダごとのデフォルトJOB_ID
        chat_session_id = (body.get('chat_session_id', '') or '').strip()
        query = (body.get('query', '') or '').strip()
        use_agent = body.get('use_agent', False)  # Agent利用フラグ（デフォルト: False）
        agent_type = body.get('agent_type', 'default')  # Agentタイプ: 'default', 'verification', 'specification'
        
        # folder_path（単一）が指定されている場合、folder_paths配列に変換
        if folder_path and not folder_paths:
            folder_paths = [folder_path]
        
        logger.info(f"Query request - job_id: {job_id}, folder_paths: {folder_paths}, folder_default_job_ids: {folder_default_job_ids}, use_agent: {use_agent}, agent_type: {agent_type}")
        
        # ジョブIDがない場合は環境変数から取得（レガシー対応）
        if not job_id and not folder_paths and DEFAULT_JOB_ID:
            job_id = DEFAULT_JOB_ID
            logger.info(f"Using default job_id from environment: {job_id}")
        
        # v2: folder_paths が指定されている場合、各フォルダの job_ids を取得
        # （folder_configテーブルのルックアップは省略 - 複数フォルダの場合は全job_idを取得）
        
        # Validate environment configuration (required resources)
        missing_env = []
        invalid_env = []
        
        for name, val in [('DYNAMODB_TABLE', DYNAMODB_TABLE), ('DYNAMODB_CHAT_HISTORY_TABLE', DYNAMODB_CHAT_HISTORY_TABLE), ('KNOWLEDGE_BASE_ID', KNOWLEDGE_BASE_ID), ('BEDROCK_MODEL_ARN', BEDROCK_MODEL_ARN)]:
            if not val:
                missing_env.append(name)
        
        # Validate BEDROCK_MODEL_ARN format (should be an ARN like arn:aws:bedrock:...)
        if BEDROCK_MODEL_ARN and not BEDROCK_MODEL_ARN.startswith('arn:aws:bedrock'):
            invalid_env.append(f"BEDROCK_MODEL_ARN has invalid format: {BEDROCK_MODEL_ARN}")
        
        if missing_env or invalid_env:
            error_msgs = missing_env + invalid_env
            logger.error(f"Environment configuration issues: {error_msgs}")
            return {
                'statusCode': 500,
                'headers': {
                    'Access-Control-Allow-Origin': '*',
                    'Content-Type': 'application/json'
                },
                'body': json.dumps({'error': f'Configuration error: {", ".join(error_msgs)}'})
            }

        # Validate inputs - job_id OR folder_paths が必須
        if not job_id and not folder_paths:
            logger.error("Missing jobId and folder_paths")
            return {
                'statusCode': 400,
                'headers': {
                    'Access-Control-Allow-Origin': '*',
                    'Content-Type': 'application/json'
                },
                'body': json.dumps({
                    'error': 'ジョブIDまたはフォルダパスが指定されていません'
                })
            }
        
        
        # Validate chat_session_id
        if not chat_session_id:
            logger.error("Missing chat_session_id")
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
        
        # Validate required parameters
        if not query:
            logger.error("Missing query")
            return {
                'statusCode': 400,
                'headers': {
                    'Access-Control-Allow-Origin': '*',
                    'Content-Type': 'application/json'
                },
                'body': json.dumps({
                    'error': '質問が指定されていません'
                })
            }
        
        if not folder_paths:
            logger.error("Missing folder_paths")
            return {
                'statusCode': 400,
                'headers': {
                    'Access-Control-Allow-Origin': '*',
                    'Content-Type': 'application/json'
                },
                'body': json.dumps({
                    'error': 'フォルダパスが指定されていません'
                })
            }
        
        # folder_paths から folder_path/job_id ペアを収集
        folder_path_job_id_pairs = []
        logger.info(f"Processing folder_paths: {folder_paths}")
        logger.info(f"folder_default_job_ids: {folder_default_job_ids}")
        
        for fp in folder_paths:
            # デフォルトJOB_IDの確認（必須）
            if fp not in folder_default_job_ids or not folder_default_job_ids[fp]:
                logger.error(f"No default job_id specified for folder: {fp}")
                return {
                    'statusCode': 400,
                    'headers': {
                        'Access-Control-Allow-Origin': '*',
                        'Content-Type': 'application/json'
                    },
                    'body': json.dumps({
                        'error': f'フォルダ「{fp}」のデフォルトJOB_IDが指定されていません。フォルダを選択してから質問してください。'
                    }, ensure_ascii=False)
                }
            
            default_job_id = folder_default_job_ids[fp]
            logger.info(f"Using default job_id {default_job_id} for folder {fp}")
            folder_path_job_id_pairs.append((fp, default_job_id))
        
        logger.info(f"Collected {len(folder_path_job_id_pairs)} folder_path/job_id pairs from {len(folder_paths)} folders")
        
        if not folder_path_job_id_pairs:
            logger.error(f"No jobs found for folder_paths: {folder_paths}")
            return {
                'statusCode': 400,
                'headers': {
                    'Access-Control-Allow-Origin': '*',
                    'Content-Type': 'application/json'
                },
                'body': json.dumps({
                    'error': '指定されたフォルダパスにジョブが見つかりません'
                })
            }
        
        # 最初のペアを履歴保存用に使用
        folder_path, job_id = folder_path_job_id_pairs[0]
        logger.info(f"Using folder_path: {folder_path}, job_id: {job_id} for history, querying {len(folder_path_job_id_pairs)} pairs")
        
        logger.info(f"Processing query for chat_session_id: {chat_session_id}, job_id: {job_id}, folder_path: {folder_path}")
        logger.info(f"MAX_CONTEXT_LENGTH: {MAX_CONTEXT_LENGTH}")
        
        # リクエストからユーザーが選択したJOB_IDを取得（オプション）
        user_selected_job_id = body.get('selected_job_id')
        
        # チャット履歴を確認して、このセッションの最初のメッセージかどうか判定
        chat_history = get_chat_history(job_id, chat_session_id)
        is_first_message = len(chat_history) == 0
        
        # Save user query to history
        # 最初のメッセージの場合のみ、フォルダ選択情報を保存
        if is_first_message:
            logger.info(f"First message in session - saving folder selection info")
            save_chat_message(
                job_id, 
                'user', 
                query, 
                chat_session_id=chat_session_id,
                selected_folder_paths=folder_paths,
                selected_job_id=user_selected_job_id
            )
        else:
            logger.info(f"Not first message - saving without folder selection info")
            save_chat_message(job_id, 'user', query, chat_session_id=chat_session_id)
        
        # Retrieve chat history for this session (再取得して最新の状態を取得)
        chat_history = get_chat_history(job_id, chat_session_id)
        logger.info(f"Retrieved {len(chat_history)} messages from chat history")
        
        # Agent使用時と従来のKB直接呼び出しで処理を分岐
        if use_agent:
            # === Agent経由での問い合わせ ===
            logger.info("[Agent Mode] Using Bedrock Agent for query")
            
            # Agent呼び出し時は会話履歴を含めず、ユーザーコメントのみ送信
            # Agent自身がsessionIdで会話履歴を管理
            answer, sources = invoke_agent_with_filter(query, folder_path_job_id_pairs, chat_session_id)
            
        else:
            # === 従来のKnowledgebase直接問い合わせ ===
            logger.info("[KB Direct Mode] Using Knowledge Base direct query")
            
            # Build formatted query with history
            formatted_query = build_context_with_history(chat_history, query)
            logger.info(f"Built formatted query with {len(formatted_query)} total characters")
            logger.info(f"Context preview (first 300 chars): {formatted_query[:300]}")
            
            # Query knowledge base with folder_path/job_id pairs
            logger.info(f"Querying knowledge base with {len(folder_path_job_id_pairs)} folder_path/job_id pairs")
            answer, sources = query_knowledge_base(formatted_query, folder_path_job_id_pairs)
        
        # Generate presigned URLs for sources before returning to client
        for source in sources:
            if 's3Key' in source:
                presigned_url = generate_presigned_url(S3_BUCKET, source['s3Key'], expiration=604800)  # 7 days
                if presigned_url:
                    source['presignedUrl'] = presigned_url
        
        # Save assistant response to history (with sources, only for assistant)
        # and get the message_id
        message_id = save_chat_message(job_id, 'assistant', answer, sources=sources, chat_session_id=chat_session_id)
        
        logger.info(f"Query completed successfully. Answer length: {len(answer)}, sources: {len(sources)}, message_id: {message_id}")
        
        response_body = {
            'answer': answer,
            'sources': sources
        }
        
        # Include message_id if available
        if message_id:
            response_body['message_id'] = message_id
        
        return {
            'statusCode': 200,
            'headers': {
                'Access-Control-Allow-Origin': '*',
                'Content-Type': 'application/json'
            },
            'body': json.dumps(response_body, ensure_ascii=False)
        }

        
    except Exception as e:
        logger.error(f"Error processing request: {e}", exc_info=True)

        # Check if it's a known error message (from query_knowledge_base)
        error_message = str(e)
        
        # Log the full exception type for debugging
        exception_type = type(e).__name__
        logger.error(f"Exception type: {exception_type}, Message: {error_message}")
        
        if any(x in error_message for x in ['準備中', '見つかりません', 'ナレッジベースエラー']):
            return {
                'statusCode': 503,
                'headers': {
                    'Access-Control-Allow-Origin': '*',
                    'Content-Type': 'application/json'
                },
                'body': json.dumps({
                    'error': error_message
                }, ensure_ascii=False)
            }

        # Generic error - include exception type in response for debugging
        return {
            'statusCode': 500,
            'headers': {
                'Access-Control-Allow-Origin': '*',
                'Content-Type': 'application/json'
            },
            'body': json.dumps({
                'error': 'エラーが発生しました。管理者に連絡してください',
                'details': error_message[:200]  # Include first 200 chars of error for debugging
            }, ensure_ascii=False)
        }


def handle_async_query(event, query_id):
    """
    Handle asynchronous query (invoked from StartQueryLambda)
    
    Updates query status in DynamoDB with results or error.
    Does not return response to client (fire and forget).
    """
    dynamodb = boto3.resource('dynamodb', region_name=DYNAMODB_REGION)
    query_status_table = dynamodb.Table(QUERY_STATUS_TABLE)
    
    try:
        # Extract parameters
        job_id = event.get('jobId', '').strip()
        chat_session_id = event.get('chat_session_id', '').strip()
        query = event.get('query', '').strip()
        folder_paths = event.get('folder_paths', [])
        folder_default_job_ids = event.get('folder_default_job_ids', {})  # フォルダごとのデフォルトJOB_ID
        use_agent = event.get('use_agent', True)
        agent_type = event.get('agent_type', 'default')  # Agentタイプ
        
        logger.info(f"Processing async query: query_id={query_id}, use_agent={use_agent}, agent_type={agent_type}, folder_paths={folder_paths}")
        
        # Determine folder_path_job_id_pairs
        if folder_paths:
            # 複数フォルダ指定: 各フォルダのデフォルトjob_idを使用
            folder_path_job_id_pairs = []
            for fp in folder_paths:
                # フロントエンドから渡されたデフォルトjob_idを使用
                if fp in folder_default_job_ids and folder_default_job_ids[fp]:
                    default_job_id = folder_default_job_ids[fp]
                    folder_path_job_id_pairs.append({'folder_path': fp, 'job_id': default_job_id})
                    logger.info(f"Found {1} unique job_ids for folder_path: {fp}")
                else:
                    logger.warning(f"No default job_id found for folder_path: {fp}")
            
            if not folder_path_job_id_pairs:
                raise ValueError("No valid default job_ids found for the specified folders")
        elif job_id:
            # 単一job_id指定（レガシー）
            folder_path_job_id_pairs = [{'job_id': job_id}]
        else:
            raise ValueError("Either folder_paths or jobId must be specified")
        
        if not folder_path_job_id_pairs:
            raise ValueError("No valid job_ids found for the specified folders")
        
        logger.info(f"folder_path_job_id_pairs: {folder_path_job_id_pairs}")
        
        # Execute query based on mode
        if use_agent:
            logger.info("Using Bedrock Agent mode")
            answer, sources = invoke_agent_with_filter(query, folder_path_job_id_pairs, chat_session_id, agent_type)
        else:
            logger.info("Using Knowledge Base direct mode")
            answer, sources = query_knowledge_base(query, folder_path_job_id_pairs)
        
        # チャット履歴に保存 (オプション) - Update前に実行してmessage_idを取得
        # folder_pathsモードの場合、job_idは空になるので、folder_path_job_id_pairsから取得
        effective_job_id = job_id
        if not effective_job_id and folder_path_job_id_pairs:
            # 最初のペアからjob_idを取得（履歴保存用）
            first_pair = folder_path_job_id_pairs[0]
            effective_job_id = first_pair.get('job_id', '') if isinstance(first_pair, dict) else first_pair[1]
            logger.info(f"Using job_id from folder_path_job_id_pairs for history: {effective_job_id}")
        
        # job_idがない場合はchat_session_idをjob_idとして使用（フィードバック機能のため）
        if not effective_job_id and chat_session_id:
            effective_job_id = f"session-{chat_session_id}"
            logger.info(f"Using chat_session_id as job_id for history: {effective_job_id}")
        
        assistant_message_id = None
        if chat_session_id and effective_job_id:
            try:
                # Save user message
                save_chat_message(
                    job_id=effective_job_id,
                    role='user',
                    content=query,
                    chat_session_id=chat_session_id,
                    selected_folder_paths=folder_paths if folder_paths else None
                )
                
                # Save assistant message and get message_id
                assistant_message_id = save_chat_message(
                    job_id=effective_job_id,
                    role='assistant',
                    content=answer,
                    sources=sources,
                    chat_session_id=chat_session_id,
                    selected_folder_paths=folder_paths if folder_paths else None
                )
                
                logger.info(f"Chat history saved for query_id={query_id}, message_id={assistant_message_id}")
            except Exception as e:
                logger.warning(f"Failed to save chat history: {e}")
        
        # Update status to completed in DynamoDB (include message_id if available)
        update_expression = 'SET #status = :status, answer = :answer, sources = :sources, updated_at = :updated_at'
        expression_values = {
            ':status': 'completed',
            ':answer': answer,
            ':sources': sources,
            ':updated_at': datetime.now().isoformat()
        }
        
        if assistant_message_id:
            update_expression += ', message_id = :message_id'
            expression_values[':message_id'] = assistant_message_id
        
        query_status_table.update_item(
            Key={'query_id': query_id},
            UpdateExpression=update_expression,
            ExpressionAttributeNames={
                '#status': 'status'
            },
            ExpressionAttributeValues=expression_values
        )
        
        logger.info(f"Successfully completed async query: query_id={query_id}, message_id={assistant_message_id}")
        
        return {'statusCode': 200}
        
    except Exception as e:
        logger.error(f"Error in async query processing: {e}", exc_info=True)
        
        # Update status to failed in DynamoDB
        try:
            query_status_table.update_item(
                Key={'query_id': query_id},
                UpdateExpression='SET #status = :status, #error = :error, updated_at = :updated_at',
                ExpressionAttributeNames={
                    '#status': 'status',
                    '#error': 'error'  # 'error' is a reserved keyword
                },
                ExpressionAttributeValues={
                    ':status': 'failed',
                    ':error': str(e),
                    ':updated_at': datetime.now().isoformat()
                }
            )
        except Exception as update_error:
            logger.error(f"Failed to update error status: {update_error}", exc_info=True)
        
        # Re-raise for Lambda retry mechanism
        raise
