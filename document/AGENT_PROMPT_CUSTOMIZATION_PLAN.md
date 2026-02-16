# Agentプロンプトカスタマイズ実装計画書

**作成日**: 2026年2月16日  
**対象**: 検証計画作成Agent、仕様書作成Agent、AI質問支援Agent  
**目標**: DynamoDBでプロンプトテンプレートを管理し、フロントエンドで編集可能にする

---

## 📌 概要

### 現状
- Agentのプロンプトがハードコード化されている（PowerShellスクリプト内）
- プロンプト変更にはスクリプト修正が必要
- Agent作成時にのみプロンプトが反映される

### 目標状態
- **プロンプトテンプレートをDynamoDBで管理**
- **フロントエンドでテンプレート選択・編集**
- **選択したテンプレートを使用してAgent作成**
- **固定部分と編集可能部分を分離**

---

## 🏗️ 技術アーキテクチャ

### 1. **DynamoDB スキーマ設計**

#### テーブル名: `agent-prompt-templates`

```
PK (Partition Key): agentType (String)
  - Values: VERIFICATION | SPECIFICATION | QUERY_SUPPORT

SK (Sort Key): templateId (String)
  - Format: "template-{timestamp}-{randomId}"
  - Example: "template-20260216-abc123"

Attributes:
├── name (String)                    # テンプレート名
│   └── Example: "検証計画 - 標準版"
├── description (String)             # 説明
│   └── Example: "標準的な検証計画作成用テンプレート"
├── isDefault (Boolean)              # デフォルトテンプレートか
├── fixedPrompt (String)             # 固定部分（変更不可）
│   ├── 最重要ルール
│   ├── アクション定義
│   ├── 重要な制約事項
│   └── 対話スタイル
├── editablePrompt (String)          # 編集可能部分
│   ├── 出力形式
│   ├── ワークフロー詳細
│   ├── 品質チェック項目
│   └── その他カスタマイズ可能な部分
├── version (Number)                 # バージョン番号
├── createdAt (Number)               # Unix timestamp
├── updatedAt (Number)               # Unix timestamp
├── createdBy (String)               # 作成ユーザー（Cognito user ID）
├── tags (List)                      # タグ（ex: ["draft", "production"]）
└── metadata (Map)                   # その他メタデータ
    ├── parameterCount: 整数
    └── lastUsedAt: Unix timestamp
```

#### GSI (Global Secondary Index)

**GSI1**: `agentType-isDefault-index`
- PK: `agentType`
- SK: `isDefault`
- 用途: デフォルトテンプレートの高速検索

**GSI2**: `agentType-updatedAt-index`
- PK: `agentType`
- SK: `updatedAt`
- 用途: 最新テンプレートの検索

---

### 2. **プロンプト構造化**

#### 固定部分（変更不可）- すべてのAgentに共通

```
========================================
あなた[Agentの役割]です。

【最重要ルール】
 - 検索が必要な場合、必ずアクショングループの...
 - 検索をした結果、Sourceが見つからなかった場合は...

【役割】
[Agentの基本的な役割説明]

【重要な制約】
- ナレッジベースに存在しない情報を創作しない
- 検索結果に基づいて回答する
- ...

【Action Group】
このAgentは以下のActionを持っています:
- **search_knowledge_base**: ナレッジベースを検索

【対話スタイル】
- [スタイル1]
- [スタイル2]
========================================
```

#### 編集可能部分（テンプレート機能）

**検証計画作成Agent**:
```
【出力形式】
## 検証計画: [設備/技術名]

### 1. 背景と目的
...

【作業フロー】
①ユーザーの入力内容を確認
②ナレッジベースを検索
...
```

**仕様書作成Agent**:
```
【出力形式】
## 設備仕様書: [設備名]

### 1. 概要
...

【作業フロー】
①ユーザーの入力内容を確認
...
```

**AI質問支援Agent**:
```
【最重要ルール】以降の内容全体が編集可能
（ただし search_knowledge_base の使用ルールは固定）
```

---

### 3. **バックエンド API 開発**

#### Lambda 関数: `prompt-management-api`

**エンドポイント設計**:

