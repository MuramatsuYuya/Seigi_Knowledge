# マルチモード実装ガイド - 検証計画・仕様書作成機能

## 概要

本ドキュメントでは、既存のAI質問システムに「検証計画作成」「仕様書作成」の2つの新規モードを追加した実装について説明します。

**実装日**: 2026年2月9日  
**対象システム**: DoctorKnow - 生技ナレッジAI  

---

## アーキテクチャ設計

### システム全体構成

```
┌─────────────────────────────────────────────────┐
│          フロントエンド (S3 + CloudFront)        │
├─────────────────────────────────────────────────┤
│ ● index.html         - PDF処理・ナレッジ化      │
│ ● knowledge-query.html - AI質問（既存）         │
│ ● verification-plan.html - 検証計画作成（NEW）   │
│ ● specification.html - 仕様書作成（NEW）         │
└─────────────────────────────────────────────────┘
                        ↓ HTTPS
┌─────────────────────────────────────────────────┐
│        API Gateway + Lambda (バックエンド)       │
├─────────────────────────────────────────────────┤
│ ● start_query_lambda.py                         │
│ ● knowledge_querier.py (agent_type対応)         │
│ ● agent_kb_action.py                            │
└─────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────┐
│            AWS Bedrock Agent (3つ)              │
├─────────────────────────────────────────────────┤
│ ① Default Agent    - 汎用質問                   │
│ ② Verification Agent - 検証計画作成            │
│ ③ Specification Agent - 仕様書作成             │
└─────────────────────────────────────────────────┘
                        ↓
         Knowledge Base (共通・QBRNP5FY8E)
```

### モード切り替えの仕組み

各モードは独立したHTMLページとして実装し、異なるBedrock Agentを使用します。

| ページ | HTML | JS | Agent Type | Session ID Prefix |
|--------|------|----|-----------|--------------------|
| AI質問 | knowledge-query.html | knowledge-query.js | `default` | なし |
| 検証計画 | verification-plan.html | verification-plan.js | `verification` | `verification_` |
| 仕様書 | specification.html | specification.js | `specification` | `specification_` |

**ポイント**:
- モード別にチャット履歴を分離（session_idのプレフィックスで区別）
- 各モードは専用のAgentを呼び出す（agent_typeパラメータで指定）
- 検索対象（フォルダ選択）は共通の仕組みを利用

---

## 実装詳細

### 1. フロントエンド

#### 1.1 新規ページ作成

**verification-plan.html**
- knowledge-query.htmlをベースに作成
- タイトルを「検証計画作成」に変更
- Help文を検証計画用に調整
- Settings モーダルは非表示（Agent利用固定）

**specification.html**
- verification-plan.htmlをコピーして作成
- タイトルを「仕様書作成」に変更
- プレースホルダーテキストを仕様書用に調整

#### 1.2 JavaScript実装

**verification-plan.js**
```javascript
class KnowledgeQueryApp {
    constructor(config = {}) {
        this.agentType = 'verification';  // NEW
        this.useAgent = true;  // 固定
        // ...
    }
    
    initializeChatSession() {
        let sessionId = sessionStorage.getItem('verificationPlanSessionId');
        if (!sessionId) {
            sessionId = 'verification_' + generateUUID();  // プレフィックス追加
            // ...
        }
    }
    
    initializeAuthManager() {
        // window.verificationPlanAuthManager を参照
    }
    
    submitQuery() {
        const requestBody = {
            // ...
            agent_type: this.agentType  // NEW: agent_typeを送信
        };
    }
}
```

**specification.js**
- `agentType = 'specification'`
- `session_id` プレフィックス: `specification_`
- `window.specificationAuthManager` を参照

#### 1.3 ナビゲーション更新

**index.html, knowledge-query.html, verification-plan.html, specification.html**

全ページで共通のナビゲーションバーを追加:

```html
<button class="nav-tab" data-page="index">📄 技術資料のナレッジ化</button>
<button class="nav-tab" data-page="knowledge-query">🔍 AI質問</button>
<button class="nav-tab" data-page="verification-plan">📋 検証計画</button>
<button class="nav-tab" data-page="specification">📖 仕様書</button>
```

**app.js**

```javascript
switchPage(pageName) {
    if (pageName === 'knowledge-query') {
        window.location.href = 'knowledge-query.html';
        return;
    }
    if (pageName === 'verification-plan') {
        window.location.href = 'verification-plan.html';
        return;
    }
    if (pageName === 'specification') {
        window.location.href = 'specification.html';
        return;
    }
    // ...
}
```

---

### 2. バックエンド

#### 2.1 start_query_lambda.py

**変更点**: `agent_type`パラメータを受け取り、KnowledgeQuerierLambdaに渡す

```python
def lambda_handler(event, context):
    body = json.loads(event['body'])
    
    # NEW: agent_typeパラメータを追加
    agent_type = body.get('agent_type', 'default')
    
    # DynamoDBに保存
    query_status_table.put_item(Item={
        # ...
        'agent_type': agent_type,
    })
    
    # KnowledgeQuerierLambdaに渡す
    querier_payload = {
        # ...
        'agent_type': agent_type
    }
```

