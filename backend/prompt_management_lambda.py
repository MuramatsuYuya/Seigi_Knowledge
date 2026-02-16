"""
Prompt Template Management Lambda Function

This Lambda function handles CRUD operations for agent output format templates.
The fixed system prompts (rules, action groups, workflows) are defined in 
Bedrock Agent Instructions. This manages only the editable output format templates
that users can customize and insert into their queries.

API Endpoints:
- GET /api/prompt-templates?agentType=xxx           : List templates for agent type
- POST /api/prompt-templates                         : Create new template
- PUT /api/prompt-templates                          : Update existing template
- DELETE /api/prompt-templates?agentType=xxx&templateId=yyy : Delete template

Environment Variables:
    - DYNAMODB_PROMPT_TEMPLATES_TABLE: DynamoDB table for prompt templates
    - AWS_REGION: AWS region
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')

# Environment variables
PROMPT_TEMPLATES_TABLE = os.environ.get('DYNAMODB_PROMPT_TEMPLATES_TABLE', '')

# DynamoDB table
prompt_table = dynamodb.Table(PROMPT_TEMPLATES_TABLE) if PROMPT_TEMPLATES_TABLE else None

# JST timezone (UTC+9)
JST = timezone(timedelta(hours=9))

# Valid agent types
VALID_AGENT_TYPES = ['VERIFICATION', 'SPECIFICATION', 'QUERY_SUPPORT']

# Flag to track if auto-initialization has been done (per Lambda instance)
_defaults_initialized = False

# CORS headers
CORS_HEADERS = {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token',
    'Access-Control-Allow-Methods': 'GET,POST,PUT,DELETE,OPTIONS'
}

# =====================================================
# Default editable prompt templates
# These are the output format templates that users can customize
# The fixed system prompts are defined in Bedrock Agent Instructions
# =====================================================

DEFAULT_EDITABLE_PROMPTS = {
    'VERIFICATION': """【出力形式】
以下の構成で検証計画をプレーンテキスト形式で出力してください:

 検証計画: [設備/技術名]

 1. 背景と目的
背景: なぜこの検証が必要か
目的: 何を達成したいか

 2. 検証項目
各検証項目について以下を記載:

 項目1: [項目名]
検証内容: 具体的な検証手順（ステップバイステップ）
判定基準: 合格/不合格の基準（数値で明確に）
N数: 評価に必要なワークの数
備考：必要に応じて

 項目2: [項目名]
（同様に繰り返し）

 3. 判定基準
総合合格基準: どのような条件を満たせば検証合格とするか
重要項目: 特に重視すべき検証項目
制約条件: 検証上の制約や前提条件

 4. 除外事項
以下の内容はユーザー所有のフォーマットにすでにあるためユーザーに提供不要
| 検証項目 | 検証内容 | 判定基準 |
|----------|----------|----------|
| 安全チェック（安衛チェックシート） | 安衛チェックシートを確認する | チェックシートを満足すること |
| 意地悪動作① | 自動起動中に非常停止釦を押す、エアを落としてみる | 原位置復帰できること |
| 意地悪動作② | 各インターロックは正しく設定されているか | 安全に問題なく設備停止すること |
| NG発生時の設備操作について | NGを発生させ、自動起動再開させるまでの動作を確認する | 動作に不具合ないこと |
| TM確認 | 動画、ストップウォッチで測定 | ラインTM 60 s を満たすこと |
| やり取りシートの指摘対応確認 | やり取りシートを確認する | 対応されていること |
| 承認図指摘事項の改善確認 | 承認図指摘事項の改善確認する | 対応されていること |
| RA指摘事項の改善確認 | RAシートを確認する | 対応されていること |
| hintデータ収集状況確認（①項目精査、②Access取出し、③工程飛び） | hint出力ツールで確認 | hintに問題なく挙がっていること |
| GOT機種名確認 | 段取替えで機種名が変わるか（DGE T,G / RVE T,G） | 機種名が問題なく切り替わること |
| 治具関係準備 | 各項目の要領書作成およびデータ記録 | - |
| 芯出し、原点出し方法の確認 | 方法を確認してドキュメントを残す | - |
| 位置再現・初期位置の記録 | 記録する | - |
| マスターワーク準備 | 品管登録する | - |
| 作業指導票の作成 | 必要なデータをまとめる | - |
| 作業要領書の作成 | 必要なデータをまとめる | - |
| 安全ラベル | 手配内容まとめ一括手配 | - |
| 消耗品リストアップ | 消耗品リストを追加する | - |


