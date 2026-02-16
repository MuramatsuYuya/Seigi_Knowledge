import json
import boto3
import base64
import os
import logging
from datetime import datetime, timezone, timedelta
from botocore.exceptions import ClientError
from botocore.config import Config

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ===== 固定設宁E=====
BEDROCK_REGION = "us-west-2"
S3_REGION = "us-west-2"
DYNAMO_REGION = "us-west-2"
BEDROCK_KB_REGION = "us-west-2"
config = Config(
    connect_timeout=10,
    read_timeout=900,
    retries={'max_attempts': 3}
)

# JST timezone (UTC+9)
JST = timezone(timedelta(hours=9))

s3_client = boto3.client("s3", region_name=S3_REGION)
dynamodb = boto3.resource("dynamodb", region_name=DYNAMO_REGION)
bedrock_client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION, config=config)
bedrock_kb_client = boto3.client("bedrock-agent", region_name=BEDROCK_KB_REGION, config=config)

# ===== 環墁E��数 =====
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "global.anthropic.claude-haiku-4-5-20251001-v1:0")
BEDROCK_MAX_TOKENS = int(os.environ.get("BEDROCK_MAX_TOKENS", "2000"))
DYNAMODB_TABLE = os.environ["DYNAMODB_TABLE"]
S3_BUCKET = os.environ["S3_BUCKET"]
KNOWLEDGE_BASE_ID = os.environ.get("KNOWLEDGE_BASE_ID", "QBRNP5FY8E")
DATA_SOURCE_ID = os.environ.get("DATA_SOURCE_ID", "DE8SIWPN5R")

jobs_table = dynamodb.Table(DYNAMODB_TABLE)


# ===== S3 関連 =====
def get_prompt_from_s3(job_id, prompt_type):
    """
    Fetch prompt from S3
    
    Args:
        job_id: Job ID
        prompt_type: 'transcript' or 'knowledge'
    
    Returns:
        Prompt text or None if not found
    """
    try:
        if prompt_type == 'transcript':
            prompt_key = f"Prompts/{job_id}/transcript_prompt.txt"
        elif prompt_type == 'knowledge':
            prompt_key = f"Prompts/{job_id}/knowledge_prompt.txt"
        else:
            logger.error(f"Unknown prompt type: {prompt_type}")
            return None
        
        logger.info(f"Fetching {prompt_type} prompt from S3: {prompt_key}")
        response = s3_client.get_object(Bucket=S3_BUCKET, Key=prompt_key)
        prompt_text = response['Body'].read().decode('utf-8')
        logger.info(f"Successfully fetched {prompt_type} prompt ({len(prompt_text)} bytes)")
        return prompt_text
    except ClientError as e:
        logger.error(f"Error fetching {prompt_type} prompt from S3: {e}")
        return None


def read_pdf_from_s3(pdf_key):
    logger.info(f"Attempting to read PDF from s3://{S3_BUCKET}/{pdf_key}")
    response = s3_client.get_object(Bucket=S3_BUCKET, Key=pdf_key)
    pdf_bytes = response["Body"].read()
    pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")
    logger.info(f"Successfully read PDF ({len(pdf_bytes)} bytes)")
    return pdf_base64, pdf_bytes


def save_to_s3(content, s3_key):
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=content.encode("utf-8"),
        ContentType="text/plain; charset=utf-8",
        ContentEncoding="utf-8",
    )
    logger.info(f"Saved to S3: {s3_key}")


