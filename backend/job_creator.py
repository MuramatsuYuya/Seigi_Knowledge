"""
PDF OCR System - Job Creator Lambda

Receives processing requests from API Gateway and:
1. Generates a job ID (YYYYMMDDhhmmss)
2. Registers job in DynamoDB
3. Starts Step Functions execution for PDF processing
4. Returns job ID to frontend
"""

import json
import boto3
import os
from datetime import datetime, timezone, timedelta
import logging
from botocore.exceptions import ClientError
from folder_tree_helper import get_folder_tree

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS Clients
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
stepfunctions_client = boto3.client('stepfunctions')

# Environment variables
DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']
DYNAMODB_FOLDER_CONFIG_TABLE = os.environ.get('DYNAMODB_FOLDER_CONFIG_TABLE', '')
S3_BUCKET = os.environ['S3_BUCKET']
STATE_MACHINE_ARN = os.environ.get('STATE_MACHINE_ARN', '')

# DynamoDB tables
jobs_table = dynamodb.Table(DYNAMODB_TABLE)
folder_config_table = dynamodb.Table(DYNAMODB_FOLDER_CONFIG_TABLE) if DYNAMODB_FOLDER_CONFIG_TABLE else None

# JST timezone (UTC+9)
JST = timezone(timedelta(hours=9))


def generate_job_id():
    """Generate job ID in format YYYYMMDDhhmmss (JST)"""
    return datetime.now(JST).strftime('%Y%m%d%H%M%S')


def get_pdf_files_in_folder(folder_path, specific_files=None):
    """
    指定フォルダ配下のすべてのPDFファイルを取得（階層対応）
    
    Args:
        folder_path: "フォルダ1/フォルダ1-1" (先頭の PDF/ は含めない)
        specific_files: Optional list of specific file names to filter
    
    Returns:
        [
            {
                "file_key": "PDF/フォルダ1/フォルダ1-1/資料1.pdf",
                "folder_path": "フォルダ1/フォルダ1-1",
                "file_name": "資料1.pdf"
            },
            ...
        ]
    """
    try:
        # S3 Prefix を構築
        prefix = f"PDF/{folder_path}/"
        logger.info(f"Searching for PDF files in: {prefix}")
        
        pdf_files = []
        paginator = s3_client.get_paginator('list_objects_v2')
        
        for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
            if 'Contents' not in page:
                continue
                
            for obj in page['Contents']:
                key = obj['Key']
                
                # PDFファイルのみ対象
                if not key.endswith('.pdf'):
                    continue
                
                # ファイル名を抽出
                file_name = key.split('/')[-1]
                
                # specific_files が指定されている場合、フィルター
                if specific_files and file_name not in specific_files:
                    continue
                
                pdf_files.append({
                    'file_key': key,
                    'folder_path': folder_path,
                    'file_name': file_name
                })
        
        logger.info(f"Found {len(pdf_files)} PDF files in {folder_path}")
        return pdf_files
        
    except ClientError as e:
        logger.error(f"Error listing PDF files in folder {folder_path}: {e}")
        return []


def check_folder_has_children(folder_path):
    """
    フォルダが子フォルダを持つかチェック
    
    Args:
        folder_path: "フォルダ1" または "フォルダ1/フォルダ1-1"
    
    Returns:
        True if folder has children, False otherwise
    """
    try:
        prefix = f"PDF/{folder_path}/"
        
        # 子フォルダを探す（delimiter='/' で階層を区切る）
        response = s3_client.list_objects_v2(
            Bucket=S3_BUCKET,
            Prefix=prefix,
            Delimiter='/',
            MaxKeys=10
        )
        
        # CommonPrefixes があれば子フォルダが存在
        has_children = 'CommonPrefixes' in response and len(response['CommonPrefixes']) > 0
        
        logger.info(f"Folder {folder_path} has children: {has_children}")
        return has_children
        
    except ClientError as e:
        logger.error(f"Error checking folder children: {e}")
        return False


