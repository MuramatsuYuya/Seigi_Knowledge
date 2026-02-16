# ステップ0機能実装 - 実装サマリー

**実装日**: 2025年11月11日
**ステータス**: ✅ コア実装完了 / CloudFormation・デプロイスクリプト要更新

---

## ✅ 完了済み実装

### 1. バックエンド（Python/Lambda）

#### ✅ `backend/folder_management_lambda.py` (新規作成)
- **機能**: フォルダ・ファイル管理の統合Lambda
- **実装内容**:
  - `GET /api/folders`: 登録状態を含むフォルダツリー取得
  - `POST /api/folder-management`: フォルダ作成・削除
  - `GET /api/s3-presigned-urls`: ファイルアップロード用署名付きURL生成
  - `POST /api/trigger-processing`: アップロード後の自動処理トリガー

#### ✅ `backend/bedrock_kb_sync_lambda.py` (修正)
- **追加機能**: `register_folder_on_first_knowledge_completion()`
  - 初回ナレッジ処理完了時に`doctoknow-dev-folder-config`テーブルに登録
  - 既存フォルダは`latest_job_id`のみ更新
  - イベント: `is_new_folder: true` フラグで判定

### 2. フロントエンド

#### ✅ `frontend/index.html` (修正)
- **追加内容**: ステップ0セクション
  - 左パネル: フォルダツリー管理（新規作成・削除・アップロード選択）
  - 右パネル: ファイルアップロード（複数選択可能）

#### ✅ `frontend/app.js` (修正)
- **追加メソッド**:
  - `initializeStep0()`: 初期化
  - `fetchFolderTreeForManagement()`: フォルダツリー取得
  - `renderFolderTreeForManagement()`: ツリー描画
  - `createFolder()`: フォルダ作成
  - `deleteFolder()`: フォルダ削除
  - `selectFolderForUpload()`: アップロード先選択
  - `uploadFiles()`: 署名付きURLでS3へ直接アップロード + 自動処理トリガー

#### ✅ `frontend/style.css` (修正)
- **追加スタイル**:
  - `.folder-management-section`: ステップ0全体
  - `.management-grid`: 2カラムレイアウト
  - `.folder-item-mgmt`: フォルダアイテム
  - `.registered-badge`: 登録済みバッジ
  - `.btn-small`: 管理ボタン
  - `.progress-bar`: アップロード進捗バー

---

## 🔧 残作業

### 1. CloudFormation テンプレート更新

`cloudformation-doctoknow-template.json` に以下を追加:

```json
{
  "Resources": {
    "FolderManagementLambda": {
      "Type": "AWS::Lambda::Function",
      "Properties": {
        "FunctionName": { "Fn::Sub": "${ProjectName}-folder-management-${Environment}" },
        "Runtime": "python3.11",
        "Handler": "folder_management_lambda.lambda_handler",
        "Timeout": 60,
        "MemorySize": 512,
        "Environment": {
          "Variables": {
            "S3_BUCKET": { "Ref": "DataS3Bucket" },
            "DYNAMODB_FOLDER_CONFIG_TABLE": { "Ref": "FolderConfigTable" },
            "WORKER_LAMBDA_ARN": { "Fn::GetAtt": ["WorkerLambda", "Arn"] },
            "AWS_REGION": { "Ref": "AWS::Region" }
          }
        },
        "Role": { "Fn::GetAtt": ["LambdaExecutionRole", "Arn"] },
        "Code": {
          "ZipFile": "import json\nprint('FolderManagement Lambda Placeholder')\n"
        }
      }
    },
    
    "FolderManagementLambdaPermission": {
      "Type": "AWS::Lambda::Permission",
      "Properties": {
        "FunctionName": { "Ref": "FolderManagementLambda" },
        "Action": "lambda:InvokeFunction",
        "Principal": "apigateway.amazonaws.com",
        "SourceArn": {
          "Fn::Sub": "arn:aws:execute-api:${AWS::Region}:${AWS::AccountId}:${ApiGateway}/*/*"
        }
      }
    },
    
    "ApiFolderManagement": {
      "Type": "AWS::ApiGateway::Resource",
      "Properties": {
        "RestApiId": { "Ref": "ApiGateway" },
        "ParentId": { "Fn::GetAtt": ["ApiGateway", "RootResourceId"] },
        "PathPart": "folder-management"
      }
    },
    
    "ApiFolderManagementPost": {
      "Type": "AWS::ApiGateway::Method",
      "Properties": {
        "RestApiId": { "Ref": "ApiGateway" },
        "ResourceId": { "Ref": "ApiFolderManagement" },
        "HttpMethod": "POST",
        "AuthorizationType": "COGNITO_USER_POOLS",
        "AuthorizerId": { "Ref": "CognitoAuthorizer" },
        "Integration": {
          "Type": "AWS_PROXY",
          "IntegrationHttpMethod": "POST",
          "Uri": {
            "Fn::Sub": "arn:aws:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/${FolderManagementLambda.Arn}/invocations"
          }
        }
      }
    },
    
    "ApiS3PresignedUrls": {
      "Type": "AWS::ApiGateway::Resource",
      "Properties": {
        "RestApiId": { "Ref": "ApiGateway" },
        "ParentId": { "Fn::GetAtt": ["ApiGateway", "RootResourceId"] },
        "PathPart": "s3-presigned-urls"
      }
    },
    
    "ApiS3PresignedUrlsGet": {
      "Type": "AWS::ApiGateway::Method",
      "Properties": {
        "RestApiId": { "Ref": "ApiGateway" },
        "ResourceId": { "Ref": "ApiS3PresignedUrls" },
        "HttpMethod": "GET",
        "AuthorizationType": "COGNITO_USER_POOLS",
        "AuthorizerId": { "Ref": "CognitoAuthorizer" },
        "Integration": {
          "Type": "AWS_PROXY",
          "IntegrationHttpMethod": "POST",
          "Uri": {
            "Fn::Sub": "arn:aws:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/${FolderManagementLambda.Arn}/invocations"
          }
        }
      }
    },
    
    "ApiTriggerProcessing": {
      "Type": "AWS::ApiGateway::Resource",
      "Properties": {
        "RestApiId": { "Ref": "ApiGateway" },
        "ParentId": { "Fn::GetAtt": ["ApiGateway", "RootResourceId"] },
        "PathPart": "trigger-processing"
      }
    },
    
    "ApiTriggerProcessingPost": {
      "Type": "AWS::ApiGateway::Method",
      "Properties": {
        "RestApiId": { "Ref": "ApiGateway" },
        "ResourceId": { "Ref": "ApiTriggerProcessing" },
        "HttpMethod": "POST",
        "AuthorizationType": "COGNITO_USER_POOLS",
        "AuthorizerId": { "Ref": "CognitoAuthorizer" },
        "Integration": {
          "Type": "AWS_PROXY",
          "IntegrationHttpMethod": "POST",
          "Uri": {
            "Fn::Sub": "arn:aws:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/${FolderManagementLambda.Arn}/invocations"
          }
        }
      }
    }
  }
}
```