def save_metadata_to_s3(s3_key, folder_path, job_id, original_file_name, 
                          original_s3_key, stated_in_document="-", processing_mode="full"):
    """
    Save metadata file for Knowledge Base (with job_id and folder_path)
    
    Args:
        s3_key: "Knowledge/{folder_path}/{job_id}/file_001.txt.metadata.json"
        folder_path: "フォルダ1/フォルダ1-1"
        job_id: "20251105120000"
        original_file_name: "賁E��1.pdf"
        original_s3_key: "PDF/フォルダ1/フォルダ1-1/賁E��1.pdf"
        stated_in_document: "p.5"
        processing_mode: "full", "reknowledge", or "direct_pdf"
    """
    source_uri = f"s3://{S3_BUCKET}/{original_s3_key}"
    
    metadata = {
        "metadataAttributes": {
            "FileName": {
                "value": {
                    "type": "STRING",
                    "stringValue": original_file_name
                },
                "includeForEmbedding": True
            },
            "s3Key": {
                "value": {
                    "type": "STRING",
                    "stringValue": original_s3_key
                },
                "includeForEmbedding": True
            },
            "folder_path": {
                "value": {
                    "type": "STRING",
                    "stringValue": folder_path
                },
                "includeForEmbedding": True
            },
            "job_id": {
                "value": {
                    "type": "STRING",
                    "stringValue": job_id
                },
                "includeForEmbedding": True
            },
            "source_uri": {
                "value": {
                    "type": "STRING",
                    "stringValue": source_uri
                },
                "includeForEmbedding": True
            }
        }
    }
    
    # Only include statedindocument for full/reknowledge processing
    if processing_mode != "direct_pdf":
        metadata["metadataAttributes"]["statedindocument"] = {
            "value": {
                "type": "STRING",
                "stringValue": stated_in_document
            },
            "includeForEmbedding": True
        }
    
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json; charset=utf-8",
        ContentEncoding="utf-8",
    )
    logger.info(f"Saved metadata v2 to S3: {s3_key} (job_id={job_id}, folder_path={folder_path})")


def extract_json_from_text(text):
    """
    Extract JSON array from text with potential noise before/after.
    Looks for content between first [ and last ].
    
    Args:
        text: Text potentially containing JSON array
    
    Returns:
        tuple: (success: bool, data: list or None, error_message: str or None)
    """
    try:
        # Find first [ and last ]
        first_bracket = text.find('[')
        last_bracket = text.rfind(']')
        
        if first_bracket == -1 or last_bracket == -1 or first_bracket >= last_bracket:
            return False, None, "No valid JSON array brackets found"
        
        # Extract JSON portion
        json_str = text[first_bracket:last_bracket + 1]
        
        # Parse JSON
        data = json.loads(json_str)
        
        # Validate structure
        if not isinstance(data, list):
            return False, None, "JSON is not an array"
        
        # Validate each item has required fields
        for idx, item in enumerate(data):
            if not isinstance(item, dict):
                return False, None, f"Item {idx} is not an object"
            if "statedindocument" not in item or "content" not in item:
                return False, None, f"Item {idx} missing required fields"
        
        return True, data, None
        
    except json.JSONDecodeError as e:
        return False, None, f"JSON parsing error: {str(e)}"
    except Exception as e:
        return False, None, f"Unexpected error: {str(e)}"