```
API Gateway → Lambda → DynamoDB

ルート:
  GET    /api/prompts/{agentType}
  GET    /api/prompts/{agentType}/{templateId}
  POST   /api/prompts/{agentType}
  PUT    /api/prompts/{agentType}/{templateId}
  DELETE /api/prompts/{agentType}/{templateId}
  POST   /api/prompts/{agentType}/apply
  GET    /api/prompts/{agentType}/default
```

**実装詳細**:

```python
# prompt_management_lambda.py

import json
import boto3
import os
from datetime import datetime
import uuid
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
bedrock_agent = boto3.client('bedrock-agent')
table = dynamodb.Table(os.environ['PROMPT_TEMPLATES_TABLE'])

def lambda_handler(event, context):
    """
    Main entry point for prompt management API
    
    Routes:
    - GET /prompts/{agentType}
    - GET /prompts/{agentType}/{templateId}
    - POST /prompts/{agentType}
    - PUT /prompts/{agentType}/{templateId}
    - DELETE /prompts/{agentType}/{templateId}
    - POST /prompts/{agentType}/apply
    - GET /prompts/{agentType}/default
    """
    http_method = event['httpMethod']
    path = event['path']
    
    try:
        if http_method == 'GET' and '/apply' not in path:
            return handle_get_templates(event)
        elif http_method == 'POST' and '/apply' in path:
            return handle_apply_template(event)
        elif http_method == 'POST':
            return handle_create_template(event)
        elif http_method == 'PUT':
            return handle_update_template(event)
        elif http_method == 'DELETE':
            return handle_delete_template(event)
        else:
            return error_response(400, 'Invalid method')
    except Exception as e:
        return error_response(500, str(e))

# ... (各ハンドラ関数を実装)
```

---

### 4. **フロントエンド UI 実装**

#### 新規ページ: `prompt-management.html`

```html
<!DOCTYPE html>
<html lang="ja">
<head>
    <title>プロンプト管理 - DoctorKnow</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <div id="container">
        <!-- 管理パネル -->
        <div id="managementPanel">
            <!-- タブ: 検証計画 / 仕様書 / AI質問 -->
            <div class="tab-selector">
                <button class="tab-btn active" data-agent="VERIFICATION">
                    検証計画作成Agent
                </button>
                <button class="tab-btn" data-agent="SPECIFICATION">
                    仕様書作成Agent
                </button>
                <button class="tab-btn" data-agent="QUERY_SUPPORT">
                    AI質問支援Agent
                </button>
            </div>

            <!-- テンプレート選択 -->
            <div class="template-selector">
                <label>テンプレート選択:</label>
                <select id="templateDropdown">
                    <option value="">--- 新規作成 ---</option>
                </select>
                <button id="loadTemplate">読込</button>
                <button id="deleteTemplate">削除</button>
            </div>

            <!-- テンプレート情報 -->
            <div class="template-info">
                <div class="info-row">
                    <label>テンプレート名:</label>
                    <input type="text" id="templateName" placeholder="例: 検証計画 - 標準版">
                </div>
                <div class="info-row">
                    <label>説明:</label>
                    <textarea id="templateDesc" placeholder="このテンプレートの説明"></textarea>
                </div>
                <div class="info-row">
                    <label>
                        <input type="checkbox" id="setDefault">
                        このテンプレートをデフォルトに設定
                    </label>
                </div>
            </div>

            <!-- 固定部分（表示のみ）-->
            <div class="fixed-section">
                <h3>固定部分（変更不可）</h3>
                <div class="prompt-display" id="fixedPromptDisplay">
                    [固定プロンプト内容が表示されます]
                </div>
            </div>

            <!-- 編集可能部分 -->
            <div class="editable-section">
                <h3>編集可能部分</h3>
                <textarea id="editablePrompt" class="prompt-editor" 
                          placeholder="ここで出力形式やワークフロー詳細を編集してください">
                </textarea>
                <div class="char-count">
                    文字数: <span id="charCount">0</span>
                </div>
            </div>

            <!-- 操作ボタン -->
            <div class="action-buttons">
                <button id="previewButton" class="btn-secondary">
                    プレビュー
                </button>
                <button id="saveButton" class="btn-primary">
                    保存
                </button>
                <button id="applyButton" class="btn-success">
                    Agentに適用 (Agent更新)
                </button>
            </div>
        </div>

        <!-- プレビューパネル -->
        <div id="previewPanel" style="display: none;">
            <h3>プレビュー</h3>
            <div id="previewContent" class="prompt-preview"></div>
            <button id="closePreviewButton">閉じる</button>
        </div>
    </div>

    <script src="auth.js"></script>
    <script src="prompt-management.js"></script>
</body>
</html>
```