def register_job_in_dynamodb(job_id, folder_path, pdf_files, processing_mode='full'):
    """
    ジョブ登録（複合キー対応）
    
    Args:
        job_id: "20251105120000"
        folder_path: "フォルダ1/フォルダ1-1"
        pdf_files: [
            {
                "file_key": "PDF/フォルダ1/フォルダ1-1/資料1.pdf",
                "folder_path": "フォルダ1/フォルダ1-1",
                "file_name": "資料1.pdf"
            },
            ...
        ]
        processing_mode: "full", "reknowledge", or "direct_pdf" (default: "full")
    """
    try:
        for pdf_file in pdf_files:
            file_name = pdf_file['file_name']
            file_key = pdf_file['file_key']
            
            # 複合キー: job_id (PK) + folder_path#file_name (SK)
            jobs_table.put_item(
                Item={
                    'job_id': job_id,
                    'folder_path#file_name': f"{folder_path}#{file_name}",
                    'folder_path': folder_path,
                    'file_name': file_name,
                    'file_key': file_key,
                    'status': 'queued',
                    'processing_mode': processing_mode,
                    'last_update': datetime.now(JST).isoformat(),
                    'message': 'Job queued for processing'
                }
            )
        
        logger.info(f"Registered {len(pdf_files)} files in DynamoDB v2 for job {job_id}, folder {folder_path}")
        
        # フォルダ設定テーブルに最新job_idを更新（既存属性を保護）
        if folder_config_table:
            try:
                folder_config_table.update_item(
                    Key={'folder_path': folder_path},
                    UpdateExpression='SET latest_job_id = :jid, #lu = :ts',
                    ExpressionAttributeNames={'#lu': 'last_update'},
                    ExpressionAttributeValues={
                        ':jid': job_id,
                        ':ts': datetime.now(JST).isoformat()
                    }
                )
                logger.info(f"Updated folder config: {folder_path} -> job_id {job_id}")
            except ClientError as e:
                logger.warning(f"Failed to update folder config table: {e}")
        
    except ClientError as e:
        logger.error(f"Error registering job in DynamoDB v2: {e}")
        raise
        
    except ClientError as e:
        logger.error(f"Error registering job in DynamoDB v2: {e}")
        raise


def set_default_job_id(folder_path, job_id):
    """
    フォルダのデフォルトJOB_IDを設定
    
    Args:
        folder_path: "生技資料/生技25"
        job_id: "20251106120000"
    """
    try:
        if not DYNAMODB_FOLDER_CONFIG_TABLE:
            logger.error("DYNAMODB_FOLDER_CONFIG_TABLE not configured")
            return False
        
        folder_config_table = dynamodb.Table(DYNAMODB_FOLDER_CONFIG_TABLE)
        JST = timezone(timedelta(hours=9))
        
        # update_item で既存属性を保護（latest_job_id などが消えないようにする）
        folder_config_table.update_item(
            Key={'folder_path': folder_path},
            UpdateExpression='SET default_job_id = :djid, #lu = :ts',
            ExpressionAttributeNames={'#lu': 'last_update'},
            ExpressionAttributeValues={
                ':djid': job_id,
                ':ts': datetime.now(JST).isoformat()
            }
        )
        logger.info(f"Set default job_id for folder {folder_path}: {job_id}")
        return True
        
    except ClientError as e:
        logger.error(f"Error setting default job_id: {e}")
        return False


def get_default_job_id(folder_path):
    """
    フォルダのデフォルトJOB_IDを取得
    
    Args:
        folder_path: "生技資料/生技25"
        
    Returns:
        job_id or None
    """
    try:
        if not DYNAMODB_FOLDER_CONFIG_TABLE:
            logger.error("DYNAMODB_FOLDER_CONFIG_TABLE not configured")
            return None
        
        folder_config_table = dynamodb.Table(DYNAMODB_FOLDER_CONFIG_TABLE)
        
        response = folder_config_table.get_item(
            Key={'folder_path': folder_path}
        )
        
        if 'Item' in response and 'default_job_id' in response['Item']:
            job_id = response['Item']['default_job_id']
            logger.info(f"Found default job_id for folder {folder_path}: {job_id}")
            return job_id
        else:
            logger.info(f"No default job_id found for folder {folder_path}")
            return None
            
    except ClientError as e:
        logger.error(f"Error getting default job_id: {e}")
        return None