def save_knowledge_chunks(knowledge_text, job_id, folder_path, base_name, file_name, original_s3_key):
    """
    Process knowledge text, extract JSON chunks if possible, and save to S3.
    
    Args:
        knowledge_text: Raw text from Bedrock (may contain JSON array)
        job_id: "20251105120000"
        folder_path: "フォルダ1/フォルダ1-1"
        base_name: Base filename without extension
        file_name: Original PDF filename
        original_s3_key: S3 key of original PDF
    
    Returns:
        int: Number of chunks saved
    """
    """
    Process knowledge text, extract JSON chunks if possible, and save to S3 (v2 - hierarchical).
    
    Args:
        knowledge_text: Raw text from Bedrock (may contain JSON array)
        job_id: Job ID
        folder_path: "フォルダ1/フォルダ1-1"
        base_name: Base filename without extension
        file_name: Original PDF filename
        original_s3_key: S3 key of original PDF
    
    Returns:
        int: Number of chunks saved
    """
    # Try to extract JSON
    success, data, error_msg = extract_json_from_text(knowledge_text)
    
    if success and data:
        logger.info(f"Successfully extracted {len(data)} JSON chunks for v2 schema")
        
        # Save each chunk as separate file
        for idx, item in enumerate(data, start=1):
            stated_in_doc = item.get("statedindocument", "-")
            content = item.get("content", "")
            
            # Save content file (v2 path: Knowledge/{folder_path}/{job_id}/)
            chunk_filename = f"{base_name}_{idx:03d}.txt"
            knowledge_key = f"Knowledge/{folder_path}/{job_id}/{chunk_filename}"
            save_to_s3(content, knowledge_key)
            
            # Save metadata file (with folder_path and job_id)
            metadata_key = f"Knowledge/{folder_path}/{job_id}/{chunk_filename}.metadata.json"
            save_metadata_to_s3(metadata_key, folder_path, job_id, file_name, original_s3_key, stated_in_doc)
        
        return len(data)
    
    else:
        # JSON extraction failed - save as single file with traditional approach
        logger.warning(f"JSON extraction failed: {error_msg}. Saving as single file (v2).")
        
        knowledge_key = f"Knowledge/{folder_path}/{job_id}/{base_name}.txt"
        save_to_s3(knowledge_text, knowledge_key)
        
        # Save metadata with dummy statedindocument
        metadata_key = f"Knowledge/{folder_path}/{job_id}/{base_name}.txt.metadata.json"
        save_metadata_to_s3(metadata_key, folder_path, job_id, file_name, original_s3_key, "-")
        
        return 1

    logger.info(f"Metadata: FileName={original_file_name}, s3Key={original_s3_key}")


def copy_s3_object(source_key, dest_key):
    """Copy S3 object from source to destination"""
    try:
        s3_client.copy_object(
            Bucket=S3_BUCKET,
            CopySource={'Bucket': S3_BUCKET, 'Key': source_key},
            Key=dest_key
        )
        logger.info(f"Copied S3 object: {source_key} -> {dest_key}")
    except ClientError as e:
        logger.error(f"Error copying S3 object: {e}")
        raise


def read_transcript_from_s3(transcript_key):
    """Read transcript content from S3"""
    try:
        response = s3_client.get_object(Bucket=S3_BUCKET, Key=transcript_key)
        content = response['Body'].read().decode('utf-8')
        logger.info(f"Successfully read transcript from: {transcript_key}")
        return content
    except ClientError as e:
        logger.error(f"Error reading transcript from S3: {e}")
        raise




# ===== Knowledge Base Sync は別 Lambda で処琁E=====
# trigger_knowledge_base_sync() 関数は削除されました
# Step Functions が最後�Eファイル処琁E��に BedrockKBSyncLambda を呼び出しまぁE

def update_dynamodb_status(job_id, folder_path, file_name, status, message, 
                             file_key=None, processing_mode=None, source_job_id=None):
    """Update DynamoDB status (with composite key)"""
    update_expr = "SET #status = :status, last_update = :ts, #msg = :msg"
    expr_names = {"#status": "status", "#msg": "message"}
    expr_values = {
        ":status": status,
        ":ts": datetime.now(JST).isoformat(),
        ":msg": message,
    }
    
    # file_keyが指定されてぁE��場合、S3キーも保孁E
    if file_key:
        update_expr += ", file_key = :file_key"
        expr_values[":file_key"] = file_key
    
    # processing_modeが指定されてぁE��場合、�E琁E��ードを保孁E
    if processing_mode:
        update_expr += ", processing_mode = :processing_mode"
        expr_values[":processing_mode"] = processing_mode
    
    # source_job_idが指定されてぁE��場合、�EジョブIDを保孁E
    if source_job_id:
        update_expr += ", source_job_id = :source_job_id"
        expr_values[":source_job_id"] = source_job_id
    
    # 褁E��キー: job_id (PK) + folder_path#file_name (SK)
    composite_key = f"{folder_path}#{file_name}"
    
    jobs_table.update_item(
        Key={
            "job_id": job_id,
            "folder_path#file_name": composite_key
        },
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )
    logger.info(f"Updated DynamoDB - Job: {job_id}, Folder: {folder_path}, File: {file_name}, Status: {status}")
    if file_key:
        logger.info(f"  File key: {file_key}")
    if processing_mode:
        logger.info(f"  Processing mode: {processing_mode}")
    if source_job_id:
        logger.info(f"  Source job ID: {source_job_id}")