#### 2.2 knowledge_querier.py

**環境変数追加**:
```python
BEDROCK_AGENT_ID = os.environ.get("BEDROCK_AGENT_ID", "M89ZN5FKB4")
BEDROCK_AGENT_ALIAS_ID = os.environ.get("BEDROCK_AGENT_ALIAS_ID", "TSTALIASID")
VERIFICATION_AGENT_ID = os.environ.get("VERIFICATION_AGENT_ID", "")
VERIFICATION_AGENT_ALIAS_ID = os.environ.get("VERIFICATION_AGENT_ALIAS_ID", "")
SPECIFICATION_AGENT_ID = os.environ.get("SPECIFICATION_AGENT_ID", "")
SPECIFICATION_AGENT_ALIAS_ID = os.environ.get("SPECIFICATION_AGENT_ALIAS_ID", "")
```

**invoke_agent_with_filter関数の更新**:
```python
def invoke_agent_with_filter(query, folder_path_job_id_pairs, session_id, agent_type='default'):
    # agent_typeに応じてAgent IDを切り替え
    if agent_type == 'verification':
        agent_id = VERIFICATION_AGENT_ID or BEDROCK_AGENT_ID
        agent_alias_id = VERIFICATION_AGENT_ALIAS_ID or BEDROCK_AGENT_ALIAS_ID
    elif agent_type == 'specification':
        agent_id = SPECIFICATION_AGENT_ID or BEDROCK_AGENT_ID
        agent_alias_id = SPECIFICATION_AGENT_ALIAS_ID or BEDROCK_AGENT_ALIAS_ID
    else:
        agent_id = BEDROCK_AGENT_ID
        agent_alias_id = BEDROCK_AGENT_ALIAS_ID
    
    # Agent呼び出し
    response = bedrock_agent.invoke_agent(
        agentId=agent_id,
        agentAliasId=agent_alias_id,
        # ...
    )
```

**handle_sync_query / handle_async_query の更新**:
```python
def handle_async_query(event, query_id):
    agent_type = event.get('agent_type', 'default')
    # ...
    answer, sources = invoke_agent_with_filter(query, folder_path_job_id_pairs, chat_session_id, agent_type)
```

---

### 3. CloudFormation

#### 3.1 環境変数追加

**KnowledgeQuerierLambda**:
```json
"Environment": {
  "Variables": {
    "BEDROCK_AGENT_ID": "M89ZN5FKB4",
    "BEDROCK_AGENT_ALIAS_ID": "HZHJZIHUHR",
    "VERIFICATION_AGENT_ID": "PLACEHOLDER_VERIFICATION_AGENT_ID",
    "VERIFICATION_AGENT_ALIAS_ID": "PLACEHOLDER_VERIFICATION_ALIAS_ID",
    "SPECIFICATION_AGENT_ID": "PLACEHOLDER_SPECIFICATION_AGENT_ID",
    "SPECIFICATION_AGENT_ALIAS_ID": "PLACEHOLDER_SPECIFICATION_ALIAS_ID"
  }
}
```

**注**: PLACEHOLDERは、Agent作成後に手動で更新する必要があります。

#### 3.2 Lambda Permission追加

```json
"AgentKBActionLambdaVerificationPermission": {
  "Type": "AWS::Lambda::Permission",
  "Properties": {
    "FunctionName": {"Ref": "AgentKBActionLambda"},
    "Action": "lambda:InvokeFunction",
    "Principal": "bedrock.amazonaws.com",
    "SourceArn": "arn:aws:bedrock:us-west-2:722631436454:agent/*"
  }
},
"AgentKBActionLambdaSpecificationPermission": {/* 同様 */}
```

**注**: ワイルドカード（`agent/*`）を使用して、将来的な新規Agentにも対応。

---

## デプロイ手順

### ステップ1: フロントエンドのデプロイ

```powershell
# S3バケットに新規ファイルをアップロード
aws s3 cp frontend/verification-plan.html s3://doctoknow-seigi25-data/frontend/
aws s3 cp frontend/verification-plan.js s3://doctoknow-seigi25-data/frontend/
aws s3 cp frontend/specification.html s3://doctoknow-seigi25-data/frontend/
aws s3 cp frontend/specification.js s3://doctoknow-seigi25-data/frontend/

# 既存ファイルを更新
aws s3 cp frontend/index.html s3://doctoknow-seigi25-data/frontend/
aws s3 cp frontend/knowledge-query.html s3://doctoknow-seigi25-data/frontend/
aws s3 cp frontend/app.js s3://doctoknow-seigi25-data/frontend/

# CloudFrontキャッシュ無効化
aws cloudfront create-invalidation --distribution-id YOUR_DISTRIBUTION_ID --paths "/*"
```

### ステップ2: バックエンドのデプロイ

```powershell
# CloudFormationスタック更新
.\deploy-doctoknow.ps1
```

