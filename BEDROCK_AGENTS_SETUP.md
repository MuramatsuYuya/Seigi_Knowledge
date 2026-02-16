# Bedrock Agents セットアップガイド

このガイドでは、AI質問、検証計画作成、仕様書作成の3つのBedrock Agentを作成する方法を説明します。

## 前提条件

1. AWS CLIがインストールされ、適切な認証情報が設定されていること
2. PowerShell 5.1以降がインストールされていること
3. 以下のAWSリソースが既に存在すること：
   - S3バケット（データ保存用）
   - Lambda関数（`doctoknow-dev2-agent-kb-action-v0`）
   - KnowledgeBase（または作成予定）
   - IAMロール（`AmazonBedrockExecutionRoleForAgents_doctoknow`）

## スクリプトファイル

### create-bedrock-agents-full.ps1
**推奨：新規環境構築用**

AI質問Agent、検証計画Agent、仕様書作成Agentの3つすべてを作成します。

#### 基本的な使い方

```powershell
# 既存のKnowledgeBaseを使用する場合
.\create-bedrock-agents-full.ps1 `
    -ProjectName "doctoknow-dev2" `
    -Region "us-west-2" `
    -ExistingKnowledgeBaseId "QBRNP5FY8E" `
    -ExistingIAMRoleArn "arn:aws:iam::722631436454:role/service-role/AmazonBedrockExecutionRoleForAgents_doctoknow"
```

#### パラメータ

| パラメータ | 説明 | デフォルト値 |
|-----------|------|-------------|
| `-ProjectName` | プロジェクト名 | `doctoknow-dev2` |
| `-Region` | AWSリージョン | `us-west-2` |
| `-S3BucketName` | S3バケット名 | `doctoknow-data` |
| `-LambdaFunctionName` | Lambda関数名（空の場合は自動生成） | （自動生成） |
| `-CloudFormationStackName` | CloudFormationスタック名 | `doctoknow-stack2` |
| `-Model` | 使用するBedrockモデルID | `anthropic.claude-3-5-sonnet-20241022-v2:0` |
| `-ExistingKnowledgeBaseId` | 既存のKnowledgeBase ID | （必須） |
| `-ExistingIAMRoleArn` | 既存のIAMロールARN | （必須） |
| `-SkipKnowledgeBase` | KnowledgeBase作成をスキップ | false |
| `-SkipDefaultAgent` | AI質問Agent作成をスキップ | false |
| `-UpdateCloudFormation` | CloudFormation更新情報を表示 | false |

#### 使用例

**例1: すべてのAgentを作成**
```powershell
.\create-bedrock-agents-full.ps1 `
    -ExistingKnowledgeBaseId "QBRNP5FY8E" `
    -ExistingIAMRoleArn "arn:aws:iam::722631436454:role/service-role/AmazonBedrockExecutionRoleForAgents_doctoknow"
```

**例2: 検証計画と仕様書Agentのみ作成（AI質問Agentはスキップ）**
```powershell
.\create-bedrock-agents-full.ps1 `
    -ExistingKnowledgeBaseId "QBRNP5FY8E" `
    -ExistingIAMRoleArn "arn:aws:iam::722631436454:role/service-role/AmazonBedrockExecutionRoleForAgents_doctoknow" `
    -SkipDefaultAgent
```

**例3: CloudFormation更新情報も表示**
```powershell
.\create-bedrock-agents-full.ps1 `
    -ExistingKnowledgeBaseId "QBRNP5FY8E" `
    -ExistingIAMRoleArn "arn:aws:iam::722631436454:role/service-role/AmazonBedrockExecutionRoleForAgents_doctoknow" `
    -UpdateCloudFormation
```

### create-bedrock-agents.ps1
**旧バージョン：検証計画と仕様書Agentのみ作成**

既存のデフォルトAgentを使用し、検証計画と仕様書作成Agentのみを作成します。

## スクリプトの実行フロー

`create-bedrock-agents-full.ps1` は以下の順序で処理を実行します：

1. **Lambda ARN取得** - Lambda関数の存在確認
2. **IAMロール準備** - Bedrock Agent用のIAMロールを取得
3. **KnowledgeBase ID準備** - 既存のKnowledgeBaseを使用
4. **AI質問Agent作成**（`-SkipDefaultAgent`未指定時）
   - Agent本体の作成
   - Action Groupの追加
   - Lambda実行権限の付与
   - Prepare（準備）
   - Alias作成