# ===== Bedrock 呼び出ぁE=====
def invoke_bedrock(payload_obj):
    """Anthropic用: anthropic_version フィールドを含める"""
    request = {
        "modelId": BEDROCK_MODEL_ID,
        "contentType": "application/json",
        "accept": "application/json",
        "body": json.dumps(payload_obj),
    }
    logger.info(f"Invoking Bedrock via modelId={BEDROCK_MODEL_ID}")
    try:
        response = bedrock_client.invoke_model(**request)
        raw = response["body"].read()
        text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
        return json.loads(text)
    except Exception as e:
        logger.error(f"Error invoking Bedrock model: {e}")
        raise


# ===== メイン処琁E=====
def process_pdf_on_demand(job_id, file_key, file_name):
    """
    Full processing: File -> Transcription -> Knowledge
    
    Fetches prompts from S3 instead of receiving them as parameters
    """
    update_dynamodb_status(job_id, file_name, "running", "Processing started", file_key=file_key, processing_mode="full")

    # --- Fetch prompts from S3 ---
    transcript_prompt = get_prompt_from_s3(job_id, 'transcript')
    knowledge_prompt = get_prompt_from_s3(job_id, 'knowledge')
    
    if not transcript_prompt or not knowledge_prompt:
        error_msg = "Failed to fetch prompts from S3"
        logger.error(error_msg)
        update_dynamodb_status(job_id, file_name, "failed", error_msg)
        raise Exception(error_msg)

    # --- File reading from S3 ---
    pdf_base64, _ = read_pdf_from_s3(file_key)

    # --- Transcription ---
    body_obj = {
        "anthropic_version": "bedrock-2023-05-31",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_base64,
                        },
                    },
                    {"type": "text", "text": transcript_prompt},
                ],
            }
        ],
        "max_tokens": BEDROCK_MAX_TOKENS,
    }

    resp = invoke_bedrock(body_obj)
    transcription_text = resp.get("content", [{}])[0].get("text", "")

    base_name = file_name.rsplit(".pdf", 1)[0] if file_name.lower().endswith(".pdf") else file_name
    transcript_key = f"Transcript/{job_id}/{base_name}.txt"
    save_to_s3(transcription_text, transcript_key)

    # --- Knowledge 抽出 ---
    body_obj = {
        "anthropic_version": "bedrock-2023-05-31",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"{knowledge_prompt}\n\n---\n\n{transcription_text}"},
                ],
            }
        ],
        "max_tokens": BEDROCK_MAX_TOKENS,
    }

    resp = invoke_bedrock(body_obj)
    knowledge_text = resp.get("content", [{}])[0].get("text", "")
    
    # Save knowledge chunks (with JSON extraction if possible)
    original_s3_key = file_key  # PDF/{job_id}/filename.pdf or PDF/filename.pdf
    num_chunks = save_knowledge_chunks(knowledge_text, job_id, base_name, file_name, original_s3_key)
    logger.info(f"Saved {num_chunks} knowledge chunk(s)")

    update_dynamodb_status(job_id, file_name, "done", "Processing completed")


