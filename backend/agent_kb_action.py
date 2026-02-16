"""
PDF OCR System - Bedrock Agent Action Lambda

This Lambda function is called by Bedrock Agent as an Action Group.
It performs filtered Knowledge Base queries using folder_path and job_id filters.

Agent Action Group Name: KnowledgeBaseSearch
Function Name: search_knowledge_base

Parameters:
- query: The search query text
- folder_paths: Comma-separated folder paths (e.g., "フォルダ1/フォルダ1-1,フォルダ2")
- job_ids: Comma-separated job IDs (e.g., "20251105120000,20251105130000")
"""

import json
import boto3
import os
import logging
from botocore.exceptions import ClientError
from botocore.config import Config

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ===== 環境変数 =====
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-west-2")
KNOWLEDGE_BASE_ID = os.environ.get("KNOWLEDGE_BASE_ID")
BEDROCK_MODEL_ARN = os.environ.get("BEDROCK_MODEL_ARN")
S3_BUCKET = os.environ.get("S3_BUCKET", "doctoknow-seigi25-data")

config = Config(
    connect_timeout=int(os.environ.get("HTTP_CONNECT_TIMEOUT", "10")),
    read_timeout=int(os.environ.get("HTTP_READ_TIMEOUT", "60")),
    retries={'max_attempts': int(os.environ.get("HTTP_RETRIES", "3"))}
)

# Lazy-create Bedrock client
_bedrock_agent_runtime = None


def get_bedrock_client():
    """Lazy-create Bedrock Agent Runtime client"""
    global _bedrock_agent_runtime
    if _bedrock_agent_runtime is None:
        _bedrock_agent_runtime = boto3.client(
            "bedrock-agent-runtime", 
            region_name=BEDROCK_REGION, 
            config=config
        )
    return _bedrock_agent_runtime


def generate_presigned_url(s3_key, expiration=3600):
    """
    Generate a presigned URL for S3 object
    
    Args:
        s3_key: S3 key (e.g., "PDF/生技資料/生技25/MCステータライン/filename.pdf")
        expiration: URL expiration time in seconds (default: 1 hour)
    
    Returns:
        Presigned URL string or None if error
    """
    try:
        s3_client = boto3.client('s3', region_name=BEDROCK_REGION)
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': S3_BUCKET,
                'Key': s3_key
            },
            ExpiresIn=expiration
        )
        logger.info(f"[Agent Action] Generated presigned URL for: {s3_key}")
        return presigned_url
    except ClientError as e:
        logger.error(f"[Agent Action] Error generating presigned URL for {s3_key}: {e}")
        return None


def extract_job_id_and_pdf_from_uri(source_uri):
    """
    Extract job_id and PDF filename from source URI.
    URI format: s3://doctoknow-seigi25-data/Knowledge/{job_id}/filename.txt
    Returns: (job_id, pdf_filename.pdf)
    """
    try:
        prefix = f"s3://{S3_BUCKET}/Knowledge/"
        
        if source_uri.startswith(prefix):
            path = source_uri.replace(prefix, "")
        else:
            path = source_uri.split("/Knowledge/", 1)[-1]
        
        parts = path.split("/", 1)
        
        if len(parts) == 2:
            job_id = parts[0]
            txt_filename = parts[1].split("/")[-1]
            pdf_filename = txt_filename.replace(".txt", ".pdf")
            return job_id, pdf_filename
        
        logger.warning(f"Could not extract job_id and filename from URI: {source_uri}")
        return None, None
    except Exception as e:
        logger.error(f"Error extracting job_id from URI: {e}")
        return None, None


