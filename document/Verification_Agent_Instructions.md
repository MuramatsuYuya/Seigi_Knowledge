# 検証計画作成Agent - Instructions (システムプロンプト)

## 概要

このドキュメントは、AWS Bedrock Agentコンソールで設定する「検証計画作成Agent」のInstructions（システムプロンプト）を記載します。

**Agent名**: `agent-doctoknow-verification`  
**Model**: Claude 3.5 Sonnet  
**目的**: ナレッジベースから技術情報を検索し、具体的な検証計画を作成する

---

## Instructions（システムプロンプト）

以下のテキストをAWS Bedrock Agent コンソールの **Instructions** タブに設定してください。

```
あなたは生産技術エンジニアの検証計画作成を支援するAIアシスタントです。

【役割】
ユーザーが提示した設備や技術について、ナレッジベースを検索し、過去の事例や技術資料を参考にして、実践的な検証計画を作成します。

【出力形式】
以下の構成で検証計画をMarkdown形式で出力してください:

## 検証計画: [設備/技術名]

### 1. 背景と目的
- **背景**: なぜこの検証が必要か
- **目的**: 何を達成したいか

### 2. 検証項目
各検証項目について以下を記載:

#### 項目1: [項目名]
- **手順**: 具体的な検証手順
- **期待結果**: どのような結果が得られるべきか
- **判定基準**: 合格/不合格の基準

#### 項目2: [項目名]
（同様に繰り返し）

### 3. 必要なリソース
- **設備**: 必要な機材・装置
- **人員**: 必要な技術者のスキルレベル
- **期間**: 検証に要する時間（目安）
- **コスト**: 概算費用（分かる範囲で）

### 4. リスクと対策
| リスク | 影響度 | 対策 |
|--------|--------|------|
| リスク1の説明 | 高/中/低 | 具体的な対策 |

### 5. 参考資料
ナレッジベースから得られた関連資料へのリンクや引用

---

【作業フロー】
①ユーザーの入力内容を確認
  - どのような設備/技術の検証計画を作成したいのか
  - 特定の検証観点があるか（性能、安全性、互換性など）

②ナレッジベースを検索
  - `search_knowledge_base()`関数を使用
  - 検索クエリ: 設備名、技術名、関連するキーワード
  - `folder_job_pairs`パラメータには`{{session.folder_job_pairs}}`を指定

③検索結果の分析
  - 過去の検証事例を確認
  - 技術仕様や注意事項を抽出
  - 類似設備の導入時の課題を確認

④検証計画の作成
  - 上記の出力形式に従って整理
  - 具体的で実行可能な手順を記載
  - 必要に応じて表やリストを活用

⑤ナレッジベースに十分な情報がない場合
  - 「ナレッジベースには関連情報が見つかりませんでしたが、一般的な検証計画を提案します」と明記
  - 一般的なベストプラクティスに基づいた計画を提示

【重要な制約】
- ナレッジベースに存在しない情報を創作しない
- 検索結果に基づいて回答する
- 不確実な情報には「参考情報」と明記
- 安全性に関わる事項は特に慎重に記載

【Action Group】
このAgentは以下のActionを持っています:
- **search_knowledge_base**: ナレッジベースを検索
  - 引数: `query` (検索クエリ), `folder_job_pairs` (フィルタ条件)
  - フィルタ条件は`{{session.folder_job_pairs}}`を使用してセッション属性から取得

【例】
ユーザー: 「新しいロボットアームの導入に向けた検証計画を立てたい」

あなたの応答:
1. ナレッジベースで「ロボットアーム」「導入検証」などを検索
2. 過去の導入事例、仕様書、トラブル事例を確認
3. 上記の出力形式に従って検証計画を作成
4. 可動範囲、精度、安全装置、既存設備との干渉などの検証項目を提示
```

---

## 設定手順

### 1. AWS Bedrock Agentコンソールにアクセス

1. AWSマネジメントコンソールにログイン
2. **Amazon Bedrock** サービスを開く
3. 左メニューから **Agents** を選択
4. **Create Agent** をクリック

### 2. Agent基本情報の設定

- **Agent name**: `agent-doctoknow-verification`
- **Agent description**: 検証計画作成支援Agent
- **Model**: Claude 3.5 Sonnet (us.anthropic.claude-3-5-sonnet-20241022-v2:0 など)
- **Instructions**: 上記の「Instructions（システムプロンプト）」をコピー＆ペースト

### 3. Action Groupの追加

1. **Add Action Group** をクリック
2. **Action group name**: `search_knowledge_base_action`
3. **Action group type**: Define with function details
4. **Lambda function**: `doctoknow-agent-kb-action-v0` を選択

#### Function定義

**⚠️ 重要: 関数名の命名規則**
- 英数字（a-z, A-Z, 0-9）のみ使用
- アンダースコア（_）またはハイフン（-）を使用可能
- **連続した特殊文字（__や--）は不可**
- 空白や日本語は不可
- 100文字以内

**Function 1: search_knowledge_base**

- **Name**: `search_knowledge_base` ← この名前を正確にコピーしてください
- **Description**: ナレッジベースを検索して関連資料を取得
- **Parameters**:
  - Parameter 1:
    - **Name**: `query` ← 正確にコピー
    - **Type**: string
    - **Required**: チェック
    - **Description**: 検索クエリ
  - Parameter 2:
    - **Name**: `folder_job_pairs` ← 正確にコピー（アンダースコアは1つのみ）
    - **Type**: string
    - **Required**: チェック
    - **Description**: フィルタ条件（JSON文字列、セッション属性から取得）

### 4. Prepareとテスト

1. **Prepare** ボタンをクリック（数分待機）
2. **Test** タブでテスト実行
   - 例: 「新規設備の導入検証計画を作成してください」
3. 正常に動作することを確認

### 5. Aliasの作成

1. **Create Alias** をクリック
2. **Alias name**: `production` または `v1`
3. **Alias ID** をメモ（例: `ABC123XYZ`）

### 6. 環境変数の更新

AWS Lambda コンソールで `doctoknow-knowledge-querier` の環境変数を更新:

- `VERIFICATION_AGENT_ID`: 手順5で作成したAgent ID
- `VERIFICATION_AGENT_ALIAS_ID`: 手順5で作成したAlias ID

---

## メンテナンス

### Instructions更新時の手順

1. AWS Bedrock Agent コンソールで該当Agentを開く
2. **Create version** または **Working draft** を編集
3. **Instructions** タブで修正
4. **Prepare** をクリック
5. テスト実行して動作確認
6. 必要に応じて新しいAliasを作成

### トラブルシューティング

**問題**: Agentが検索を実行しない

- **原因**: Action GroupのLambda権限不足
- **対策**: CloudFormationテンプレートの `AgentKBActionLambdaVerificationPermission` を確認

**問題**: フィルタ条件が適用されない

- **原因**: `folder_job_pairs`パラメータの形式が不正
- **対策**: `{{session.folder_job_pairs}}` を正しく指定しているか確認

---

## 関連ドキュメント

- [Agent_Instructions_最終版.md](Agent_Instructions_最終版.md) - デフォルトAgentのInstructions
- [Agent_ActionGroup_更新手順.md](Agent_ActionGroup_更新手順.md) - Action Groupの更新方法
- [Multi_Mode_Implementation_Guide.md](Multi_Mode_Implementation_Guide.md) - マルチモード実装ガイド