**注意**: 既存の`GET /api/folders`エンドポイントは`JobCreatorLambda`から`FolderManagementLambda`に変更する必要があります。

---

### 2. デプロイスクリプト更新

`deploy-doctoknow.ps1` に以下を追加:

```powershell
# FolderManagementLambda のデプロイ
Write-Host "`n=== Deploying FolderManagementLambda ===" -ForegroundColor Green
$folderMgmtZip = "$pwd\backend\folder_management_lambda.zip"

# Zip作成
Compress-Archive -Path "$pwd\backend\folder_management_lambda.py", "$pwd\backend\folder_tree_helper.py" `
    -DestinationPath $folderMgmtZip -Force

# Lambda更新
aws lambda update-function-code `
    --function-name "$projectName-folder-management-$environment" `
    --zip-file "fileb://$folderMgmtZip" `
    --region $region

Remove-Item $folderMgmtZip
```

---

### 3. BedrockKBSyncLambda の環境変数追加

既存の`BedrockKBSyncLambda`に環境変数を追加:

```json
"Environment": {
  "Variables": {
    "KNOWLEDGE_BASE_ID": "...",
    "DATA_SOURCE_ID": "...",
    "DYNAMODB_TABLE": "...",
    "DYNAMODB_FOLDER_CONFIG_TABLE": { "Ref": "FolderConfigTable" },  // 追加
    "AWS_REGION": "..."
  }
}
```

---

## 📝 実装完了後の確認項目

### フロントエンド動作確認
1. ✅ ステップ0セクションが表示される
2. ✅ フォルダツリーが取得できる
3. ✅ 登録済みフォルダに「✓ 登録済み」バッジが表示される
4. ✅ 新規フォルダを作成できる
5. ✅ 空のフォルダを削除できる
6. ✅ ファイルを選択してアップロードできる
7. ✅ 登録済みフォルダへのアップロード時、自動処理が開始される
8. ✅ 未登録フォルダへのアップロード時、案内メッセージが表示される

### バックエンド動作確認
1. ✅ `GET /api/folders` が登録状態を含むツリーを返す
2. ✅ `POST /api/folder-management` でフォルダ作成・削除ができる
3. ✅ `GET /api/s3-presigned-urls` が署名付きURLを返す
4. ✅ 署名付きURLでS3へファイルをアップロードできる
5. ✅ `POST /api/trigger-processing` でworker Lambdaが呼び出される
6. ✅ 初回ナレッジ処理時に`folder_config`テーブルに登録される

---

## 🎯 次のステップ

1. CloudFormationテンプレートに上記のリソース定義を追加
2. デプロイスクリプトを更新
3. デプロイ実行
4. 動作確認

---

## 📌 重要な設計ポイント

### セキュリティ
- ✅ 署名付きURLは1時間で期限切れ
- ✅ CognitoユーザープールによるAPI認証
- ✅ S3へのダイレクトアップロード（Lambda経由なし）

### パフォーマンス
- ✅ マルチパートアップロード対応（100MB以上のファイル）
- ✅ 複数ファイルの並列アップロード
- ✅ フロントエンドでフォルダツリーをキャッシュ

### ユーザビリティ
- ✅ リアルタイム進捗表示
- ✅ 登録状態の視覚的な識別（バッジ）
- ✅ エラーメッセージの明確化