5. **検証計画Agent作成**
   - Agent本体の作成
   - Action Groupの追加
   - Lambda実行権限の付与
   - Prepare（準備）
   - Alias作成
6. **仕様書作成Agent作成**
   - Agent本体の作成
   - Action Groupの追加
   - Lambda実行権限の付与
   - Prepare（準備）
   - Alias作成
7. **結果サマリー表示**

## 作成されるAgent

### 1. AI質問Agent（デフォルトAgent）
- **名前**: `agent-{ProjectName}-default`
- **用途**: 生産技術ナレッジベースへの一般的な質問応答
- **プロンプト**: 質問の確認、検索判断、検索実行、回答生成のフローを実行
- **Action Group**: `search_knowledge_base_action`

### 2. 検証計画作成Agent
- **名前**: `agent-{ProjectName}-verification`
- **用途**: 設備の検証計画書作成支援
- **プロンプト**: `document\Verification_Agent_Prompt.txt`から読み込み
- **Action Group**: `search_knowledge_base_action`

### 3. 仕様書作成Agent
- **名前**: `agent-{ProjectName}-specification`
- **用途**: 設備の仕様書作成支援
- **プロンプト**: `document\Specification_Agent_Prompt.txt`から読み込み
- **Action Group**: `search_knowledge_base_action`

## 必要なプロンプトファイル

以下のファイルが存在する必要があります：

- `document\Verification_Agent_Prompt.txt` - 検証計画Agent用プロンプト
- `document\Specification_Agent_Prompt.txt` - 仕様書作成Agent用プロンプト

AI質問Agent用のプロンプトはスクリプト内に埋め込まれています。

## トラブルシューティング

### エラー: "Lambda関数が見つかりません"
Lambda関数が存在することを確認してください：
```powershell
aws lambda get-function --function-name doctoknow-dev2-agent-kb-action-v0 --region us-west-2
```

### エラー: "Agent名が既に存在します"
既存のAgentを使用します。スクリプトは自動的に既存のAgentのIDを取得します。

### エラー: "Aliasは既に存在します"
既存のAliasを使用します。スクリプトは自動的に既存のAlias IDを取得します。

### Lambda権限エラー
Lambda関数のリソースベースポリシーで、すべてのBedrock Agentからの呼び出しを許可してください：
```powershell
aws lambda add-permission `
    --function-name doctoknow-dev2-agent-kb-action-v0 `
    --statement-id AllowAllBedrockAgents `
    --action lambda:InvokeFunction `
    --principal bedrock.amazonaws.com `
    --source-arn "arn:aws:bedrock:us-west-2:722631436454:agent/*" `
    --region us-west-2
```

## CloudFormationへの反映

スクリプト実行後、CloudFormationテンプレートのパラメータを更新する必要があります：

```json
"Parameters": {
  "BedrockAgentId": {
    "Type": "String",
    "Default": "<AI質問AgentのID>"
  },
  "BedrockAgentAliasId": {
    "Type": "String",
    "Default": "<AI質問AgentのAliasID>"
  },
  "VerificationAgentId": {
    "Type": "String",
    "Default": "<検証計画AgentのID>"
  },
  "VerificationAgentAliasId": {
    "Type": "String",
    "Default": "<検証計画AgentのAliasID>"
  },
  "SpecificationAgentId": {
    "Type": "String",
    "Default": "<仕様書作成AgentのID>"
  },
  "SpecificationAgentAliasId": {
    "Type": "String",
    "Default": "<仕様書作成AgentのAliasID>"
  }
}
```

スクリプト実行後に表示される結果サマリーから、これらの値をコピーします。

その後、CloudFormationスタックを更新します：
```powershell
.\deploy-doctoknow.ps1
```

## 注意事項

1. **Agent準備時間**: 各Agentの準備（Prepare）には数分かかります。スクリプトは自動的に30秒待機します。
2. **Lambda権限**: 各AgentにLambda実行権限を個別に付与しています。既存のMacron権限（`agent/*`）がある場合、個別の権限は不要です。
3. **既存リソース**: Agentやaliasが既に存在する場合、スクリプトは既存のものを使用します。
4. **リージョン**: すべてのリソースは同じリージョンに作成されます（デフォルト: `us-west-2`）。

## 次のステータ

1. スクリプトを実行してAgentを作成
2. 結果サマリーに表示されたIDをメモ
3. CloudFormationテンプレートのパラメータを更新
4. `.\deploy-doctoknow.ps1`を実行してデプロイ
5. ブラウザでアプリケーションにアクセスして動作確認
