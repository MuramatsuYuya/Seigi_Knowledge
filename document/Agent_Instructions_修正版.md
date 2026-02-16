# Bedrock Agent Instructions 修正版 (promptSessionAttributes対応)

## 🚨 発見された問題

テストログから、Agentが `{{session.folder_job_pairs}}` という**リテラル文字列**を渡していることが判明:

```json
"folder_job_pairs": "{{session.folder_job_pairs}}"
```

これがJSONパースエラーを引き起こしています。

---

## 📝 修正されたAgent Instructions

AWS Bedrock Agent Console → **Instructions** タブに以下を設定してください:

```
あなたは生産技術者のナレッジベースを検索してユーザーに技術情報を提供するエージェントです。

【重要: Prompt Session Attributesについて】
- Prompt Session Attributesには folder_job_pairs というキーが含まれています
- この値はJSON配列形式の文字列です
- アクション関数を呼び出す際、このキーの値を自動的に参照できます

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
【最重要】検索が必要な場合、KnowledgeBaseSearchアクショングループのsearch_knowledge_base関数を呼び出してください。

関数パラメータ:
- query: 会話履歴を考慮した検索クエリ
- folder_job_pairs: Prompt Session Attributesのfolder_job_pairsの値

【重要な注意事項】
- folder_job_pairs パラメータには、Prompt Session Attributesから自動的に取得される値を使用します
- この値はシステムが自動的に関数に渡すため、あなたが明示的に参照する必要はありません
- {{session.xxx}} のような構文や変数展開は使用しないでください
- 関数を呼び出す際は、パラメータ名のみを指定してください

正しい関数呼び出し例:
search_knowledge_base(
  query="INSシートはみ出し不具合の原因と対策",
  folder_job_pairs=<Prompt Session Attributesの値が自動的に使用されます>
)

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

### 4. Advanced Prompts の確認 (重要!)
**「Advanced prompts」** セクションで以下を確認:
- **Orchestration** プロンプトで `$prompt_session_attributes$` が利用可能か確認
- もし利用可能なら、Action Group呼び出し部分で明示的に指定

### 5. 保存してPrepare
1. **「Save」** をクリック
2. Agent画面の右上 **「Prepare」** をクリック
3. 準備完了まで数分待機

---

## 🔍 代替案: promptSessionAttributes を使わない方法

もし上記の方法でも動作しない場合、**Lambda関数側で対応**します:

### オプション1: デフォルト値を設定
`agent_kb_action.py` で空の場合にエラーを返さず、エラーメッセージでユーザーに通知:

```python
if not folder_job_pairs_str:
    # エラーではなく、ユーザーに通知するメッセージを返す
    return {
        'messageVersion': '1.0',
        'response': {
            'actionGroup': action_group,
            'function': function,
            'functionResponse': {
                'responseBody': {
                    'TEXT': {
                        'body': json.dumps({
                            'answer': 'フォルダ情報が指定されていません。複数フォルダを選択してから質問してください。',
                            'sources': []
                        }, ensure_ascii=False)
                    }
                }
            }
        }
    }
```

### オプション2: sessionState の sessionAttributes を直接参照
Lambda関数で `event['sessionState']['sessionAttributes']` から直接取得:

```python
def lambda_handler(event, context):
    # sessionAttributesから直接取得
    session_attributes = event.get('sessionState', {}).get('sessionAttributes', {})
    folder_job_pairs_str = session_attributes.get('folder_job_pairs', '')
    
    if not folder_job_pairs_str:
        # parametersから取得を試みる
        param_dict = {}
        for param in event.get('parameters', []):
            param_dict[param['name']] = param['value']
        folder_job_pairs_str = param_dict.get('folder_job_pairs', '')
```

---

## 📋 チェックリスト

- [ ] Agent Instructionsを更新
- [ ] Advanced Promptsを確認
- [ ] Agentを「Prepare」
- [ ] Test panelで動作確認
- [ ] CloudWatch Logsでパラメータを確認
- [ ] 必要に応じてLambda関数を修正

---

## 🧪 テスト時の確認ポイント

### CloudWatch Logsで以下を確認:

**✅ 成功時**:
```json
"parameters": [
  {"name": "query", "value": "..."},
  {"name": "folder_job_pairs", "value": "[{\"folder_path\":\"...\",\"job_id\":\"...\"}]"}
]
```

**❌ 現在の状態 (失敗)**:
```json
"parameters": [
  {"name": "folder_job_pairs", "value": "{{session.folder_job_pairs}}"}
]
```

---

作成日: 2025年11月19日
最終更新: 2025年11月19日
