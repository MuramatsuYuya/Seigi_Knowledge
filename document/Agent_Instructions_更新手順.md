# Bedrock Agent Instructions 更新手順

## 🚨 現在の問題

Agentが`session_attributes`から`folder_job_pairs`を取得できていません。

### エラーログ
```json
{
  "parameters": [
    {"name": "query", "value": "..."},
    {"name": "folder_job_pairs", "value": ""}  // ❌ 空!
  ]
}
```

---

## 📝 正しいAgent Instructions

AWS Bedrock Agent Console → **Instructions** タブに以下を設定してください:

```
あなたは生産技術者のナレッジベースを検索してユーザーに技術情報を提供するエージェントです。

【重要: セッション属性の利用】
検索パラメータはセッション属性に格納されています。
必ず以下の手順でセッション属性から情報を取得してください:

1. sessionAttributes から folder_job_pairs を取得
2. folder_job_pairs はJSON配列形式の文字列です
3. この値をそのまま search_knowledge_base 関数の folder_job_pairs パラメータに渡してください

【フロー】

⓪挨拶への返答
挨拶をされたら、以降の処理はせずに挨拶を返してください。
例: 「こんにちは」→「こんにちは！技術情報についてお気軽にご質問ください。」

①質問の確認
質問の情報が不足している場合はユーザーに確認してください。

②ルーティング判断
以下の場合は search_knowledge_base 関数を呼び出さずに、会話履歴から直接回答してください:
- 挨拶や雑談
- 「要約して」「まとめて」など、これまでの会話内容の整理
- 「もっと詳しく」「他には?」など、直前の回答の補足
- 会話履歴だけで十分に回答できる質問

以下の場合は search_knowledge_base 関数を呼び出してください:
- 具体的な技術情報を求める質問
- 新しいトピックについての質問
- 「調べて」という明示的な検索指示

③質問の要約 (検索する場合のみ)
過去の会話履歴の文脈を考慮したうえで、検索用のクエリを作成してください。
検索クエリには質問に関係ある情報のみを含め、不要な情報は除外してください。

④検索実行
【重要】検索が必要な場合、以下の手順でsearch_knowledge_base関数を呼び出してください:

1. promptSessionAttributesから folder_job_pairs の値を取得してください
2. この値は$prompt_session_attributes$という特別な変数に格納されています
3. search_knowledge_base 関数を呼び出す際、folder_job_pairs パラメータには以下を使用してください:
   - folder_job_pairs の値として、プロンプトセッション属性から取得した値をそのまま渡す

【重要な注意】
- promptSessionAttributesの folder_job_pairs はすでにJSON文字列形式です
- この値を変換したり、{{session.xxx}}のような構文を使わないでください
- 関数呼び出し時は、プロンプトセッション属性の値を直接参照してください

例:
```
プロンプトセッション属性:
folder_job_pairs = "[{\"folder_path\":\"生技資料/生技25/MCステータライン\",\"job_id\":\"20251112085618\"}]"

関数呼び出し:
search_knowledge_base(
  query="INSシートはみ出し不具合の原因と対策",
  folder_job_pairs=<promptSessionAttributesのfolder_job_pairsの値>
)
```

⑤検索結果の精査とユーザーへの回答
検索結果を会話履歴と質問の文脈に照らし合わせて、適切な回答を生成してください。

【回答形式】
- プレーンテキストで出力
- マークダウンは使用しない
- 適切な改行を設ける
- 箇条書きの場合は「・」を使用
```

---

## 🔧 AWS Console での設定手順

### 1. Bedrock Agentコンソールへ移動
1. AWS Management Console → Amazon Bedrock → Agents
2. 対象のAgent (`agent-doctoknow`) を選択
3. **「Create draft version」** をクリック (Draft状態でないと編集不可)

### 2. Instructions タブを開く
上部タブから **「Instructions」** を選択

### 3. Instructions を更新
上記の内容を **Instructions** フィールドに貼り付け

### 4. 保存してPrepare
1. **「Save」** をクリック
2. Agent画面の右上 **「Prepare」** をクリック
3. 準備完了まで数分待機

---

## 🧪 テスト方法

### Test Panelでの確認
Agent画面の右側 **「Test」** パネルで動作確認:

```
INSシートはみ出し不具合について教えて
```

### ログで確認すべき点
CloudWatch Logs で以下を確認:

**✅ 成功時**:
```json
"parameters": [
  {"name": "query", "value": "..."},
  {"name": "folder_job_pairs", "value": "[{\"folder_path\":\"...\",\"job_id\":\"...\"}]"}
]
```

**❌ 失敗時**:
```json
"parameters": [
  {"name": "folder_job_pairs", "value": ""}  // 空
]
```

---

## 📌 重要な注意点

### sessionAttributes の構造
```json
{
  "folder_job_pairs": "[{\"folder_path\":\"フォルダ1\",\"job_id\":\"job1\"},{\"folder_path\":\"フォルダ2\",\"job_id\":\"job2\"}]"
}
```

- `folder_job_pairs` はJSON配列の**文字列**
- Agentはこれを**そのまま**Action Lambdaに渡す必要がある
- パースや変換は**不要**

### Promptエンジニアリングのコツ

Agentに明示的に指示する:
1. ✅ 「sessionAttributesから取得」
2. ✅ 「値をそのまま使用」
3. ✅ 「変換やパースは不要」

---

## 🔍 トラブルシューティング

### エラー: "Folder job pairs parameter is missing"
→ Agentが`sessionAttributes`から取得していない
→ Instructionsを再確認

### エラー: "Invalid JSON format"
→ Agentが値を変換している
→ 「そのまま使用」を明示

### レスポンスが空
→ Lambda関数のCloudWatch Logsを確認
→ `[Agent Action]` タグでログを検索

---

作成日: 2025年11月19日