### ステップ3: Bedrock Agent作成

#### 3.1 検証計画作成Agent

1. AWS Bedrock コンソールで新しいAgentを作成
   - Agent名: `agent-doctoknow-verification`
   - Model: Claude 3.5 Sonnet
   - Instructions: [Verification_Agent_Instructions.md](Verification_Agent_Instructions.md) の内容を設定

2. Action Groupを追加
   - Lambda: `doctoknow-agent-kb-action-v0`
   - Function: `search_knowledge_base`

3. Prepare → Test → Create Alias
   - Alias名: `production`
   - Agent ID と Alias ID をメモ

#### 3.2 仕様書作成Agent

1. 同様に新しいAgentを作成
   - Agent名: `agent-doctoknow-specification`
   - Instructions: [Specification_Agent_Instructions.md](Specification_Agent_Instructions.md) の内容を設定

2. Action Group追加 → Prepare → Alias作成
   - Agent ID と Alias ID をメモ

### ステップ4: Lambda環境変数の更新

AWS Lambda コンソールで `doctoknow-knowledge-querier` の環境変数を更新:

```
VERIFICATION_AGENT_ID = [手順3.1で取得したAgent ID]
VERIFICATION_AGENT_ALIAS_ID = [手順3.1で取得したAlias ID]
SPECIFICATION_AGENT_ID = [手順3.2で取得したAgent ID]
SPECIFICATION_AGENT_ALIAS_ID = [手順3.2で取得したAlias ID]
```

**手動更新の理由**: CloudFormationでAgent自体は作成できないため、手動で作成後に環境変数を更新する必要があります。

---

## テスト

### 動作確認手順

1. **各ページへのアクセス**
   - `https://your-domain.com/verification-plan.html`
   - `https://your-domain.com/specification.html`
   - 認証が正常に動作することを確認

2. **ナビゲーション**
   - 各ページ間の遷移が正常に動作することを確認
   - ナビゲーションバーのアクティブ表示が正しいことを確認

3. **検証計画作成**
   - フォルダを選択
   - 「新しいロボットアームの導入に向けた検証計画を立てたい」と入力
   - 検証計画形式の回答が返ってくることを確認

4. **仕様書作成**
   - フォルダを選択
   - 「産業用ロボットの仕様書を作成してほしい」と入力
   - 仕様書形式の回答が返ってくることを確認

5. **チャット履歴の分離**
   - 各モードで質問を投稿
   - ブラウザ開発者ツールでsessionStorageを確認
   - `chatSessionId`, `verificationPlanSessionId`, `specificationSessionId` が別々に保存されていることを確認

6. **CloudWatch Logs確認**
   - `doctoknow-knowledge-querier` のログを確認
   - `agent_type` が正しく渡されていることを確認
   - 正しいAgent IDが使用されていることを確認

---

## トラブルシューティング

### 問題: 新しいページにアクセスすると認証エラー

**原因**: auth.jsの初期化タイミングの問題

**対策**:
- HTMLファイルのスクリプトタグの順序を確認
- `window.verificationPlanAuthManager` / `window.specificationAuthManager` が正しくグローバル変数に設定されているか確認

### 問題: Agent が呼び出されない

**原因**: 環境変数の未設定またはPermission不足

**対策**:
1. Lambda環境変数を確認
   ```bash
   aws lambda get-function-configuration --function-name doctoknow-knowledge-querier | grep AGENT
   ```

2. Lambda Permissionを確認
   ```bash
   aws lambda get-policy --function-name doctoknow-agent-kb-action-v0
   ```

### 問題: 検証計画・仕様書の形式が期待と異なる

**原因**: Agent Instructions の記述不足

**対策**:
- AWS Bedrock Agent コンソールでInstructionsを更新
- より具体的な出力例を追加
- Prepareして再テスト

---

## 今後の拡張性

### 新しいモードの追加

本実装パターンに従えば、容易に新しいモードを追加できます:

1. **新規HTMLとJSファイル作成**
   - 既存のverification-plan.htmlをコピー
   - `agentType`、`session_id`プレフィックスを変更

2. **新しいBedrock Agentを作成**
   - 専用のInstructionsを設定
   - Action Groupは既存のものを再利用

3. **環境変数とPermissionを追加**
   - CloudFormationテンプレート更新
   - Lambda環境変数に新しいAgent IDを追加

### モード共通機能の改善

- **テンプレート機能**: よく使う質問をテンプレート化
- **エクスポート機能**: 生成された文書をPDF/Wordでダウンロード
- **承認ワークフロー**: 生成した文書をレビュー・承認する機能

---

## 参考資料

- [Verification_Agent_Instructions.md](Verification_Agent_Instructions.md) - 検証計画Agent設定
- [Specification_Agent_Instructions.md](Specification_Agent_Instructions.md) - 仕様書Agent設定
- [Agent_Instructions_最終版.md](Agent_Instructions_最終版.md) - デフォルトAgent設定
- [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) - システム全体実装概要
