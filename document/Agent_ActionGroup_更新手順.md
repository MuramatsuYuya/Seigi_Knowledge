# Agent Action Group パラメータ更新手順

## 📌 変更内容

複数フォルダ対応のため、パラメータフォーマットをJSON形式に変更しました。

### 変更前（カンマ区切り）
```
folder_paths: "フォルダ1,フォルダ2"
job_ids: "job1,job2"
```
**問題点**: 
- フォルダ名にカンマが含まれるとパースエラー
- folder_pathsとjob_idsの対応関係が不明確

### 変更後（JSON形式）
```json
folder_job_pairs: [
  {"folder_path": "フォルダ1", "job_id": "job1"},
  {"folder_path": "フォルダ2", "job_id": "job2"}
]
```
**メリット**:
- ✅ 一対一対応が明確
- ✅ 特殊文字を含むフォルダ名も安全
- ✅ 拡張性が高い

---

## 🔧 AWS Bedrock Agent Action Group の更新手順

### 1. Bedrock Agentコンソールへ移動
1. AWS Management Console → Amazon Bedrock → Agents
2. 対象のAgent (`agent-doctoknow`) を選択
3. **「Create draft version」** をクリック（Draft状態でないと編集不可）

### 2. Action タブを開く
上部タブから **「Action」** を選択

### 3. 既存のAction Groupを編集
1. Action Group名: `KnowledgeBaseSearch` を選択
2. **「Edit」** をクリック

### 4. Function details のパラメータを更新

**削除するパラメータ**:
- ❌ `folder_paths`
- ❌ `job_ids`

**新規追加するパラメータ**:

| 項目 | 内容 |
|-----|------|
| Parameter name | `folder_job_pairs` |
| Type | `string` |
| Required | ✓ (チェック) |
| Description | `JSON array of folder_path and job_id pairs. Format: [{"folder_path":"...", "job_id":"..."}]` |

**既存パラメータ (変更なし)**:

| 項目 | 内容 |
|-----|------|
| Parameter name | `query` |
| Type | `string` |
| Required | ✓ |
| Description | `Search query` |

### 5. 保存してPrepare
1. **「Save」** をクリック
2. Agent画面の右上 **「Prepare」** をクリック
3. 準備完了まで数分待機

### 6. テスト（オプション）
Agent画面の右側 **「Test」** パネルで動作確認:
```
フォルダ1とフォルダ2から〇〇について検索してください
```

---

## 📋 CloudFormation / CDK での設定例

### CloudFormation (OpenAPI Schema)
```yaml
ActionGroups:
  - ActionGroupName: KnowledgeBaseSearch
    Description: Search knowledge base with folder and job filters
    ActionGroupExecutor:
      Lambda: !GetAtt AgentKbActionLambda.Arn
    FunctionSchema:
      Functions:
        - Name: search_knowledge_base
          Description: Search knowledge base with folder and job filters
          Parameters:
            query:
              Type: string
              Required: true
              Description: Search query
            folder_job_pairs:
              Type: string
              Required: true
              Description: 'JSON array of folder_path and job_id pairs. Format: [{"folder_path":"...", "job_id":"..."}]'
```

### CDK (TypeScript)
```typescript
const actionGroup = new bedrock.CfnAgentActionGroup(this, 'KnowledgeBaseSearch', {
  agentId: agent.attrAgentId,
  agentVersion: 'DRAFT',
  actionGroupName: 'KnowledgeBaseSearch',
  actionGroupExecutor: {
    lambda: agentKbActionLambda.functionArn
  },
  functionSchema: {
    functions: [{
      name: 'search_knowledge_base',
      description: 'Search knowledge base with folder and job filters',
      parameters: {
        query: {
          type: 'string',
          required: true,
          description: 'Search query'
        },
        folder_job_pairs: {
          type: 'string',
          required: true,
          description: 'JSON array of folder_path and job_id pairs. Format: [{"folder_path":"...", "job_id":"..."}]'
        }
      }
    }]
  }
});
```

---

## ⚠️ 重要な注意点

### 1. Agent Instructionsの更新も必要
Agentの指示文も更新が必要です:

**Action タブ → Instructions** を以下のように更新:

```
[検索パラメータの抽出]
ユーザーの質問から以下を抽出してください:
1. folder_paths: 検索対象のフォルダパス（セッション属性から取得）
2. job_ids: 対応するジョブID（セッション属性から取得）
3. query: ユーザーの質問本文

[Action Group呼び出し]
search_knowledge_base関数を呼び出す際、以下の形式でパラメータを渡してください:
- query: ユーザーの質問
- folder_job_pairs: JSON配列形式 [{"folder_path":"...", "job_id":"..."}]

folder_job_pairsは、セッション属性の folder_job_pairs をそのまま渡してください。
```

### 2. Lambda関数のデプロイ
修正したLambda関数を必ずデプロイしてください:
```powershell
cd c:\webapp\PDFOCR
.\deploy-doctoknow.ps1
```

### 3. テスト時の注意
- Draft versionで動作確認
- 問題なければ **「Create version」** → **「Create alias」** で本番反映

---

## 🧪 動作確認チェックリスト

- [ ] Agent Action Groupのパラメータを更新
- [ ] Agent Instructionsを更新
- [ ] Lambda関数をデプロイ
- [ ] Agentを「Prepare」
- [ ] Test panelで単一フォルダテスト
- [ ] Test panelで複数フォルダテスト
- [ ] フロントエンドから実際に問い合わせテスト

---

## 📞 トラブルシューティング

### エラー: "Invalid parameter format"
→ `folder_job_pairs` が正しいJSON形式か確認

### エラー: "Function not found"
→ Agentを「Prepare」したか確認

### レスポンスが空
→ Lambda関数のCloudWatch Logsを確認
→ `[Agent Action]` タグでログを検索

---

作成日: 2025年11月19日
最終更新: 2025年11月19日
