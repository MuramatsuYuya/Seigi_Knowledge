# ステップ0 機能実装 - 最終要件定義書

**作成日**: 2025年11月11日
**バージョン**: 2.0 (最終版)
**ステータス**: ✅ **要件確定**

---

## 1. 機能概要

`index.html` の「ステップ1」より前に、S3のフォルダとファイルを管理する「ステップ0」を新設する。

| 機能 | 説明 |
| :--- | :--- |
| **フォルダツリー表示** | `PDF/` 配下の全フォルダを階層表示。`doctoknow-dev-folder-config` テーブルに登録済みのフォルダは識別表示する。 |
| **新規フォルダ作成** | `PDF/` 配下の任意の場所に新しいフォルダを作成する。 |
| **フォルダ削除** | 中身が空のフォルダのみ削除可能。子フォルダやファイルが存在する場合はエラーを表示する。 |
| **ファイル一括アップロード** | ユーザーがローカルから複数PDFファイルを選択し、指定したS3フォルダへ一括でアップロードする。 |
| **自動処理** | **登録済みフォルダ**へのアップロード時は、`default_job_id` を使って自動でナレッジ化処理を開始する。 |
| **手動案内** | **未登録フォルダ**へのアップロード時は、ファイル配置のみ行い、ユーザーに「ステップ1以降で処理してください」と案内する。 |

---

## 2. アーキテクチャと処理フロー

### 2.1. ファイルアップロードフロー (署名付きURL方式)

1.  **フロントエンド**:
    *   ユーザーがアップロード先のフォルダとファイルを選択。
    *   `GET /api/s3-presigned-urls` を呼び出し、ファイルごとの署名付きURLを要求。
2.  **バックエンド (`folder_management_lambda`)**:
    *   `doctoknow-dev-folder-config` テーブルをチェックし、フォルダが登録済みか判定。
    *   ファイルごとにS3へのアップロード用署名付きURLを生成。
    *   URLリスト、登録状態、`default_job_id` (登録済みの場合) をフロントエンドに返す。
3.  **フロントエンド**:
    *   受け取った署名付きURLを使い、ファイルをS3へ直接アップロード (マルチパートアップロード対応)。
    *   全ファイルのアップロード完了後、フォルダが**登録済み**であれば `POST /api/trigger-processing` を呼び出す。
4.  **バックエンド (`folder_management_lambda`)**:
    *   `trigger-processing` を受け取り、アップロードされたファイルに対して `worker` Lambdaを非同期で呼び出し、自動処理を開始する。
    *   最後のファイルの処理イベントに `trigger_kb_sync: true` フラグを付与する。

### 2.2. `default_job_id` 設定フロー

`default_job_id` は以下の2つのタイミングで設定・更新される。

1.  **初回ナレッジ処理完了時**:
    *   ユーザーが「ステップ1〜3」で**未登録フォルダ**のナレッジ化を初めて実行。
    *   `bedrock_kb_sync_lambda` がKnowledge Base同期後、`doctoknow-dev-folder-config` テーブルに新しい項目を作成し、その時の `job_id` を `default_job_id` として保存する。
2.  **ユーザーによる明示的な設定時**:
    *   フロントエンドの「デフォルトに設定」ボタン（既存機能）がクリックされた時。
    *   `job_creator.py` の `set_default_job_id` が呼び出され、`doctoknow-dev-folder-config` テーブルの `default_job_id` を更新する。

---

## 3. API仕様

### 3.1. `GET /api/folders` (既存APIの拡張)

*   **用途**: フォルダツリーと各フォルダの登録状態を取得する。
*   **レスポンス (変更後)**: 各フォルダオブジェクトに `is_registered` (boolean) と `default_job_id` (string | null) を追加する。

### 3.2. `POST /api/folder-management` (新規)

*   **用途**: フォルダの作成と削除を行う。
*   **リクエストボディ**:
    ```json
    {
      "action": "create" | "delete",
      "folder_path": "対象のフォルダパス"
    }
    ```
*   **成功レスポンス**: `200 OK` とメッセージ。
*   **失敗レスポンス (削除時)**: `400 Bad Request` とエラーメッセージ「データが存在するため削除できません。管理者に問い合わせてください。」

### 3.3. `GET /api/s3-presigned-urls` (新規)

*   **用途**: ファイルアップロード用の署名付きURLを生成する。
*   **クエリパラメータ**:
    *   `folder_path`: アップロード先のフォルダパス。
    *   `filenames`: アップロードするファイル名のカンマ区切りリスト。