""",

    'SPECIFICATION': """【出力形式】
以下の構成で仕様書をプレーンテキスト形式で出力してください:

## 設備仕様書: [設備名]

### 1. 概要
- **設備名称**: 正式名称
- **型番**: モデル番号（分かる場合）
- **メーカー**: 製造元
- **製造国**: 原産国
- **用途**: 主な使用目的
- **導入目的**: なぜこの設備が必要か
- **適用工程**: どの工程で使用するか

### 2. 主要仕様
| 項目 | 仕様 | 備考 |
|------|------|------|
| 外形寸法 | W × D × H (mm) | 設置に必要なスペース |
| 重量 | ○○ kg | 床耐荷重の確認が必要 |
| 電源 | AC ○○V, ○○Hz, ○○kW | 専用回路が必要かどうか |
| 処理能力 | ○○ 個/分 など | 生産タクトに影響 |
| 精度 | ±○○mm など | 品質要求と照合 |

### 3. 機能詳細
主要機能、安全機能、制御・通信、駆動系について記載

### 4. 運用条件
使用環境温度、湿度、設置環境、騒音レベルなど

### 5. 設置要件
床面・基礎、ユーティリティ、必要スペース

### 6. メンテナンス
日常点検、定期保守、トラブル対応

### 7. 関連規格・法規制
安全規格、品質・環境規格、法的要求事項

### 8. コスト情報
設備本体価格、設置工事費、年間ランニングコスト

### 9. 付属品・オプション
標準付属品、オプション品、推奨予備品

### 10. 導入スケジュール
発注～製造、搬入・据付、試運転、立ち上げ

### 11. 教育・トレーニング
操作トレーニング、メンテナンストレーニング、安全教育

""",

    'QUERY_SUPPORT': """【回答形式のガイドライン】
以下の方針で回答してください:

- ユーザーが指定した形式 (箇条書き、レポート形式など) で回答
- 指定がない場合はプレーンテキスト形式の箇条書きで回答
- 検索結果が0件の場合は「該当する情報が見つかりませんでした」と正直に伝える