#### JavaScript: `prompt-management.js`

```javascript
class PromptManagementApp {
    constructor(config = {}) {
        this.apiEndpoint = config.apiEndpoint || '';
        this.currentAgentType = 'VERIFICATION';
        this.currentTemplate = null;
        this.fixedPrompts = {};
        
        this.initializeElements();
        this.attachEventListeners();
        this.loadFixedPrompts();
        this.loadTemplates();
    }

    /**
     * Load templates from backend
     */
    async loadTemplates() {
        try {
            const response = await fetch(
                `${this.apiEndpoint}/api/prompts/${this.currentAgentType}`,
                { headers: { Authorization: this.getAuthToken() } }
            );
            
            const templates = await response.json();
            this.populateDropdown(templates);
        } catch (error) {
            console.error('Error loading templates:', error);
        }
    }

    /**
     * Save template to backend
     */
    async saveTemplate() {
        const template = {
            name: document.getElementById('templateName').value,
            description: document.getElementById('templateDesc').value,
            editablePrompt: document.getElementById('editablePrompt').value,
            isDefault: document.getElementById('setDefault').checked,
            tags: ['custom']
        };

        try {
            const method = this.currentTemplate ? 'PUT' : 'POST';
            const url = this.currentTemplate
                ? `${this.apiEndpoint}/api/prompts/${this.currentAgentType}/${this.currentTemplate.templateId}`
                : `${this.apiEndpoint}/api/prompts/${this.currentAgentType}`;

            const response = await fetch(url, {
                method: method,
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': this.getAuthToken()
                },
                body: JSON.stringify(template)
            });

            if (response.ok) {
                alert('テンプレートを保存しました');
                this.loadTemplates();
            } else {
                alert('保存に失敗しました');
            }
        } catch (error) {
            console.error('Error saving template:', error);
        }
    }

    /**
     * Apply template to Agent (update Agent prompt)
     */
    async applyTemplate() {
        const template = {
            fixedPrompt: this.fixedPrompts[this.currentAgentType],
            editablePrompt: document.getElementById('editablePrompt').value
        };

        try {
            const response = await fetch(
                `${this.apiEndpoint}/api/prompts/${this.currentAgentType}/apply`,
                {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': this.getAuthToken()
                    },
                    body: JSON.stringify(template)
                }
            );

            if (response.ok) {
                alert('Agentを更新しました。新規チャットから新しいプロンプトが適用されます');
            } else {
                alert('適用に失敗しました');
            }
        } catch (error) {
            console.error('Error applying template:', error);
        }
    }

    // ... (その他のメソッド)
}
```

---

### 5. **既存プロンプトの分割実装**

#### 検証計画作成Agent

**固定部分**:
```
あなたは生産技術エンジニアの検証計画作成を支援するAIアシスタントです。

【最重要ルール】
 - 検索が必要な場合、必ずアクショングループの...
...
【対話スタイル】
- 専門的だが分かりやすい表現を使う
- ユーザーに対してブラッシュアップのための追加の質問をする
```

**編集可能部分** (デフォルトテンプレート):
```
【出力形式】
以下の構成で検証計画をMarkdown形式で出力してください:

## 検証計画: [設備/技術名]
...
```

#### 仕様書作成Agent

**固定部分**: (同様)

**編集可能部分** (デフォルトテンプレート):
```
【出力形式】
以下の構成で仕様書をMarkdown形式で出力してください:

## 設備仕様書: [設備名]
...
```

---

## 📋 実装ステップ (詳細版)