def start_step_functions_execution(job_id, folder_path, pdf_files, transcript_prompt, knowledge_prompt, processing_mode='full'):
    """
    Start Step Functions execution for file processing
    
    Args:
        job_id: "20251105120000"
        folder_path: "フォルダ1/フォルダ1-1"
        pdf_files: [{"file_key": "...", "folder_path": "...", "file_name": "..."}]
        transcript_prompt: プロンプト文字列
        knowledge_prompt: プロンプト文字列
        processing_mode: "full", "reknowledge", or "direct_pdf" (default: "full")
    """
    try:
        # Save prompts to S3 (only if not direct_pdf mode)
        if processing_mode != 'direct_pdf':
            # Save prompts to S3 (新パス: Prompts/{folder_path}/{job_id}/)
            transcript_prompt_key = f"Prompts/{folder_path}/{job_id}/transcript_prompt.txt"
            knowledge_prompt_key = f"Prompts/{folder_path}/{job_id}/knowledge_prompt.txt"
            
            logger.info(f"Saving prompts to S3 for job {job_id}, folder {folder_path}")
            s3_client.put_object(
                Bucket=S3_BUCKET,
                Key=transcript_prompt_key,
                Body=transcript_prompt.encode('utf-8'),
                ContentType='text/plain; charset=utf-8'
            )
            s3_client.put_object(
                Bucket=S3_BUCKET,
                Key=knowledge_prompt_key,
                Body=knowledge_prompt.encode('utf-8'),
                ContentType='text/plain; charset=utf-8'
            )
            logger.info(f"Saved prompts to S3: {transcript_prompt_key}, {knowledge_prompt_key}")
        else:
            logger.info(f"Skipping prompt save for direct_pdf mode")
        
        # Prepare Step Functions input with folder_path
        file_items = []
        for pdf_file in pdf_files:
            file_items.append({
                'mode': processing_mode,
                'job_id': job_id,
                'folder_path': folder_path,
                'file_key': pdf_file['file_key'],
                'file_name': pdf_file['file_name'],
                'trigger_kb_sync': False
            })
        
        # Add KB sync flag to the last item
        if file_items:
            file_items[-1]['trigger_kb_sync'] = True
        
        execution_input = {
            'files': file_items
        }
        
        # Check input size
        execution_input_str = json.dumps(execution_input, ensure_ascii=False)
        input_size = len(execution_input_str.encode('utf-8'))
        max_size = 262144
        logger.info(f"Step Functions input size: {input_size} bytes (max: {max_size})")
        
        if input_size > max_size:
            error_msg = f"Execution input too large: {input_size} bytes (max: {max_size})"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # Start Step Functions execution
        response = stepfunctions_client.start_execution(
            stateMachineArn=STATE_MACHINE_ARN,
            name=f"job-{job_id}",
            input=execution_input_str
        )
        
        execution_arn = response['executionArn']
        logger.info(f"Started Step Functions execution v2: {execution_arn}")
        return execution_arn
        
    except ClientError as e:
        logger.error(f"Error starting Step Functions execution v2: {e}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"Unexpected error starting Step Functions v2: {e}", exc_info=True)
        raise


def lambda_handler(event, context):
    """
    Main Lambda handler for job creation (v2 - hierarchical structure only)
    
    Routes:
    - GET /api/folders: Get folder tree structure
    - GET /list-pdfs?folder_path=xxx: List PDFs in a folder
    - POST /api/job: Creates processing job with folder_path
    - POST /api/reknowledge: Re-generate knowledge for existing job
    
    Expected input for POST /api/job:
    {
        "folder_path": "フォルダ1/フォルダ1-1",
        "transcript_prompt": "文字起こしのプロンプト",
        "knowledge_prompt": "ナレッジベース生成のプロンプト",
        "pdfFiles": ["file1.pdf", "file2.pdf"]  // Optional: specific files to process
    }
    
    Expected input for POST /api/reknowledge:
    {
        "job_id": "20251106145706",
        "folder_path": "生技資料/生技25/MC巻き線ライン",
        "knowledge_prompt": "新しいナレッジベース生成のプロンプト"
    }
    """
    try:
        # ルーティング処理
        http_method = event.get('httpMethod', event.get('requestContext', {}).get('http', {}).get('method', 'POST'))
        path = event.get('path', event.get('requestContext', {}).get('http', {}).get('path', '/api/job'))
        
        logger.info(f"Request: {http_method} {path}")
        
        # GET /api/folders - フォルダツリー取得
        if http_method == 'GET' and path == '/api/folders':
            folder_tree = get_folder_tree()
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps(folder_tree, ensure_ascii=False)
            }
        
        # GET /list-pdfs - フォルダ内のPDF一覧取得
        if http_method == 'GET' and (path == '/list-pdfs' or path == '/api/list-pdfs'):
            logger.info(f"list-pdfs request - full event: {json.dumps(event, ensure_ascii=False)}")
            query_params = event.get('queryStringParameters', {}) or {}
            logger.info(f"Query parameters: {query_params}")
            folder_path = query_params.get('folder_path', '')
            logger.info(f"Extracted folder_path: '{folder_path}'")
            
            if not folder_path:
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({'error': 'folder_path is required'})
                }
            
            pdf_files = get_pdf_files_in_folder(folder_path)
            file_names = [pdf['file_name'] for pdf in pdf_files]
            
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'files': file_names,
                    'count': len(file_names)
                }, ensure_ascii=False)
            }
        
        # POST /api/default-job - デフォルトJOB_IDの設定
        if http_method == 'POST' and (path == '/default-job' or path == '/api/default-job'):
            body = json.loads(event.get('body', '{}')) if isinstance(event.get('body'), str) else event
            folder_path = body.get('folder_path', '')
            job_id = body.get('job_id', '')
            
            if not folder_path or not job_id:
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({'error': 'folder_path and job_id are required'})
                }
            
            success = set_default_job_id(folder_path, job_id)
            
            if success:
                return {
                    'statusCode': 200,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'message': 'Default job_id set successfully',
                        'folder_path': folder_path,
                        'job_id': job_id
                    }, ensure_ascii=False)
                }
            else:
                return {
                    'statusCode': 500,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({'error': 'Failed to set default job_id'})
                }
        
        # GET /api/default-job?folder_path=xxx - デフォルトJOB_IDの取得
        if http_method == 'GET' and (path == '/default-job' or path == '/api/default-job'):
            query_params = event.get('queryStringParameters', {}) or {}
            folder_path = query_params.get('folder_path', '')
            
            if not folder_path:
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({'error': 'folder_path is required'})
                }
            
            job_id = get_default_job_id(folder_path)
            
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'folder_path': folder_path,
                    'job_id': job_id
                }, ensure_ascii=False)
            }
        
        # POST /api/reknowledge - 既存ジョブのナレッジ再生成（新しいjob_idで）
        if http_method == 'POST' and (path == '/reknowledge' or path == '/api/reknowledge'):
            body = json.loads(event.get('body', '{}')) if isinstance(event.get('body'), str) else event
            source_job_id = body.get('job_id', '').strip()  # 元のjob_id
            folder_path = (body.get('folder_path', '') or '').strip()
            knowledge_prompt = body.get('knowledge_prompt', '')
            
            if not source_job_id or not folder_path or not knowledge_prompt:
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'job_id (source), folder_path, and knowledge_prompt are required'
                    })
                }
            
            logger.info(f"Reknowledge request: source_job_id={source_job_id}, folder_path={folder_path}")
            
            # Get existing job items from DynamoDB
            try:
                response = jobs_table.query(
                    KeyConditionExpression='job_id = :jid AND begins_with(#sk, :folder_prefix)',
                    ExpressionAttributeNames={'#sk': 'folder_path#file_name'},
                    ExpressionAttributeValues={
                        ':jid': source_job_id,
                        ':folder_prefix': folder_path + '#'
                    }
                )
                
                job_items = response.get('Items', [])
                
                if not job_items:
                    return {
                        'statusCode': 404,
                        'headers': {
                            'Content-Type': 'application/json',
                            'Access-Control-Allow-Origin': '*'
                        },
                        'body': json.dumps({
                            'error': f'No job found for source_job_id={source_job_id}, folder_path={folder_path}'
                        })
                    }
                
                # Generate new job_id
                new_job_id = generate_job_id()
                logger.info(f"Generated new job_id for reknowledge: {new_job_id}")
                
                # Get source transcript_prompt from S3
                source_transcript_prompt_key = f"Prompts/{folder_path}/{source_job_id}/transcript_prompt.txt"
                transcript_prompt_obj = s3_client.get_object(Bucket=S3_BUCKET, Key=source_transcript_prompt_key)
                transcript_prompt = transcript_prompt_obj['Body'].read().decode('utf-8')
                
                # Save prompts to S3 for new job_id
                transcript_prompt_key = f"Prompts/{folder_path}/{new_job_id}/transcript_prompt.txt"
                knowledge_prompt_key = f"Prompts/{folder_path}/{new_job_id}/knowledge_prompt.txt"
                
                s3_client.put_object(
                    Bucket=S3_BUCKET,
                    Key=transcript_prompt_key,
                    Body=transcript_prompt.encode('utf-8'),
                    ContentType='text/plain'
                )
                s3_client.put_object(
                    Bucket=S3_BUCKET,
                    Key=knowledge_prompt_key,
                    Body=knowledge_prompt.encode('utf-8'),
                    ContentType='text/plain'
                )
                logger.info(f"Saved prompts for new job: {new_job_id}")
                
                # Register new job items in DynamoDB with status='reknowledge'
                pdf_files = []
                for item in job_items:
                    file_name = item.get('file_name') or item.get('pdf_name')
                    file_key = item.get('file_key') or item.get('pdf_key')
                    pdf_files.append({
                        'file_name': file_name,
                        'file_key': file_key
                    })
                
                # Register new job in DynamoDB
                for pdf in pdf_files:
                    sort_key = f"{folder_path}#{pdf['file_name']}"
                    jobs_table.put_item(Item={
                        'job_id': new_job_id,
                        'folder_path#file_name': sort_key,
                        'file_name': pdf['file_name'],
                        'file_key': pdf['file_key'],
                        'folder_path': folder_path,
                        'status': 'reknowledge',
                        'message': f'Waiting for reknowledge processing from source {source_job_id}',
                        'processing_mode': 'reknowledge',
                        'source_job_id': source_job_id,
                        'last_update': datetime.now(JST).isoformat()
                    })
                
                logger.info(f"Registered {len(pdf_files)} files for reknowledge job: {new_job_id}")
                
                # Start Step Functions execution for reknowledge mode
                file_items = []
                for pdf in pdf_files:
                    file_items.append({
                        'mode': 'reknowledge',
                        'job_id': new_job_id,
                        'source_job_id': source_job_id,
                        'folder_path': folder_path,
                        'file_name': pdf['file_name'],
                        'trigger_kb_sync': False
                    })
                
                # Add KB sync flag to the last item
                if file_items:
                    file_items[-1]['trigger_kb_sync'] = True
                
                execution_input = {
                    'files': file_items
                }
                
                execution_arn = None
                if STATE_MACHINE_ARN:
                    response_sf = stepfunctions_client.start_execution(
                        stateMachineArn=STATE_MACHINE_ARN,
                        name=f"{new_job_id}-reknowledge",
                        input=json.dumps(execution_input)
                    )
                    execution_arn = response_sf['executionArn']
                    logger.info(f"Started Step Functions execution: {execution_arn}")
                
                return {
                    'statusCode': 202,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'job_id': new_job_id,
                        'source_job_id': source_job_id,
                        'folder_path': folder_path,
                        'file_count': len(pdf_files),
                        'execution_arn': execution_arn,
                        'message': 'Reknowledge job started with new job_id'
                    })
                }
                
            except Exception as e:
                logger.error(f"Error in reknowledge: {e}", exc_info=True)
                return {
                    'statusCode': 500,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Failed to process reknowledge request',
                        'message': str(e)
                    })
                }
        
        # POST /api/job - ジョブ作成
        if http_method == 'POST' and (path == '/job' or path == '/api/job'):
            # Parse request
            body = json.loads(event.get('body', '{}')) if isinstance(event.get('body'), str) else event
            folder_path = (body.get('folder_path', '') or '').strip()
            transcript_prompt = body.get('transcript_prompt', '')
            knowledge_prompt = body.get('knowledge_prompt', '')
            requested_pdf_files = body.get('pdfFiles', [])  # Optional: specific files
            processing_mode = body.get('processing_mode', 'full').strip()  # New parameter
            
            # Validate processing_mode
            valid_modes = ['full', 'direct_pdf']
            if processing_mode not in valid_modes:
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': f'Invalid processing_mode. Must be one of: {valid_modes}'
                    })
                }
            
            # Validate required parameters
            if not folder_path:
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
            
            # Prompts are optional for direct_pdf mode
            if processing_mode != 'direct_pdf' and (not transcript_prompt or not knowledge_prompt):
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'transcript_prompt and knowledge_prompt are required for non-direct_pdf modes'
                    })
                }
            
            # Check if folder has child folders (must be leaf folder)
            if check_folder_has_children(folder_path):
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Selected folder has child folders. Please select a leaf folder only.'
                    })
                }
            
            # Generate job ID
            job_id = generate_job_id()
            logger.info(f"Generated job ID: {job_id} for folder_path: {folder_path}")
            
            # Get PDF files in folder
            pdf_files = get_pdf_files_in_folder(folder_path, requested_pdf_files if requested_pdf_files else None)
            
            if not pdf_files:
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': f'No PDF files found in folder: {folder_path}'
                    })
                }
            
            # Register job in DynamoDB
            register_job_in_dynamodb(job_id, folder_path, pdf_files, processing_mode)
            
            # Start Step Functions execution
            execution_arn = start_step_functions_execution(
                job_id, folder_path, pdf_files, transcript_prompt, knowledge_prompt, processing_mode
            )
            
            return {
                'statusCode': 202,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'job_id': job_id,
                    'folder_path': folder_path,
                    'pdf_count': len(pdf_files),
                    'execution_arn': execution_arn,
                    'message': 'Job started via Step Functions'
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

def generate_presigned_url(bucket_name, object_key, expiration=3600):
    """署名付きURL生成"""
    url = s3_client.generate_presigned_url(
        'get_object',
        Params={'Bucket': bucket_name, 'Key': object_key},
        ExpiresIn=expiration
    )
    return url