*   **レスポンス**:
    ```json
    {
      "is_registered": true,
      "default_job_id": "20251105120000",
      "urls": {
        "file1.pdf": "https://...",
        "file2.pdf": "https://..."
      }
    }
    ```

### 3.4. `POST /api/trigger-processing` (新規)

*   **用途**: アップロード完了後、登録済みフォルダの自動処理を開始させる。
*   **リクエストボディ**:
    ```json
    {
      "folder_path": "対象のフォルダパス",
      "job_id": "使用するdefault_job_id",
      "uploaded_files": ["file1.pdf", "file2.pdf"]
    }
    ```
*   **レスポンス**: `202 Accepted` とメッセージ「処理を開始しました」。

---

## 4. バックエンド実装

### 4.1. 新規Lambda: `folder_management_lambda.py`

*   **責務**: 上記API仕様の3.1〜3.4で定義されたリクエストを処理する単一のLambda関数。
*   **主な機能**:
    *   `get_folder_tree_with_registration_status()`: フォルダツリーと登録状態を返す。
    *   `create_folder()`: S3に `.folder_marker` を作成してフォルダを表現。
    *   `delete_folder()`: フォルダが空か検証し、マーカーファイルを削除。
    *   `generate_presigned_urls()`: アップロード用URLを生成。
    *   `trigger_processing()`: `worker` Lambdaを呼び出して自動処理を開始。

### 4.2. 既存Lambda修正: `bedrock_kb_sync_lambda.py`

*   **責務追加**: 初回ナレッジ処理完了時に `doctoknow-dev-folder-config` テーブルに `default_job_id` を登録する。
*   **トリガー**: Step Functionsからの入力イベントに `is_new_folder: true` のようなフラグが含まれている場合に実行。

### 4.3. 既存Lambda修正: `worker.py`

*   **変更点**: `lambda_handler` に、`folder_management_lambda` からの非同期呼び出し（自動処理モード）に対応するロジックを追加。既存の `process_pdf_on_demand` を再利用する。

---

## 5. フロントエンド実装

### 5.1. `index.html`

*   「ステップ1」の前に「ステップ0: S3フォルダ・ファイル管理」セクションを追加。
*   フォルダツリー表示エリア、新規フォルダ作成ボタン、削除ボタン、ファイル選択 (`<input type="file" multiple>`)、アップロードボタンを配置。

### 5.2. `app.js`

*   **フォルダツリー**:
    *   取得したツリー情報を画面に描画。登録済みフォルダには特別なアイコンを表示。
    *   各フォルダに「新規作成」「削除」「ここにアップロード」ボタンを追加。
*   **ファイルアップロード**:
    *   `GET /api/s3-presigned-urls` を呼び出し。
    *   取得したURLを使い、S3へファイルを直接アップロード（マルチパート対応）。
    *   アップロード完了後、レスポンスに応じて `POST /api/trigger-processing` を呼び出すか、ユーザーに案内メッセージを表示。
*   **状態管理**: 取得したフォルダツリー情報（登録状態含む）をフロントエンド側でキャッシュし、APIへの不要な問い合わせを削減する。

---

## 6. DynamoDBスキーマ

### `doctoknow-dev-folder-config` テーブル

| 属性名 | 型 | 説明 |
| :--- | :--- | :--- |
| `folder_path` | String (PK) | フォルダパス (例: `生技資料/生技25`) |
| `default_job_id` | String | デフォルトで使用されるジョブID |
| `latest_job_id` | String | このフォルダで最後に実行されたジョブID |

---

## 7. ファイル修正・作成一覧

| 種別 | ファイルパス | 概要 |
| :--- | :--- | :--- |
| **新規** | `backend/folder_management_lambda.py` | フォルダ・ファイル操作の統合Lambda |
| **修正** | `backend/bedrock_kb_sync_lambda.py` | 初回ナレッジ処理時の `default_job_id` 登録機能を追加 |
| **修正** | `backend/worker.py` | 自動処理モードからの呼び出しに対応 |
| **修正** | `backend/folder_tree_helper.py` | 登録状態を含むフォルダツリーを返すように拡張 |
| **修正** | `frontend/index.html` | 「ステップ0」のUIセクションを追加 |
| **修正** | `frontend/app.js` | ステップ0の全機能（API呼び出し、UI操作）を実装 |
| **修正** | `frontend/style.css` | ステップ0のUIスタイルを追加 |
| **修正** | `cloudformation-doctoknow-template.json` | 新規LambdaとAPI Gatewayエンドポイントを定義 |
| **修正** | `deploy-doctoknow.ps1` | 新規Lambdaのデプロイに対応 |