### Phase 1: バックエンド基盤 (1-2日)

#### Step 1: DynamoDBテーブル作成
- [ ] `agent-prompt-templates` テーブル作成
- [ ] GSI1, GSI2 作成
- [ ] デフォルトテンプレート3個を初期化

#### Step 2: Lambda関数開発
- [ ] `prompt-management-lambda.py` 作成
- [ ] CRUD操作実装
- [ ] Error handling追加

#### Step 3: API Gateway設定
- [ ] エンドポイント6個を定義
- [ ] CORS設定
- [ ] Cognito認証設定

---

### Phase 2: フロントエンド UI (2-3日)

#### Step 4: プロンプト管理ページ
- [ ] `prompt-management.html` 作成
- [ ] `prompt-management.js` 作成
- [ ] 基本UI実装

#### Step 5: テンプレート選択機能
- [ ] ドロップダウン実装
- [ ] テンプレート読込
- [ ] テンプレート作成・編集・削除

#### Step 6: エディター機能
- [ ] 固定部分表示（読み取り専用）
- [ ] 編集可能部分エディター
- [ ] プレビュー機能

---

### Phase 3: Agent統合 (2-3日)

#### Step 7: Agent作成時の動的プロンプト適用
- [ ] `agent_kb_action.py` 修正
- [ ] DynamoDBからプロンプト取得
- [ ] Agent更新ロジック実装

#### Step 8: PowerShellスクリプト修正
- [ ] `create-bedrock-agents-full.ps1` 修正
- [ ] DynamoDBからプロンプト取得
- [ ] Agent作成時に動的適用

#### Step 9: 既存システムとの統合
- [ ] 検証計画ページにプロンプト管理へのリンク
- [ ] 仕様書ページに同様のリンク
- [ ] 3ページ間のナビゲーション

---

### Phase 4: テスト・最適化 (1-2日)

#### Step 10: テスト実施
- [ ] Unit test作成（Lambda関数）
- [ ] Integration test
- [ ] UI/UXテスト

#### Step 11: パフォーマンス最適化
- [ ] DynamoDBクエリ最適化
- [ ] キャッシング実装
- [ ] フロントエンドUIの最適化

---

## 🔧 実装の優先度

**高優先度** (必須):
1. DynamoDBスキーマ設計・作成
2. Lambda CRUD関数実装
3. フロントエンド管理ページ (基本機能)
4. PowerShellスクリプト修正

**中優先度** (推奨):
1. テンプレート選択機能の拡張
2. プレビュー機能
3. バージョン管理
4. テンプレート共有機能

**低優先度** (将来):
1. テンプレートランキング
2. コラボレーティブ編集
3. AI提案機能

---

## 📌 重要な注意点

### セキュリティ
- [ ] DynamoDB へのアクセスは IAM ロールで制限
- [ ] Cognito認証は必須
- [ ] プロンプト内容はユーザー単位で保護

### 互換性
- [ ] 既存Agentとの下位互換性を維持
- [ ] プロンプト変更後のAgent再作成手順を文書化
- [ ] ロールバック機能の実装

### 運用
- [ ] プロンプトテンプレートのバージョン管理
- [ ] 変更履歴の記録
- [ ] デフォルトテンプレートの明確化

---

## 📊 プロジェクト最終スケジュール

| Phase | 内容 | 期間 | 担当 |
|-------|------|------|------|
| 1 | バックエンド基盤 | 1-2日 | Backend Engineer |
| 2 | フロントエンド UI | 2-3日 | Frontend Engineer |
| 3 | Agent統合 | 2-3日 | DevOps / Backend |
| 4 | テスト・最適化 | 1-2日 | QA / 全体 |
| **合計** | **実装完了** | **6-10日** | |

---

## 📚 関連ドキュメント

- [DynamoDBスキーマ詳細](./DYNAMODB_SCHEMA.md) *(作成予定)*
- [Lambda関数仕様](./LAMBDA_SPEC.md) *(作成予定)*
- [API 仕様書](./API_SPEC.md) *(作成予定)*
- [フロントエンド実装ガイド](./FRONTEND_GUIDE.md) *(作成予定)*