def process_reknowledge(job_id, source_job_id, folder_path, file_name):
    """
    Reknowledge processing (v2): Copy transcript and regenerate knowledge only
    
    Fetches knowledge prompt from S3 and generates knowledge for new job_id
    Args:
        job_id: New job_id for reknowledge results
        source_job_id: Original job_id to copy transcript from
        folder_path: Folder path (v2 schema)
        file_name: PDF file name
    """
    update_dynamodb_status(
        job_id, folder_path, file_name, "running", 
        f"Reknowledge processing started from source job {source_job_id}",
        processing_mode="reknowledge",
        source_job_id=source_job_id
    )

    # --- Fetch knowledge prompt from S3 (v2 path) ---
    knowledge_prompt_key = f"Prompts/{folder_path}/{job_id}/knowledge_prompt.txt"
    try:
        response = s3_client.get_object(Bucket=S3_BUCKET, Key=knowledge_prompt_key)
        knowledge_prompt = response['Body'].read().decode('utf-8')
    except Exception as e:
        error_msg = f"Failed to fetch knowledge prompt from S3: {str(e)}"
        logger.error(error_msg)
        update_dynamodb_status(job_id, folder_path, file_name, "failed", error_msg)
        raise Exception(error_msg)

    # --- Copy transcript from source job (v2: Transcript/{folder_path}/{job_id}/{file}.txt) ---
    base_name = file_name.rsplit(".pdf", 1)[0] if file_name.lower().endswith(".pdf") else file_name
    source_transcript_key = f"Transcript/{folder_path}/{source_job_id}/{base_name}.txt"
    dest_transcript_key = f"Transcript/{folder_path}/{job_id}/{base_name}.txt"
    
    try:
        copy_s3_object(source_transcript_key, dest_transcript_key)
        logger.info(f"Copied transcript from {source_transcript_key} to {dest_transcript_key}")
    except Exception as e:
        error_msg = f"Failed to copy transcript: {str(e)}"
        update_dynamodb_status(job_id, folder_path, file_name, "failed", error_msg)
        raise

    # --- Read copied transcript ---
    try:
        transcription_text = read_transcript_from_s3(dest_transcript_key)
    except Exception as e:
        error_msg = f"Failed to read transcript: {str(e)}"
        update_dynamodb_status(job_id, folder_path, file_name, "failed", error_msg)
        raise

    # --- Generate knowledge with new prompt ---
    body_obj = {
        "anthropic_version": "bedrock-2023-05-31",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"{knowledge_prompt}\n\n---\n\n{transcription_text}"},
                ],
            }
        ],
        "max_tokens": BEDROCK_MAX_TOKENS,
    }

    resp = invoke_bedrock(body_obj)
    knowledge_text = resp.get("content", [{}])[0].get("text", "")
    
    # Save knowledge chunks (v2: Knowledge/{folder_path}/{job_id}/{file}_001.txt)
    original_s3_key = f"PDF/{folder_path}/{file_name}"
    num_chunks = save_knowledge_chunks(knowledge_text, job_id, base_name, file_name, original_s3_key, folder_path)
    logger.info(f"Saved {num_chunks} knowledge chunk(s) for reknowledge job")

    update_dynamodb_status(job_id, folder_path, file_name, "done", "Reknowledge processing completed")


def process_direct_pdf(job_id, folder_path, file_key, file_name):
    """
    Direct PDF mode: Copy PDF directly to Knowledge folder without processing
    
    Args:
        job_id: Job ID
        folder_path: Folder path (e.g., "フォルダ1/フォルダ1-1")
        file_key: S3 key of the PDF (e.g., "PDF/フォルダ1/フォルダ1-1/資料.pdf")
        file_name: Original file name
    """
    update_dynamodb_status(
        job_id, folder_path, file_name, "running", 
        "Processing started (direct_pdf)", file_key=file_key, processing_mode="direct_pdf"
    )
    
    try:
        # Copy PDF from PDF/ to Knowledge/
        dest_key = f"Knowledge/{folder_path}/{job_id}/{file_name}"
        copy_s3_object(file_key, dest_key)
        logger.info(f"Copied PDF from {file_key} to {dest_key}")
        
        # Save metadata for Knowledge Base
        metadata_key = f"Knowledge/{folder_path}/{job_id}/{file_name}.metadata.json"
        original_s3_key = file_key  # PDF/{folder_path}/filename.pdf
        save_metadata_to_s3(
            metadata_key, folder_path, job_id, file_name, 
            original_s3_key, processing_mode="direct_pdf"
        )
        logger.info(f"Saved metadata for direct PDF: {metadata_key}")
        
        update_dynamodb_status(
            job_id, folder_path, file_name, "done", 
            "Direct PDF processing completed", processing_mode="direct_pdf"
        )
        
    except Exception as e:
        error_msg = f"Failed to process direct PDF: {str(e)}"
        logger.error(error_msg, exc_info=True)
        update_dynamodb_status(job_id, folder_path, file_name, "failed", error_msg)
        raise