【回答時の注意事項】
- 不確実な情報には「参考情報」と明記
- 安全性に関わる事項は特に慎重に記載
"""
}


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal types from DynamoDB"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return int(obj) if obj == int(obj) else float(obj)
        return super().default(obj)


def json_response(status_code, body):
    """Create a standardized API response"""
    return {
        'statusCode': status_code,
        'headers': CORS_HEADERS,
        'body': json.dumps(body, cls=DecimalEncoder, ensure_ascii=False)
    }


def _auto_initialize_defaults():
    """
    Auto-initialize default templates if the table is empty.
    Called once per Lambda cold start. Checks a global flag to avoid
    repeated DynamoDB queries on warm invocations.
    """
    global _defaults_initialized
    if _defaults_initialized:
        return

    try:
        # Quick check: scan with limit 1 to see if table has any items
        response = prompt_table.scan(Limit=1)
        if response.get('Count', 0) == 0:
            logger.info('DynamoDB table is empty. Initializing default templates...')
            initialize_default_templates()
        else:
            logger.info('DynamoDB table already has data. Skipping initialization.')
        _defaults_initialized = True
    except Exception as e:
        logger.error(f'Error during auto-initialization check: {e}')
        # Don't set flag so it retries on next invocation
        _defaults_initialized = True


def lambda_handler(event, context):
    """
    Main entry point for prompt template management API
    """
    logger.info(f"Event: {json.dumps(event)}")

    if not prompt_table:
        return json_response(500, {'error': 'DYNAMODB_PROMPT_TEMPLATES_TABLE not configured'})

    # Auto-initialize default templates on first invocation
    _auto_initialize_defaults()

    http_method = event.get('httpMethod', '')
    path = event.get('path', '')

    # Handle OPTIONS (CORS preflight)
    if http_method == 'OPTIONS':
        return json_response(200, {'message': 'OK'})

    try:
        if http_method == 'GET':
            return handle_get(event)
        elif http_method == 'POST':
            return handle_create(event)
        elif http_method == 'PUT':
            return handle_update(event)
        elif http_method == 'DELETE':
            return handle_delete(event)
        else:
            return json_response(405, {'error': f'Method not allowed: {http_method}'})
    except Exception as e:
        logger.error(f"Error handling request: {e}", exc_info=True)
        return json_response(500, {'error': 'Internal server error', 'message': str(e)})


def handle_get(event):
    """
    GET /api/prompt-templates?agentType=VERIFICATION
    GET /api/prompt-templates?agentType=VERIFICATION&templateId=xxx
    """
    params = event.get('queryStringParameters') or {}
    agent_type = params.get('agentType', '').upper()

    if not agent_type:
        return json_response(400, {'error': 'agentType is required'})

    if agent_type not in VALID_AGENT_TYPES:
        return json_response(400, {'error': f'Invalid agentType. Must be one of: {VALID_AGENT_TYPES}'})

    # Return specific template
    template_id = params.get('templateId', '')
    if template_id:
        return get_single_template(agent_type, template_id)

    # Return all templates for agent type
    return get_all_templates(agent_type)


def get_single_template(agent_type, template_id):
    """Get a single template by agentType and templateId"""
    try:
        response = prompt_table.get_item(
            Key={
                'agentType': agent_type,
                'templateId': template_id
            }
        )

        item = response.get('Item')
        if not item:
            return json_response(404, {'error': 'Template not found'})

        return json_response(200, item)
    except ClientError as e:
        logger.error(f"Error getting template: {e}")
        return json_response(500, {'error': str(e)})


def get_all_templates(agent_type):
    """Get all templates for a given agent type"""
    try:
        response = prompt_table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key('agentType').eq(agent_type)
        )

        items = response.get('Items', [])

        # Sort by updatedAt descending
        items.sort(key=lambda x: x.get('updatedAt', 0), reverse=True)

        return json_response(200, {
            'agentType': agent_type,
            'templates': items,
            'count': len(items)
        })
    except ClientError as e:
        logger.error(f"Error listing templates: {e}")
        return json_response(500, {'error': str(e)})


def handle_create(event):
    """
    POST /api/prompt-templates
    Body: {agentType, name, description, editablePrompt, isDefault}
    """
    try:
        body = json.loads(event.get('body', '{}'))
    except json.JSONDecodeError:
        return json_response(400, {'error': 'Invalid JSON body'})

    agent_type = body.get('agentType', '').upper()
    name = body.get('name', '').strip()
    description = body.get('description', '').strip()
    editable_prompt = body.get('editablePrompt', '').strip()
    is_default = body.get('isDefault', False)

    # Validation
    if not agent_type or agent_type not in VALID_AGENT_TYPES:
        return json_response(400, {'error': f'Invalid agentType. Must be one of: {VALID_AGENT_TYPES}'})

    if not name:
        return json_response(400, {'error': 'name is required'})

    if not editable_prompt:
        return json_response(400, {'error': 'editablePrompt is required'})

    # Generate template ID
    now = datetime.now(JST)
    template_id = f"tmpl-{now.strftime('%Y%m%d%H%M%S')}-{str(uuid.uuid4())[:8]}"
    timestamp = int(now.timestamp())

    # If setting as default, unset current default
    if is_default:
        _unset_current_default(agent_type)

    # Create item
    item = {
        'agentType': agent_type,
        'templateId': template_id,
        'name': name,
        'description': description,
        'editablePrompt': editable_prompt,
        'isDefault': is_default,
        'version': 1,
        'createdAt': timestamp,
        'updatedAt': timestamp
    }

    try:
        prompt_table.put_item(Item=item)
        logger.info(f"Created template: {template_id} for {agent_type}")
        return json_response(201, item)
    except ClientError as e:
        logger.error(f"Error creating template: {e}")
        return json_response(500, {'error': str(e)})


def handle_update(event):
    """
    PUT /api/prompt-templates
    Body: {agentType, templateId, name, description, editablePrompt, isDefault}
    """
    try:
        body = json.loads(event.get('body', '{}'))
    except json.JSONDecodeError:
        return json_response(400, {'error': 'Invalid JSON body'})

    agent_type = body.get('agentType', '').upper()
    template_id = body.get('templateId', '').strip()

    if not agent_type or not template_id:
        return json_response(400, {'error': 'agentType and templateId are required'})

    # Check if template exists
    try:
        response = prompt_table.get_item(
            Key={'agentType': agent_type, 'templateId': template_id}
        )
        if 'Item' not in response:
            return json_response(404, {'error': 'Template not found'})
    except ClientError as e:
        return json_response(500, {'error': str(e)})

    existing = response['Item']
    now = datetime.now(JST)
    timestamp = int(now.timestamp())

    # Build update expression
    name = body.get('name', existing.get('name', ''))
    description = body.get('description', existing.get('description', ''))
    editable_prompt = body.get('editablePrompt', existing.get('editablePrompt', ''))
    is_default = body.get('isDefault', existing.get('isDefault', False))
    version = existing.get('version', 0) + 1

    # If setting as default, unset current default
    if is_default and not existing.get('isDefault', False):
        _unset_current_default(agent_type)

    try:
        prompt_table.update_item(
            Key={'agentType': agent_type, 'templateId': template_id},
            UpdateExpression='SET #n = :name, description = :desc, editablePrompt = :prompt, isDefault = :default, version = :ver, updatedAt = :ts',
            ExpressionAttributeNames={'#n': 'name'},
            ExpressionAttributeValues={
                ':name': name,
                ':desc': description,
                ':prompt': editable_prompt,
                ':default': is_default,
                ':ver': version,
                ':ts': timestamp
            }
        )

        updated_item = {
            'agentType': agent_type,
            'templateId': template_id,
            'name': name,
            'description': description,
            'editablePrompt': editable_prompt,
            'isDefault': is_default,
            'version': version,
            'createdAt': existing.get('createdAt', 0),
            'updatedAt': timestamp
        }

        logger.info(f"Updated template: {template_id} for {agent_type}")
        return json_response(200, updated_item)
    except ClientError as e:
        logger.error(f"Error updating template: {e}")
        return json_response(500, {'error': str(e)})


def handle_delete(event):
    """
    DELETE /api/prompt-templates?agentType=xxx&templateId=yyy
    """
    params = event.get('queryStringParameters') or {}
    agent_type = params.get('agentType', '').upper()
    template_id = params.get('templateId', '')

    if not agent_type or not template_id:
        return json_response(400, {'error': 'agentType and templateId are required'})

    try:
        # Check if exists
        response = prompt_table.get_item(
            Key={'agentType': agent_type, 'templateId': template_id}
        )
        if 'Item' not in response:
            return json_response(404, {'error': 'Template not found'})

        prompt_table.delete_item(
            Key={'agentType': agent_type, 'templateId': template_id}
        )

        logger.info(f"Deleted template: {template_id} for {agent_type}")
        return json_response(200, {'message': 'Template deleted successfully'})
    except ClientError as e:
        logger.error(f"Error deleting template: {e}")
        return json_response(500, {'error': str(e)})


def _unset_current_default(agent_type):
    """Unset the current default template for a given agent type"""
    try:
        response = prompt_table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key('agentType').eq(agent_type),
            FilterExpression=boto3.dynamodb.conditions.Attr('isDefault').eq(True)
        )

        for item in response.get('Items', []):
            prompt_table.update_item(
                Key={
                    'agentType': item['agentType'],
                    'templateId': item['templateId']
                },
                UpdateExpression='SET isDefault = :val',
                ExpressionAttributeValues={':val': False}
            )
            logger.info(f"Unset default for template: {item['templateId']}")
    except ClientError as e:
        logger.error(f"Error unsetting default: {e}")


def initialize_default_templates():
    """
    Initialize default templates for all agent types.
    Called externally or via a one-time setup.
    """
    for agent_type in VALID_AGENT_TYPES:
        template_id = f"default-{agent_type.lower()}"
        now = datetime.now(JST)
        timestamp = int(now.timestamp())

        try:
            # Check if default already exists
            response = prompt_table.get_item(
                Key={'agentType': agent_type, 'templateId': template_id}
            )
            if 'Item' in response:
                logger.info(f"Default template already exists for {agent_type}")
                continue

            item = {
                'agentType': agent_type,
                'templateId': template_id,
                'name': f'{agent_type} デフォルト',
                'description': f'{agent_type} のデフォルトテンプレート',
                'editablePrompt': DEFAULT_EDITABLE_PROMPTS.get(agent_type, ''),
                'isDefault': True,
                'version': 1,
                'createdAt': timestamp,
                'updatedAt': timestamp
            }

            prompt_table.put_item(Item=item)
            logger.info(f"Created default template for {agent_type}: {template_id}")
        except ClientError as e:
            logger.error(f"Error creating default template for {agent_type}: {e}")
