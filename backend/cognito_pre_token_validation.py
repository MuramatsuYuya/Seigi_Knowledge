"""
Cognito Pre-token Generation Validation Lambda

メールドメイン(@ad.melco.co.jp)をチェックする関数
AWS Lambda が呼び出すコード

CloudFormation: Lambda関数をアップロードしてから、
PreTokenGenerationトリガーを設定してください
"""

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# メールドメイン許可リスト
ALLOWED_EMAIL_DOMAIN = '@ad.melco.co.jp'


def lambda_handler(event, context):
    """
    Cognito Pre-token Generation トリガー
    ユーザーメールのドメイン制限を検証
    
    イベント例:
    {
        'request': {
            'userAttributes': {
                'email': 'user@ad.melco.co.jp',
                'email_verified': 'true'
            }
        }
    }
    """
    print(f'Event: {json.dumps(event)}')
    
    try:
        # ユーザーのメールアドレスを取得
        user_attributes = event['request'].get('userAttributes', {})
        user_email = user_attributes.get('email', '')
        
        logger.info(f'Validating email: {user_email}')
        
        # メールドメイン検証
        if not user_email.endswith(ALLOWED_EMAIL_DOMAIN):
            logger.warning(f'Email domain not allowed: {user_email}')
            # エラーをthrowすると、トークン生成前に拒否される
            raise Exception(f'メールドメインが許可されていません。{ALLOWED_EMAIL_DOMAIN} を使用してください')
        
        logger.info(f'Email validation passed: {user_email}')
        
        # イベントを返す（変更なし）
        return event
        
    except Exception as e:
        logger.error(f'Validation error: {str(e)}')
        raise