def process_pdf_on_demand(job_id, folder_path, file_key, file_name):
    """
    Full processing with v2 schema: File -> Transcription -> Knowledge (hierarchical structure)
    
    Fetches prompts from S3: Prompts/{folder_path}/{job_id}/
    Saves outputs to: Transcript/{folder_path}/{job_id}/, Knowledge/{folder_path}/{job_id}/
    """
    update_dynamodb_status(
        job_id, folder_path, file_name, "running", 
        "Processing started (v2)", file_key=file_key, processing_mode="full"
    )

    # --- Fetch prompts from S3 (v2 path) ---
    transcript_prompt_key = f"Prompts/{folder_path}/{job_id}/transcript_prompt.txt"
    knowledge_prompt_key = f"Prompts/{folder_path}/{job_id}/knowledge_prompt.txt"
    
    try:
        response = s3_client.get_object(Bucket=S3_BUCKET, Key=transcript_prompt_key)
        transcript_prompt = response['Body'].read().decode('utf-8')
        
        response = s3_client.get_object(Bucket=S3_BUCKET, Key=knowledge_prompt_key)
        knowledge_prompt = response['Body'].read().decode('utf-8')
        
        logger.info(f"Successfully fetched prompts for v2 schema (folder: {folder_path}, job: {job_id})")
    except ClientError as e:
        error_msg = f"Failed to fetch prompts from S3 (v2): {e}"
        logger.error(error_msg)
        update_dynamodb_status(job_id, folder_path, file_name, "failed", error_msg)
        raise Exception(error_msg)

    # --- File reading from S3 ---
    pdf_base64, _ = read_pdf_from_s3(file_key)

    # --- Transcription ---
    body_obj = {
        "anthropic_version": "bedrock-2023-05-31",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_base64,
                        },
                    },
                    {"type": "text", "text": transcript_prompt},
                ],
            }
        ],
        "max_tokens": BEDROCK_MAX_TOKENS,
    }

    resp = invoke_bedrock(body_obj)
    transcription_text = resp.get("content", [{}])[0].get("text", "")

    base_name = file_name.rsplit(".pdf", 1)[0] if file_name.lower().endswith(".pdf") else file_name
    transcript_key = f"Transcript/{folder_path}/{job_id}/{base_name}.txt"
    save_to_s3(transcription_text, transcript_key)

    # --- Knowledge 抽出 ---
    body_obj = {
        "anthropic_version": "bedrock-2023-05-31",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"{knowledge_prompt}\n\n---\n\n{transcription_text}"},
                ],
            }
        ],
        "max_tokens": BEDROCK_MAX_TOKENS,
    }

    resp = invoke_bedrock(body_obj)
    knowledge_text = resp.get("content", [{}])[0].get("text", "")
    
    # Save knowledge chunks (with folder_path)
    original_s3_key = file_key  # PDF/{folder_path}/filename.pdf
    num_chunks = save_knowledge_chunks(knowledge_text, job_id, folder_path, base_name, file_name, original_s3_key)
    logger.info(f"Saved {num_chunks} knowledge chunk(s)")

    update_dynamodb_status(job_id, folder_path, file_name, "done", "Processing completed")


