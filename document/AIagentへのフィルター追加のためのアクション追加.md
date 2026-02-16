Bedrock Agents のコンソール UI が分かりにくく、**「Action Group」という名前の項目がそのまま見つからない**のが普通です。
実際には **“Agent の構成画面にある *Action*（アクション）タブ → Action Group の追加”** という操作になります。

以下、いまのコンソール画面の構造に沿った **実際の手順がわかる説明**です。

---

# ✅ **AWS コンソールでの作業をわかりやすく説明（Action Group の場所含む）**

## ① Bedrock Agent へ移動

1. AWS コンソールにログイン
2. 左メニュー
   **Amazon Bedrock → Agents**
3. 対象の Agent（例：`agent-doctoknow`）をクリック

---

## ② “Action” タブを開く（※ここが「Action Group」の場所）

Agent の管理画面に入ると上部にタブがあります：

* **Overview**
* **Instructions**
* **Knowledge bases**
* **Action** ← これ

👉 **Action タブの中に “Add action group” ボタンがあります**

つまり画面上では *“Action Group” と直接書かれていない* だけで、
この **Action タブの中で Action Group を追加**します。

---

## ③ Action Group を追加する

1. **Action** タブを開く
2. 右上の **「Add action group」** を押す
   （※場所：Action 一覧の上）

すると Action Group 作成画面が開きます。

---

# 🧩 **④ 入力すべき内容（あなたが書いた設定を人間が迷わない形へ整形）**

### ◆ **Action Group の基本情報**

| 項目              | 入力内容                                    |
| --------------- | --------------------------------------- |
| Name            | `KnowledgeBaseSearch`                   |
| Type            | **Define with function details**        |
| Lambda function | `${ProjectName}-agent-kb-action-v0` を選択 |

---

### ◆ **Function details（内部の関数仕様を登録する部分）**

| 項目            | 内容                                                |
| ------------- | ------------------------------------------------- |
| Function name | `search_knowledge_base`                           |
| Description   | Search knowledge base with folder and job filters |

### Parameters（API の引数定義）

Action Group の下部にある “Parameters” に以下を追加：

1. **query**

   * type: string
   * required: ✓
   * description: Search query

2. **folder_paths**

   * type: string
   * required: ✓
   * description: Comma-separated folder paths

3. **job_ids**

   * type: string
   * required: ✓
   * description: Comma-separated job IDs

---

# 🧭 **Action Group が見つからない理由**

コンソール UI では “Action Group” と書かれていません。

代わりに：

> Bedrock Agent の編集 → **Action タブ → Add action group**

ここが “Action Group” の実体です。

もし “Action タブ” が見えない場合は：

### ✔ Agent が **Draft** 状態でないと編集できません

右上が “Published” になっている場合、
→ **“Create draft version”** を押すと編集可能になります。

---

# 必要ならスクリーンショット風の図や

# 設定 JSON / CloudFormation / CDK 版 も作れます。

続けますか？