def query_knowledge_base_with_filter(query, folder_path_job_id_pairs):
    """
    Query Knowledge Base with folder_path and job_id filtering.
    
    Args:
        query: Search query text
        folder_path_job_id_pairs: List of tuples [("folder1", "job1"), ("folder2", "job2")]
    
    Returns:
        (answer, sources)
    """
    logger.info(f"[Agent Action] Querying KB with {len(folder_path_job_id_pairs)} folder/job pairs")
    
    try:
        # Build metadata filter
        if len(folder_path_job_id_pairs) == 1:
            folder_path, job_id = folder_path_job_id_pairs[0]
            filter_config = {
                'andAll': [
                    {'equals': {'key': 'folder_path', 'value': folder_path}},
                    {'equals': {'key': 'job_id', 'value': job_id}}
                ]
            }
        else:
            filter_conditions = []
            for folder_path, job_id in folder_path_job_id_pairs:
                filter_conditions.append({
                    'andAll': [
                        {'equals': {'key': 'folder_path', 'value': folder_path}},
                        {'equals': {'key': 'job_id', 'value': job_id}}
                    ]
                })
            filter_config = {'orAll': filter_conditions}
        
        logger.info(f"[Agent Action] Filter config: {json.dumps(filter_config, ensure_ascii=False)}")

        # Retrieval configuration with reranking
        retrieval_config = {
            'vectorSearchConfiguration': {
                'numberOfResults': 80,
                'overrideSearchType': 'HYBRID',
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

        # Orchestration configuration
        orchestration_config = {
            'queryTransformationConfiguration': {
                'type': 'QUERY_DECOMPOSITION'
            }
        }

        # Call Bedrock KB
        bedrock_client = get_bedrock_client()

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

        # Extract answer and sources
        answer = response.get('output', {}).get('text', '')
        sources = []
        
        if 'citations' in response:
            for citation in response['citations']:
                retrieved_refs = citation.get('retrievedReferences', [])
                for ref in retrieved_refs:
                    location = ref.get('location', {})
                    s3_location = location.get('s3Location', {})
                    source_uri = s3_location.get('uri', '')
                    
                    metadata = ref.get('metadata', {})
                    
                    file_name = metadata.get('FileName')
                    file_s3_key = metadata.get('s3Key')
                    
                    # Fallback extraction
                    if not file_name or not file_s3_key:
                        if source_uri:
                            job_id_extracted, extracted_file_name = extract_job_id_and_pdf_from_uri(source_uri)
                            if not file_name:
                                file_name = extracted_file_name
                            if not file_s3_key and job_id_extracted:
                                file_s3_key = f"PDF/{job_id_extracted}/{extracted_file_name}"
                    
                    if file_name and file_s3_key:
                        # Generate presigned URL for S3 object
                        presigned_url = generate_presigned_url(file_s3_key)
                        
                        source_entry = {
                            'fileName': file_name,
                            's3Key': file_s3_key
                        }
                        
                        # Add presigned URL if successfully generated
                        if presigned_url:
                            source_entry['presignedUrl'] = presigned_url
                        
                        # Avoid duplicates
                        if not any(s.get('s3Key') == file_s3_key for s in sources):
                            sources.append(source_entry)
                            logger.info(f"[Agent Action] Added source: {file_name}")
        
        logger.info(f"[Agent Action] Query completed: answer_length={len(answer)}, sources={len(sources)}")
        return answer, sources

    except ClientError as e:
        logger.error(f"[Agent Action] Error querying KB: {e}")
        raise
    except Exception as e:
        logger.error(f"[Agent Action] Unexpected error: {e}")
        raise


def lambda_handler(event, context):
    """
    Bedrock Agent Action Lambda Handler
    
    Event structure (from Bedrock Agent):
    {
        "messageVersion": "1.0",
        "agent": {...},
        "inputText": "user query",
        "sessionId": "session-id",
        "actionGroup": "KnowledgeBaseSearch",
        "function": "search_knowledge_base",
        "parameters": [
            {"name": "query", "type": "string", "value": "..."},
            {"name": "folder_job_pairs", "type": "string", "value": "[{\"folder_path\":\"...\",\"job_id\":\"...\"}]"}
        ]
    }
    """
    
    logger.info(f"[Agent Action] Event: {json.dumps(event)}")
    
    try:
        # Extract parameters from Agent event
        action_group = event.get('actionGroup', '')
        function = event.get('function', '')
        parameters = event.get('parameters', [])
        
        # Parse parameters
        param_dict = {}
        for param in parameters:
            param_name = param.get('name', '')
            param_value = param.get('value', '')
            param_dict[param_name] = param_value
        
        query = param_dict.get('query', '').strip()
        folder_job_pairs_str = param_dict.get('folder_job_pairs', '').strip()
        
        # If folder_job_pairs is a template variable like {{session.xxx}}, get from sessionAttributes
        if folder_job_pairs_str.startswith('{{session.') and folder_job_pairs_str.endswith('}}'):
            logger.info(f"[Agent Action] Detected template variable: {folder_job_pairs_str}, retrieving from sessionAttributes")
            session_attributes = event.get('sessionAttributes', {})
            folder_job_pairs_str = session_attributes.get('folder_job_pairs', '').strip()
            logger.info(f"[Agent Action] Retrieved from sessionAttributes: {folder_job_pairs_str[:200]}...")
        
        logger.info(f"[Agent Action] Params: query={query[:50]}..., folder_job_pairs={folder_job_pairs_str[:200]}...")
        
        # Validate parameters
        if not query:
            raise ValueError("Query parameter is missing")
        if not folder_job_pairs_str:
            raise ValueError("Folder job pairs parameter is missing")
        
        # Parse JSON format folder_job_pairs
        try:
            folder_job_pairs_list = json.loads(folder_job_pairs_str)
            
            # Validate structure
            if not isinstance(folder_job_pairs_list, list):
                raise ValueError("folder_job_pairs must be a JSON array")
            
            # Extract folder_path and job_id from each pair
            folder_path_job_id_pairs = []
            for pair in folder_job_pairs_list:
                if not isinstance(pair, dict):
                    raise ValueError("Each pair must be a JSON object")
                
                folder_path = pair.get('folder_path', '').strip()
                job_id = pair.get('job_id', '').strip()
                
                if not folder_path or not job_id:
                    raise ValueError("Each pair must have folder_path and job_id")
                
                folder_path_job_id_pairs.append((folder_path, job_id))
            
            logger.info(f"[Agent Action] Successfully parsed {len(folder_path_job_id_pairs)} folder/job pairs")
            
        except json.JSONDecodeError as e:
            logger.error(f"[Agent Action] Failed to parse folder_job_pairs JSON: {e}")
            raise ValueError(f"Invalid JSON format for folder_job_pairs: {e}")
        
        logger.info(f"[Agent Action] Processing {len(folder_path_job_id_pairs)} folder/job pairs")
        
        # Query Knowledge Base with filter
        answer, sources = query_knowledge_base_with_filter(query, folder_path_job_id_pairs)
        
        # Format response for Agent
        response_body = {
            'answer': answer,
            'sources': sources
        }
        
        # Agent Action response format
        agent_response = {
            'messageVersion': '1.0',
            'response': {
                'actionGroup': action_group,
                'function': function,
                'functionResponse': {
                    'responseBody': {
                        'TEXT': {
                            'body': json.dumps(response_body, ensure_ascii=False)
                        }
                    }
                }
            }
        }
        
        logger.info(f"[Agent Action] Returning response with {len(sources)} sources")
        return agent_response
        
    except Exception as e:
        logger.error(f"[Agent Action] Error: {e}", exc_info=True)
        
        # Return error response to Agent
        error_response = {
            'messageVersion': '1.0',
            'response': {
                'actionGroup': event.get('actionGroup', 'unknown'),
                'function': event.get('function', 'unknown'),
                'functionResponse': {
                    'responseBody': {
                        'TEXT': {
                            'body': json.dumps({
                                'error': str(e),
                                'answer': 'エラーが発生しました。管理者に連絡してください。',
                                'sources': []
                            }, ensure_ascii=False)
                        }
                    }
                }
            }
        }
        
        return error_response