def lambda_handler(event, context):
    """
    Step Functions Task Handler
    
    Processes a single file invoked directly by Step Functions.
    Supports two processing modes and two schema versions:
    
    Mode 1 - Full Processing (File -> Transcription -> Knowledge):
    v1 (legacy):
    {
        "mode": "full",
        "job_id": "20251028123456",
        "file_key": "PDF/example.pdf",
        "file_name": "example.pdf",
        "trigger_kb_sync": false
    }
    
    v2 (hierarchical):
    {
        "mode": "full",
        "job_id": "20251028123456",
        "folder_path": "フォルダ1/フォルダ1-1",
        "file_key": "PDF/フォルダ1/フォルダ1-1/example.pdf",
        "file_name": "example.pdf",
        "trigger_kb_sync": false
    }
    
    Mode 2 - Reknowledge Processing (Copy Transcript -> Regenerate Knowledge):
    {
        "mode": "reknowledge",
        "job_id": "20251028123456",
        "source_job_id": "20251027120000",
        "file_name": "example.pdf",
        "trigger_kb_sync": false
    }
    """
    try:
        logger.info(f"Received Step Functions invocation")
        logger.info(f"Event: {json.dumps(event, default=str)}")
        
        # Extract common parameters
        mode = event.get("mode", "full")
        job_id = event.get("job_id")
        file_name = event.get("file_name") or event.get("pdf_name")  # Backward compatibility
        folder_path = event.get("folder_path")  # v2 parameter
        trigger_kb_sync = event.get("trigger_kb_sync", False)
        
        if not all([job_id, file_name]):
            raise ValueError("Missing required parameters: job_id or file_name")
        
        logger.info(f"Processing mode: {mode}, job {job_id}, File: {file_name}, Folder: {folder_path}")
        
        # Process based on mode
        if mode == "reknowledge":
            # Reknowledge mode: Copy transcript and regenerate knowledge
            source_job_id = event.get("source_job_id")
            if not source_job_id or not folder_path:
                raise ValueError("Missing required parameters for reknowledge mode: source_job_id and folder_path")
            
            process_reknowledge(job_id, source_job_id, folder_path, file_name)
            
        elif mode == "direct_pdf":
            # Direct PDF mode: Copy PDF directly to Knowledge folder
            file_key = event.get("file_key") or event.get("pdf_key")
            
            if not file_key or not folder_path:
                raise ValueError("Missing required parameters for direct_pdf mode: file_key and folder_path")
            
            logger.info(f"Using direct_pdf mode for folder: {folder_path}")
            process_direct_pdf(job_id, folder_path, file_key, file_name)
            
        else:
            # Full mode: File -> Transcription -> Knowledge
            file_key = event.get("file_key") or event.get("pdf_key")  # Backward compatibility
            
            if not file_key:
                raise ValueError("Missing required parameter for full mode: file_key")
            
            # v2 schema: folder_path が指定されてぁE��場吁E
            if folder_path:
                logger.info(f"Using v2 schema (hierarchical) for folder: {folder_path}")
                process_pdf_on_demand(job_id, folder_path, file_key, file_name)
            else:
                # v1 schema: legacy
                logger.info("Using v1 schema (flat structure)")
                process_pdf_on_demand(job_id, file_key, file_name)
        
        logger.info(f"Successfully processed file: {file_name}")
        
        # Note: Knowledge Base sync is now handled by a separate Lambda
        # Step Functions will call BedrockKBSyncLambda after the last file is processed
        
        # Return success response (pass through trigger_kb_sync flag)
        trigger_kb_sync = event.get('trigger_kb_sync', False)
        
        return {
            "statusCode": 200,
            "job_id": job_id,
            "file_name": file_name,
            "folder_path": folder_path,
            "mode": mode,
            "status": "completed",
            "trigger_kb_sync": trigger_kb_sync,
            "message": f"Successfully processed {file_name} in {mode} mode"
        }
        
    except Exception as e:
        logger.error(f"Error processing file: {e}", exc_info=True)
        
        # Update DynamoDB status to failed
        if 'job_id' in event:
            file_name_fallback = event.get('file_name') or event.get('pdf_name')
            folder_path_fallback = event.get('folder_path')
            
            if file_name_fallback:
                try:
                    # v2 また�E v1 に応じて適刁E��関数を呼び出ぁE
                    if folder_path_fallback:
                        update_dynamodb_status(
                            event['job_id'],
                            folder_path_fallback,
                            file_name_fallback,
                            "failed",
                            f"Error: {str(e)}"
                        )
                    else:
                        update_dynamodb_status(
                            event['job_id'],
                            file_name_fallback,
                            "failed",
                            f"Error: {str(e)}"
                        )
                except Exception as db_error:
                    logger.error(f"Failed to update DynamoDB: {db_error}")
        
        # Re-raise the exception so Step Functions can retry
        raise
