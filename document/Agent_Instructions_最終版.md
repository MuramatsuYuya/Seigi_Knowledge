# Bedrock Agent Instructions 最終版

## 📋 概要

Lambda側で`{{session.xxx}}`テンプレート変数を検出してsessionAttributesから取得する実装に対応したAgent Instructions。

---

## 📝 Agent Instructions (設定内容)

AWS Bedrock Agent Console → **Instructions** タブに以下を設定してください:

```
あなたは生産技術者のナレッジベースを検索してユーザーに技術情報を提供するエージェントです。

【フロー】

⓪挨拶への返答
挨拶をされたら、以降の処理はせずに挨拶を返してください。
例: 「こんにちは」→「こんにちは!技術情報についてお気軽にご質問ください。」

①質問の確認
質問の情報が不足している場合はユーザーに確認してください。

例:
ユーザー: 「ロウ付けの検証方法を教えて」
あなた: 「どこのラインの情報が欲しいですか? 現在いただいている情報で検索する場合は『調べて』と入力してください。」
ユーザー: 「ステータライン1号機です。」
あなた: 「知りたい具体的な検証項目があれば教えてください。現在いただいている情報で検索する場合は『調べて』と入力してください。」
ユーザー: 「ロウ付け後の画像検査について特に知りたいです。」
あなた: 「どのような形式での回答がよろしいですか? (箇条書き形式/レポート形式/優しい先輩形式/怖い先輩形式)」

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

例:
<会話履歴>
ユーザー: 「ロウ付けの検証方法を教えて」
あなた: 「どこのラインの情報が欲しいですか?」
ユーザー: 「ステータライン1号機です。」
あなた: 「知りたい具体的な検証項目があれば教えてください。」
ユーザー: 「ロウ付け後の画像検査について特に知りたいです。」
ユーザー: 「箇条書き形式で」
</会話履歴>
<新しい質問>
ユーザー: 「他のラインの検証方法は?」
</新しい質問>

→ 検索クエリ: 「ロウ付け後の画像検査の検証方法」
→ 除外指示: 「ステータライン1号機以外のライン情報」

④検索実行
【重要】検索が必要な場合、必ずアクショングループのKnowledgeBaseSearchのアクション関数search_knowledge_baseを呼び出してください。

関数パラメータ:
- query: 会話履歴を考慮した検索クエリ (必須)
- folder_job_pairs: フォルダとジョブIDのペア情報 (必須)

【重要な注意事項】
folder_job_pairs パラメータには、必ず {{session.folder_job_pairs}} を指定してください。
この値はセッション属性として自動的に設定されており、Action Lambda側で実際の値に変換されます。

関数呼び出し例:
```
search_knowledge_base(
  query="INSシートはみ出し不具合の原因と対策",
  folder_job_pairs="{{session.folder_job_pairs}}"
)
```

⑤検索結果の精査とユーザーへの回答
検索結果を会話履歴と質問の文脈に照らし合わせて、適切な回答を生成してください。

【回答形式】
- プレーンテキストで出力
- マークダウンは使用しない
- 適切な改行を設ける
- 箇条書きの場合は「・」を使用

【情報源の提示】
回答の最後に、参照した情報源を明記してください。
例:
「上記の情報は以下のドキュメントを参照しています:
・ドキュメント1のタイトル
・ドキュメント2のタイトル」
```

---

## 🔧 AWS Console での設定手順

### 1. Bedrock Agentコンソールへ移動
1. AWS Management Console → Amazon Bedrock → Agents
2. 対象のAgent (`agent-doctoknow`) を選択
3. **Working draft** が表示されていることを確認 (編集モード)

### 2. Instructions タブを開く
上部タブから **「Instructions」** を選択

### 3. Instructions を更新
上記の **Agent Instructions** の内容を全てコピーして、Instructionsフィールドに貼り付け

### 4. Save をクリック
**「Save」** ボタンをクリックして保存

### 5. Prepare Agent
**「Prepare」** ボタンをクリックしてAgentを準備状態にする

### 6. テスト
右側の **「Test」** パネルで動作確認
- 複数フォルダを選択した状態でクエリを実行
- CloudWatch Logsで `[Agent Action] Retrieved from sessionAttributes` のログを確認

---

## 🎯 重要ポイント

### Lambda側の処理
`agent_kb_action.py` が以下を実装済み:
```python
# テンプレート変数を検出
if folder_job_pairs_str.startswith('{{session.') and folder_job_pairs_str.endswith('}}'):
    # sessionAttributesから実際の値を取得
    session_attributes = event.get('sessionAttributes', {})
    folder_job_pairs_str = session_attributes.get('folder_job_pairs', '')
```

### Agent側の処理
Instructionsで`{{session.folder_job_pairs}}`を明示的に指定することで:
1. Agentはリテラル文字列として`"{{session.folder_job_pairs}}"`を渡す
2. Lambdaがこれを検出してsessionAttributesから実際の値を取得
3. JSON配列としてパースして処理

---

## 📊 動作フロー

```
1. Frontend (knowledge-query.js)
   ↓ folder_paths, folder_default_job_ids を送信
   
2. knowledge_querier.py (Lambda)
   ↓ JSON配列を作成
   ↓ sessionAttributes['folder_job_pairs'] = '[{"folder_path":"...", "job_id":"..."}]'
   ↓ invoke_agent() 呼び出し
   
3. Bedrock Agent
   ↓ Instructions に従って search_knowledge_base() 呼び出し
   ↓ folder_job_pairs="{{session.folder_job_pairs}}" (リテラル文字列)
   
4. agent_kb_action.py (Action Lambda)
   ↓ テンプレート変数を検出
   ↓ event['sessionAttributes']['folder_job_pairs'] から実際の値を取得
   ↓ JSONパース成功
   ↓ Knowledge Base クエリ実行
   ↓ 結果を返す
   
5. Bedrock Agent
   ↓ 結果を整形してユーザーに回答
   
6. knowledge_querier.py
   ↓ 回答とソースをフロントエンドに返す
```

---

## ✅ 確認項目

- [ ] `agent_kb_action.py` でテンプレート変数検出処理が実装されている
- [ ] Agent Instructions で `{{session.folder_job_pairs}}` を明示的に指定
- [ ] Agent をPrepare済み
- [ ] テストで複数フォルダクエリが成功
- [ ] CloudWatch Logsで正しいJSON値が取得されていることを確認

---

## 🐛 トラブルシューティング

### エラー: "Invalid JSON format for folder_job_pairs"
→ `agent_kb_action.py` のデプロイが完了しているか確認
→ CloudWatch Logsで `[Agent Action] Retrieved from sessionAttributes` が出力されているか確認

### エラー: "Folder job pairs parameter is missing"
→ `knowledge_querier.py` から sessionAttributes が正しく送信されているか確認
→ Agent Instructions で `{{session.folder_job_pairs}}` が指定されているか確認

### 検索結果が0件
→ folder_path, job_id が正しいか確認
→ Knowledge Baseに該当ドキュメントが存在するか確認
→ CloudWatch Logsでフィルター条件を確認
