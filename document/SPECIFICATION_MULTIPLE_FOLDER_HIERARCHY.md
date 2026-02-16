# PDF OCR システム - マルチフォルダ階層対応仕様書

**作成日**: 2025年11月5日  
**版号**: v1.0  
**ステータス**: 確定

---

## 📋 目次

1. [概要](#概要)
2. [S3フォルダ構造](#s3フォルダ構造)
3. [DynamoDB スキーマ設計](#dynamodb-スキーマ設計)
4. [ジョブID管理](#ジョブid管理)
5. [処理フロー](#処理フロー)
6. [Knowledge Base フィルター戦略](#knowledge-base-フィルター戦略)
7. [メタデータ構造](#メタデータ構造)
8. [API仕様](#api仕様)
9. [コード修正箇所](#コード修正箇所)

---

## 概要

### 現在の仕様
- **S3**: `PDF/ファイル.pdf` または `PDF/{job_id}/ファイル.pdf`（フラット構造）
- **ジョブ管理**: 1つのジョブID = 複数ファイル
- **出力**: `Transcript/{job_id}/`, `Knowledge/{job_id}/`

### 新しい仕様（変更後）
- **S3**: `PDF/フォルダ1/フォルダ1-1/ファイル.pdf`（階層構造をサポート）
- **ジョブ管理**: **各フォルダ経路ごとに別々のジョブIDを生成**
- **出力**: `Transcript/フォルダ1/フォルダ1-1/{job_id}/`, `Knowledge/フォルダ1/フォルダ1-1/{job_id}/`
- **DynamoDB**: `(job_id, folder_path, file_name)` の複合キー構造

---

## S3フォルダ構造

### ディレクトリツリー例

```
doctoknow-seigi25-data/
├── PDF/
│   ├── フォルダ1/
│   │   ├── フォルダ1-1/
│   │   │   ├── 資料1.pdf
│   │   │   └── 資料2.pdf
│   │   └── フォルダ1-2/
│   │       ├── フォルダ1-2-1/
│   │       │   └── 資料3.pdf
│   │       └── フォルダ1-2-2/
│   │           └── 資料4.pdf
│   ├── フォルダ2/
│   │   └── フォルダ2-1/
│   │       └── 資料5.pdf
│   └── フォルダ3/
│       └── 資料6.pdf
│
├── Transcript/
│   ├── フォルダ1/フォルダ1-1/
│   │   ├── {job_id_1}/
│   │   │   ├── 資料1.txt
│   │   │   └── 資料2.txt
│   │   └── {job_id_2}/  # 別のジョブID（再処理した場合など）
│   │       └── 資料1.txt
│   ├── フォルダ1/フォルダ1-2/フォルダ1-2-1/
│   │   └── {job_id_3}/
│   │       └── 資料3.txt
│   └── ...
│
├── Knowledge/
│   ├── フォルダ1/フォルダ1-1/
│   │   ├── {job_id_1}/
│   │   │   ├── 資料1_001.txt
│   │   │   ├── 資料1_001.txt.metadata.json
│   │   │   ├── 資料1_002.txt
│   │   │   ├── 資料1_002.txt.metadata.json
│   │   │   └── ...
│   │   └── {job_id_2}/
│   │       └── ...
│   └── ...
│
├── Prompts/
│   ├── フォルダ1/フォルダ1-1/
│   │   ├── {job_id_1}/
│   │   │   ├── transcript_prompt.txt
│   │   │   └── knowledge_prompt.txt
│   │   └── {job_id_2}/
│   │       ├── transcript_prompt.txt
│   │       └── knowledge_prompt.txt
│   ├── フォルダ1/フォルダ1-2/フォルダ1-2-1/
│   │   └── {job_id_3}/
│   │       ├── transcript_prompt.txt
│   │       └── knowledge_prompt.txt
│   └── ...
│
└── [その他のフォルダ]
```

### 重要なポイント

1. **PDF フォルダ**: 任意の深さのフォルダ階層に対応
   - 各ファイルのパスから `folder_path` を自動抽出
   - 例: `PDF/フォルダ1/フォルダ1-1/資料1.pdf` → `folder_path = "フォルダ1/フォルダ1-1"`

2. **Transcript/Knowledge/Prompts フォルダ**: S3パス内に `folder_path` と `job_id` の両方を含める
   - `Transcript/{folder_path}/{job_id}/ファイル.txt`
   - `Knowledge/{folder_path}/{job_id}/ファイル.txt`

---

## DynamoDB スキーマ設計

### ✅ テーブル: `jobs_v2` (実装完了)

> **実装状況**: ✅ **完了**
> - CloudFormation テンプレート: `cloudformation-doctoknow-template-v2.json` で定義
> - デプロイ状況: ✅ 完了 
> - データマイグレーション: ✅ 完了（361件を `jobs` から `jobs-v2-new` に移行）
> - スキーマ: 複合キー + GSI で実装済み

#### 主キー構成（複合キー）

| キー名 | 型 | 説明 | 例 |
|--------|-----|------|-----|
| `job_id` | String (PK) | ジョブID（YYYYMMDDhhmmss） | `20251105120000` |
| `folder_path#file_name` | String (SK) | フォルダパス + ファイル名（複合） | `フォルダ1/フォルダ1-1#資料1.pdf` |

#### 属性

| 属性名 | 型 | 説明 | 例 |
|--------|-----|------|-----|
| `folder_path` | String | S3内のフォルダパス | `フォルダ1/フォルダ1-1` |
| `file_name` | String | ファイル名 | `資料1.pdf` |
| `file_key` | String | S3キー（参照用） | `PDF/フォルダ1/フォルダ1-1/資料1.pdf` |
| `status` | String | ファイル処理ステータス | `queued`, `running`, `done`, `failed` |

#### GSI（Global Secondary Index）- ✅ 実装済み

**GSI1: `folder_path-index`**

| キー | 説明 |
|-----|------|
| PK | `folder_path` |
| SK | `job_id` |

**用途**: 特定のフォルダパス配下のすべてのジョブを取得する際に使用

---

## ジョブID管理

### ジョブ生成ロジック

#### 1. ジョブ作成時

**フロー**: 
```
1. ユーザーが「フォルダ1/フォルダ1-1」を選択（子フォルダを持たないフォルダのみ選択可能）
2. job_creator.py が以下を実行:
   a. S3 から PDF/フォルダ1/フォルダ1-1/ 配下のすべての .pdf ファイルを検出
   b. ユーザーが特定のPDFファイルを選択する場合はそれを絞り込む（オプション）
      - 選択しない場合は、検出されたすべてのファイルを対象
   c. 新規 job_id を生成（YYYYMMDDhhmmss）
   d. 検出されたすべてのファイルをDynamoDBに登録
      - PK: job_id
      - SK: folder_path#file_name
      - 属性: folder_path, file_name, file_key, status, ...
   e. Prompts/{folder_path}/{job_id}/ にプロンプトを保存
   f. Step Functions を実行
```

**コード変更点（job_creator.py）**:

```python
def get_pdf_files_in_folder(folder_path):
    """
    指定フォルダ配下のすべてのPDFファイルを再帰的に取得
    
    Args:
        folder_path: "フォルダ1/フォルダ1-1" (先頭の PDF/ は含めない)
    
    Returns:
        [
            {"file_key": "PDF/フォルダ1/フォルダ1-1/資料1.pdf", "folder_path": "フォルダ1/フォルダ1-1"},
            ...
        ]
    """
    # S3 list_objects_v2 で "PDF/{folder_path}/" を Prefix に指定
    # 再帰的に探索

def register_job_in_dynamodb_v2(job_id, folder_path, pdf_files):
    """
    新スキーマでジョブ登録
    
    Args:
        job_id: "20251105120000"
        folder_path: "フォルダ1/フォルダ1-1"
        pdf_files: [
            {"file_key": "PDF/フォルダ1/フォルダ1-1/資料1.pdf", "file_name": "資料1.pdf"},
            ...
        ]
    """
    for pdf_file in pdf_files:
        jobs_table.put_item(Item={
            'job_id': job_id,
            'folder_path#file_name': f"{folder_path}#{pdf_file['file_name']}",
            'folder_path': folder_path,
            'file_name': pdf_file['file_name'],
            'file_key': pdf_file['file_key'],
            'status': 'queued',
            'processing_mode': 'full',
            'last_update': datetime.now(JST).isoformat(),
            'message': 'Job queued for processing'
        })
```

#### 2. フォルダ選択ルール

**ナレッジ化（PDF処理）時:**
- 「子フォルダを持つフォルダ」は選択不可（リーフフォルダのみ選択可能）
  - 例: 「フォルダ1」「フォルダ1/フォルダ1-2」は選択不可
  - 例: 「フォルダ1/フォルダ1-1」「フォルダ1/フォルダ1-2/フォルダ1-2-1」は選択可能
- 1つのジョブにつき1つのフォルダパスのみ対応
- 複数ジョブを並列実行はしない

**AIへの質問時:**
- 「子フォルダを持つフォルダ」も選択可能（親フォルダ配下のすべてのソースを対象）
- 複数フォルダの指定は不可（1つのフォルダを選択して検索）

---

## 処理フロー

### 全体フロー図

```
┌─────────────────────────────────────────────────────────────┐
│ Step 1: ジョブ作成（job_creator.py）                          │
├─────────────────────────────────────────────────────────────┤
│ 1. POST /api/job { folder_path, prompts }                    │
│ 2. S3 から PDF/{folder_path}/ 配下のファイルを検出           │
│ 3. job_id を生成                                               │
│ 4. DynamoDB に登録（複合キー: job_id + folder_path#file_name）│
│ 5. Step Functions を実行                                       │
│ 6. Prompts/{job_id}/ に プロンプトを保存                      │
└──────────────────┬────────────────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────────────────────────┐
│ Step 2: ファイル処理（worker.py）                             │
├─────────────────────────────────────────────────────────────┤
│ 1. Step Functions が各ファイルを worker に渡す                │
│ 2. worker が以下を実行:                                        │
│    a. PDF を S3 から読み込み                                  │
│    b. Bedrock でトランスクリプション                          │
│    c. Transcript/{folder_path}/{job_id}/file.txt に保存      │
│    d. Bedrock でナレッジ抽出                                  │
│    e. Knowledge/{folder_path}/{job_id}/file_*.txt に保存     │
│    f. メタデータを Knowledge/*.txt.metadata.json に保存       │
│ 3. DynamoDB ステータスを更新（status: done）                 │
└──────────────────┬────────────────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────────────────────────┐
│ Step 3: Knowledge Base 同期（bedrock_kb_sync_lambda.py）     │
├─────────────────────────────────────────────────────────────┤
│ 1. 最後のファイル処理完了時にトリガー                          │
│ 2. Bedrock Knowledge Base を同期                             │
│ 3. Knowledge/{folder_path}/{job_id}/ 配下のファイルを同期    │
└──────────────────┬────────────────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────────────────────────┐
│ Step 4: ナレッジ検索（knowledge_querier.py）                  │
├─────────────────────────────────────────────────────────────┤
│ 1. GET /api/query { folder_path (or job_id), query_text }    │
│ 2. パラメータから job_id を決定                               │
│    - job_id が指定されていれば優先                           │
│    - folder_path が指定されていれば folder_path から job_id を取得 │
│ 3. DynamoDB から folder_path に対応するすべての job_id を検出│
│ 4. Bedrock KB を クエリ（メタデータ job_id でフィルター）     │
│ 5. 結果を返す                                                 │
└─────────────────────────────────────────────────────────────┘
```

---

## Knowledge Base フィルター戦略

### 実装案: オプション3（ハイブリッド + メタデータ）

#### メタデータにjob_idを含める

**ファイルパス**:
```
Knowledge/フォルダ1/フォルダ1-1/{job_id}/{file_001}.txt.metadata.json
```

**メタデータ内容**:
```json
{
  "FileName": "資料1.pdf",
  "s3Key": "PDF/フォルダ1/フォルダ1-1/資料1.pdf",
  "folder_path": "フォルダ1/フォルダ1-1",
  "job_id": "20251105120000",
  "source_uri": "s3://doctoknow-seigi25-data/PDF/フォルダ1/フォルダ1-1/資料1.pdf",
  "stated_in_document": "p.5"
}
```

#### Bedrock Knowledge Base クエリ時のフィルター

**フロー1: ジョブID指定での検索**

```python
# ユーザーが job_id を直接指定
GET /api/query?job_id=20251105120000&query=...

# バックエンド（knowledge_querier.py）
filter_config = {
    'equals': {
        'key': 'metadata.job_id',
        'value': '20251105120000'
    }
}

# Bedrock KB をクエリ
response = bedrock_runtime.retrieve_and_generate(
    input={'text': query},
    retrieveAndGenerateConfiguration={
        'type': 'KNOWLEDGE_BASE',
        'knowledgeBaseConfiguration': {
            'knowledgeBaseId': KNOWLEDGE_BASE_ID,
            'modelArn': BEDROCK_MODEL_ARN,
            'retrievalConfiguration': {
                'vectorSearchConfiguration': {
                    'numberOfResults': 20,
                    'filter': filter_config
                }
            }
        }
    }
)
```

**フロー2: フォルダパス指定での検索（複数job_id対応）**

```python
# ユーザーがフォルダパス を指定
GET /api/query?folder_path=フォルダ1/フォルダ1-1&query=...

# バックエンド
# 1. DynamoDB から folder_path に対応するすべての job_id を取得
response = jobs_table.query(
    IndexName='folder_path-index',
    KeyConditionExpression=Key('folder_path').eq('フォルダ1/フォルダ1-1')
)
job_ids = [item['job_id'] for item in response['Items']]
# → ['20251105120000', '20251105130000', ...]

# 2. 複数 (folder_path, job_id) ペアを orAll でつなげてフィルター
# メタデータに folder_path と job_id の両方を含める
filter_config = {
    'orAll': [
        {
            'and': [
                {'equals': {'key': 'metadata.folder_path', 'value': folder_path}},
                {'equals': {'key': 'metadata.job_id', 'value': job_id}}
            ]
        }
        for job_id in job_ids
    ]
}

# 3. Bedrock KB をクエリ
```

#### 複合フォルダ検索の例

```python
# 「フォルダ1」配下のすべてのソースから検索（親フォルダ指定）
GET /api/query?folder_path=フォルダ1&query=...

# バックエンド処理：
# 1. 「フォルダ1」で始まる folder_path を検出
#    → DynamoDB スキャンまたは アプリ層で処理
#    → ["フォルダ1/フォルダ1-1", "フォルダ1/フォルダ1-2/フォルダ1-2-1", ...]
# 2. 各 folder_path ごとに job_id を取得
# 3. (folder_path, job_id) のペアを orAll でつなげてフィルター

filter_config = {
    'orAll': [
        {
            'and': [
                {'equals': {'key': 'metadata.folder_path', 'value': 'フォルダ1/フォルダ1-1'}},
                {'equals': {'key': 'metadata.job_id', 'value': '20251105120000'}}
            ]
        },
        {
            'and': [
                {'equals': {'key': 'metadata.folder_path', 'value': 'フォルダ1/フォルダ1-2/フォルダ1-2-1'}},
                {'equals': {'key': 'metadata.job_id', 'value': '20251105130000'}}
            ]
        }
    ]
}
```

---

## メタデータ構造

### Knowledge ファイルのメタデータ

**ファイルパス**:
```
Knowledge/{folder_path}/{job_id}/{filename}_001.txt.metadata.json
```

**メタデータスキーマ**:

```json
{
  "FileName": "string - 元のPDFファイル名",
  "s3Key": "string - 元のS3キー（PDF/...）",
  "folder_path": "string - フォルダパス（Bedrock フィルター用）",
  "job_id": "string - ジョブID（Bedrock フィルター用）",
  "source_uri": "string - 元のPDFのS3 URI",
  "stated_in_document": "string - ページ番号など"
}
```

**例**:

```json
{
  "FileName": "資料1.pdf",
  "s3Key": "PDF/フォルダ1/フォルダ1-1/資料1.pdf",
  "folder_path": "フォルダ1/フォルダ1-1",
  "job_id": "20251105120000",
  "source_uri": "s3://doctoknow-seigi25-data/PDF/フォルダ1/フォルダ1-1/資料1.pdf",
  "stated_in_document": "p.10"
}
```

### worker.py での保存処理

```python
def save_metadata_to_s3_v2(s3_key, folder_path, job_id, original_file_name, 
                          original_s3_key, stated_in_document="-"):
    """
    Knowledge Base メタデータを保存（job_id, folder_path を含める）
    
    Args:
        s3_key: "Knowledge/{folder_path}/{job_id}/file_001.txt.metadata.json"
        folder_path: "フォルダ1/フォルダ1-1"
        job_id: "20251105120000"
        original_file_name: "資料1.pdf"
        original_s3_key: "PDF/フォルダ1/フォルダ1-1/資料1.pdf"
        stated_in_document: "p.5"
    """
    metadata = {
        "FileName": original_file_name,
        "s3Key": original_s3_key,
        "folder_path": folder_path,
        "job_id": job_id,
        "source_uri": f"s3://{S3_BUCKET}/{original_s3_key}",
        "stated_in_document": stated_in_document
    }
    
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=json.dumps(metadata, ensure_ascii=False, indent=2),
        ContentType='application/json'
    )
```

---

## API仕様

### 1. ジョブ作成API（job_creator.py）

#### エンドポイント

```
POST /api/job
```

#### リクエストボディ

```json
{
  "folder_path": "フォルダ1/フォルダ1-1",
  "transcript_prompt": "以下のPDFテキストを日本語で文字起こししてください...",
  "knowledge_prompt": "以下の文字起こし結果からナレッジを抽出してください...",
  "pdfFiles": ["資料1.pdf", "資料2.pdf"]
}
```

**パラメータ説明**:
- `folder_path`: 必須。子フォルダを持たないフォルダパスのみ選択可能
- `transcript_prompt`: 必須
- `knowledge_prompt`: 必須
- `pdfFiles`: オプション。指定した場合、これらのファイルのみを処理。省略時は `folder_path` 配下のすべてのPDFを処理

#### レスポンス（成功）

```json
{
  "statusCode": 202,
  "body": {
    "job_id": "20251105120000",
    "folder_path": "フォルダ1/フォルダ1-1",
    "pdf_count": 2,
    "execution_arn": "arn:aws:states:...",
    "message": "Job started via Step Functions"
  }
}
```

#### エラーレスポンス

```json
{
  "statusCode": 400,
  "error": "folder_path and prompts are required"
}
```

または

```json
{
  "statusCode": 400,
  "error": "Selected folder has child folders. Please select a leaf folder only."
}
```

#### バリデーション

- `folder_path` が子フォルダを持つ場合はエラーを返す
- `pdfFiles` が指定される場合、すべてのファイルが `folder_path` 配下に存在することを確認

---

### 2. ナレッジ検索API（knowledge_querier.py）

#### エンドポイント

```
POST /api/query
```

#### リクエストボディ

**パターン1: ジョブID指定**

```json
{
  "job_id": "20251105120000",
  "query": "システムの構成について教えてください",
  "chat_session_id": "session-123"
}
```

**パターン2: フォルダパス指定**

```json
{
  "folder_path": "フォルダ1/フォルダ1-1",
  "query": "システムの構成について教えてください",
  "chat_session_id": "session-123"
}
```

#### 処理ロジック

```python
def lambda_handler(event, context):
    """
    process:
    1. job_id が指定されていれば、そちらを優先
    2. folder_path が指定されていれば、DynamoDB から job_id を取得
    3. いずれも指定されていなければ エラー
    
    DynamoDB query:
    - folder_path 指定の場合
      IndexName='folder_path-index'
      KeyConditionExpression=Key('folder_path').eq(folder_path)
      → 複数 job_id を取得し、orAll でフィルター
    """
```

#### レスポンス

```json
{
  "statusCode": 200,
  "body": {
    "answer": "システムの構成は以下の通りです...",
    "sources": [
      {
        "file_name": "資料1.pdf",
        "file_url": "https://s3.amazonaws.com/...",
        "source_uri": "s3://bucket/PDF/フォルダ1/フォルダ1-1/資料1.pdf",
        "page": "p.10"
      }
    ]
  }
}
```

---

### 3. フォルダ一覧取得API（新規）

#### エンドポイント

```
GET /api/folders
```

#### レスポンス

```json
{
  "statusCode": 200,
  "body": {
    "folders": [
      {
        "path": "フォルダ1",
        "children": [
          {
            "path": "フォルダ1/フォルダ1-1",
            "children": [],
            "file_count": 2,
            "latest_job_id": "20251105120000"
          },
          {
            "path": "フォルダ1/フォルダ1-2",
            "children": [
              {
                "path": "フォルダ1/フォルダ1-2/フォルダ1-2-1",
                "children": [],
                "file_count": 1,
                "latest_job_id": "20251105130000"
              }
            ]
          }
        ]
      },
      {
        "path": "フォルダ2",
        "children": []
      }
    ]
  }
}
```

---

### 4. ジョブ状態取得API（result_fetcher.py - 修正）

#### エンドポイント

```
GET /api/results/{job_id}
or
GET /api/results?folder_path=...
```

#### リクエストパラメータ

| パラメータ | 型 | 説明 | 例 |
|-----------|-----|------|-----|
| `job_id` | String | ジョブID | `20251105120000` |
| `folder_path` | String | フォルダパス | `フォルダ1/フォルダ1-1` |

#### レスポンス

```json
{
  "statusCode": 200,
  "body": {
    "job_id": "20251105120000",
    "folder_path": "フォルダ1/フォルダ1-1",
    "transcript_prompt": "...",
    "knowledge_prompt": "...",
    "results": [
      {
        "file_name": "資料1.pdf",
        "status": "done",
        "last_update": "2025-11-05T12:05:00+09:00",
        "transcript": "文字起こしテキスト...",
        "knowledge": "ナレッジテキスト...",
        "file_url": "https://s3.amazonaws.com/..."
      }
    ]
  }
}
```

---

## コード修正箇所

### 🔄 バックエンド実装（未実装）

| ファイル | 修正内容 | 優先度 | 状態 |
|---------|---------|--------|------|
| `job_creator.py` | フォルダパス対応、composite key登録 | 高 | ⏳ 未実装 |
| `worker.py` | S3パス更新、メタデータ追加 | 高 | ⏳ 未実装 |
| `knowledge_querier.py` | フォルダパスフィルター、API実装 | 高 | ⏳ 未実装 |
| `result_fetcher.py` | GSI クエリ対応 | 中 | ⏳ 未実装 |

---

## フロントエンド実装（必須）

### 現状の問題点

現在のフロントエンド (`index.html`, `app.js`, `knowledge-query.html`) は**旧仕様のまま**で、以下の機能が未実装です：

#### ❌ 未実装機能

1. **フォルダ選択UI** (`index.html`)
   - S3フォルダ階層の表示
   - リーフフォルダ（子フォルダを持たないフォルダ）の選択
   - 現在: PDFファイルの直接選択のみ

2. **デフォルトJOB_ID設定機能** (`index.html` - ナレッジ作成ページ)
   - 作成したジョブをデフォルトJOB_IDとして設定
   - 既存のJOB_ID選択ドロップダウンを活用してデフォルト設定
   - ナレッジ検索ページに引き継ぐ

3. **フォルダパスでの検索** (`knowledge-query.html`)
   - フォルダパス指定でのナレッジ検索
   - JOB_ID指定は任意項目（目立たせない）
   - 現在: JOB_ID指定のみ

---

### 実装仕様

#### 1. `index.html` / `app.js` の修正（ナレッジ作成ページ）

##### 🎯 要件
- フォルダツリーを表示し、リーフフォルダを選択可能にする
- ジョブ作成後、作成したJOB_IDをデフォルトとして設定できる
- 既存のJOB_ID選択ドロップダウンを活用する

##### 追加UI要素

```html
<!-- フォルダ選択セクション（PDF選択の前に追加） -->
<div class="folder-selection-section">
    <h3>📁 ステップ1: フォルダ選択</h3>
    <p>処理対象のフォルダを選択してください（リーフフォルダのみ選択可能）</p>
    <button id="fetchFolderTreeBtn" class="btn">フォルダツリーを取得</button>
    <div id="folderTreeContainer" class="folder-tree" style="display: none;">
        <!-- 動的に生成されるフォルダツリー -->
    </div>
    <div id="selectedFolderInfo" style="display: none;">
        <strong>✓ 選択中:</strong> <span id="selectedFolderPath" class="selected-path"></span>
    </div>
</div>

<!-- 既存のPDF選択セクション（フォルダ選択後に有効化） -->
<div class="pdf-selection-section" id="pdfSelectionSection" style="opacity: 0.5; pointer-events: none;">
    <h3>📄 ステップ2: PDF選択（オプション）</h3>
    <!-- 既存のPDF選択UI -->
</div>

<!-- デフォルトJOB_ID設定（ジョブ作成後に表示） -->
<div id="defaultJobIdSection" class="default-jobid-section" style="display: none;">
    <div class="success-banner">
        <h4>✅ ジョブ作成完了</h4>
        <p>JOB_ID: <strong id="createdJobId"></strong></p>
        <label>
            <input type="checkbox" id="setAsDefaultJobId" checked>
            このJOB_IDをデフォルトとして設定（ナレッジ検索ページで使用）
        </label>
        <button id="goToQueryPageBtn" class="btn btn-primary">
            🔍 ナレッジ検索ページへ
        </button>
    </div>
</div>
```

##### JavaScript実装

```javascript
class DoctoKnowApp {
    constructor(config = {}) {
        // 既存のコード...
        this.selectedFolderPath = null;
        this.createdJobId = null;
    }
    
    // フォルダツリー取得
    async fetchFolderTree() {
        this.showLoading('フォルダツリーを取得中...');
        try {
            const response = await fetch(`${this.apiEndpoint}/api/folders`, {
                headers: { 'Authorization': `Bearer ${this.accessToken}` }
            });
            const data = await response.json();
            this.renderFolderTree(data.body.folders);
            document.getElementById('folderTreeContainer').style.display = 'block';
        } catch (error) {
            this.showError('フォルダツリーの取得に失敗しました');
        }
    }
    
    // フォルダツリーをレンダリング（リーフフォルダのみ選択可能）
    renderFolderTree(folders, parentElement = null) {
        const container = parentElement || document.getElementById('folderTreeContainer');
        container.innerHTML = '';
        
        const renderNode = (folder, level = 0) => {
            const isLeaf = !folder.children || folder.children.length === 0;
            const folderEl = document.createElement('div');
            folderEl.className = `folder-item level-${level} ${isLeaf ? 'leaf' : 'parent'}`;
            folderEl.style.paddingLeft = `${level * 20}px`;
            
            const icon = isLeaf ? '📄' : '📁';
            const folderName = folder.path.split('/').pop();
            folderEl.innerHTML = `${icon} ${folderName}`;
            
            if (isLeaf) {
                folderEl.classList.add('selectable');
                folderEl.addEventListener('click', () => this.selectFolder(folder.path));
            } else {
                folderEl.classList.add('non-selectable');
                folderEl.title = '子フォルダがあるため選択できません';
            }
            
            container.appendChild(folderEl);
            
            // 子フォルダを再帰的にレンダリング
            if (folder.children && folder.children.length > 0) {
                folder.children.forEach(child => renderNode(child, level + 1));
            }
        };
        
        folders.forEach(folder => renderNode(folder));
    }
    
    // フォルダ選択
    selectFolder(folderPath) {
        // 既存の選択をクリア
        document.querySelectorAll('.folder-item.selected').forEach(el => {
            el.classList.remove('selected');
        });
        
        // 新しい選択をハイライト
        event.target.classList.add('selected');
        
        this.selectedFolderPath = folderPath;
        document.getElementById('selectedFolderPath').textContent = folderPath;
        document.getElementById('selectedFolderInfo').style.display = 'block';
        
        // PDF選択セクションを有効化
        const pdfSection = document.getElementById('pdfSelectionSection');
        pdfSection.style.opacity = '1';
        pdfSection.style.pointerEvents = 'auto';
        
        console.log(`フォルダ選択: ${folderPath}`);
    }
    
    // ジョブ作成（修正版）
    async submitJob() {
        if (!this.selectedFolderPath) {
            this.showError('フォルダを選択してください');
            return;
        }
        
        const requestBody = {
            folder_path: this.selectedFolderPath,
            transcript_prompt: this.elements.transcriptPrompt.value,
            knowledge_prompt: this.elements.knowledgePrompt.value
        };
        
        // 選択されたPDFがあれば追加（オプション）
        if (this.selectedPdfs.length > 0) {
            requestBody.pdfFiles = this.selectedPdfs;
        }
        
        try {
            const response = await fetch(`${this.apiEndpoint}/api/job`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${this.accessToken}`
                },
                body: JSON.stringify(requestBody)
            });
            
            const data = await response.json();
            this.createdJobId = data.body.job_id;
            
            // デフォルトJOB_ID設定セクションを表示
            document.getElementById('createdJobId').textContent = this.createdJobId;
            document.getElementById('defaultJobIdSection').style.display = 'block';
            
            this.startPolling(this.createdJobId);
        } catch (error) {
            this.showError('ジョブの作成に失敗しました');
        }
    }
    
    // ナレッジ検索ページへ移動
    goToQueryPage() {
        const setAsDefault = document.getElementById('setAsDefaultJobId').checked;
        
        if (setAsDefault) {
            // localStorage にデフォルトJOB_IDを保存
            localStorage.setItem('default_job_id', this.createdJobId);
            localStorage.setItem('default_folder_path', this.selectedFolderPath);
        }
        
        // URLパラメータでJOB_IDを引き継ぐ
        window.location.href = `knowledge-query.html?jobId=${this.createdJobId}`;
    }
}
```

##### CSS追加

```css
.folder-tree {
    border: 1px solid #ddd;
    padding: 10px;
    max-height: 400px;
    overflow-y: auto;
    background: #f9f9f9;
    margin-top: 10px;
}

.folder-item {
    padding: 8px;
    margin: 2px 0;
    cursor: default;
    border-radius: 4px;
    transition: background 0.2s;
}

.folder-item.selectable {
    cursor: pointer;
}

.folder-item.selectable:hover {
    background: #e3f2fd;
}

.folder-item.selected {
    background: #2196f3;
    color: white;
    font-weight: bold;
}

.folder-item.non-selectable {
    color: #999;
    font-style: italic;
}

.selected-path {
    color: #2196f3;
    font-weight: bold;
}

.default-jobid-section {
    margin-top: 20px;
    padding: 20px;
    background: #e8f5e9;
    border-radius: 8px;
    border-left: 4px solid #4caf50;
}

.success-banner h4 {
    margin-top: 0;
    color: #2e7d32;
}
```

---

#### 2. `knowledge-query.html` / `knowledge-query.js` の修正（ナレッジ検索ページ）

##### 🎯 要件
- デフォルトJOB_IDを自動設定（localStorage または URLパラメータから）
- JOB_ID入力欄は目立たせない（詳細設定として折りたたみ可能）
- フォルダパス指定での検索をメイン機能として表示

##### 追加UI要素

```html
<!-- メイン検索コントロール -->
<div class="search-config">
    <h3>🔍 検索設定</h3>
    
    <!-- フォルダパス表示（メイン） -->
    <div class="main-search-info">
        <label>検索対象:</label>
        <div class="search-target-display">
            <span id="currentFolderPath" class="folder-path-badge">
                生技資料/生技25/MC巻き線ライン
            </span>
            <span class="job-info">(JOB_ID: <span id="currentJobId">20251104093044</span>)</span>
        </div>
    </div>
    
    <!-- 詳細設定（折りたたみ可能） -->
    <details class="advanced-settings">
        <summary>⚙️ 詳細設定</summary>
        <div class="advanced-content">
            <div class="form-group">
                <label>JOB_ID指定（任意）:</label>
                <input 
                    type="text" 
                    id="jobIdField" 
                    placeholder="自動設定されています"
                    class="form-input-small"
                >
                <small class="help-text">
                    特定のJOB_IDで検索する場合のみ入力してください
                </small>
            </div>
            
            <div class="form-group">
                <label>フォルダパス指定:</label>
                <select id="folderPathSelect" class="form-select">
                    <option value="">-- JOB_IDのフォルダを使用 --</option>
                    <!-- 動的に生成 -->
                </select>
            </div>
        </div>
    </details>
</div>
```

##### JavaScript実装

```javascript
class KnowledgeQueryApp {
    constructor(config = {}) {
        // 既存のコード...
        this.defaultJobId = null;
        this.defaultFolderPath = null;
    }
    
    async initialize() {
        // デフォルトJOB_IDを設定
        await this.loadDefaultJobId();
        
        // フォルダリストを取得
        await this.loadFolderList();
        
        // 既存の初期化処理...
    }
    
    // デフォルトJOB_IDを読み込み
    async loadDefaultJobId() {
        // 1. URLパラメータをチェック
        const urlParams = new URLSearchParams(window.location.search);
        const jobIdFromUrl = urlParams.get('jobId');
        
        if (jobIdFromUrl) {
            this.defaultJobId = jobIdFromUrl;
            console.log('URLパラメータからJOB_ID取得:', jobIdFromUrl);
        } else {
            // 2. localStorageをチェック
            this.defaultJobId = localStorage.getItem('default_job_id');
            this.defaultFolderPath = localStorage.getItem('default_folder_path');
        }
        
        // UIに反映
        if (this.defaultJobId) {
            document.getElementById('currentJobId').textContent = this.defaultJobId;
            document.getElementById('jobIdField').placeholder = this.defaultJobId;
        }
        
        if (this.defaultFolderPath) {
            document.getElementById('currentFolderPath').textContent = this.defaultFolderPath;
        } else if (this.defaultJobId) {
            // JOB_IDからフォルダパスを取得
            await this.fetchFolderPathFromJobId(this.defaultJobId);
        }
    }
    
    // JOB_IDからフォルダパスを取得
    async fetchFolderPathFromJobId(jobId) {
        try {
            const response = await fetch(
                `${this.apiEndpoint}/api/results/${jobId}`,
                { headers: { 'Authorization': `Bearer ${this.accessToken}` } }
            );
            const data = await response.json();
            
            if (data.body && data.body.folder_path) {
                this.defaultFolderPath = data.body.folder_path;
                document.getElementById('currentFolderPath').textContent = this.defaultFolderPath;
            }
        } catch (error) {
            console.error('フォルダパスの取得に失敗:', error);
        }
    }
    
    // クエリ送信（修正版）
    async sendQuery(queryText) {
        const requestBody = {
            query: queryText,
            chat_session_id: this.sessionId
        };
        
        // 詳細設定からJOB_IDまたはフォルダパスを取得
        const manualJobId = document.getElementById('jobIdField').value.trim();
        const manualFolderPath = document.getElementById('folderPathSelect').value;
        
        if (manualJobId) {
            // 手動指定のJOB_IDを優先
            requestBody.job_id = manualJobId;
        } else if (manualFolderPath) {
            // 手動指定のフォルダパス
            requestBody.folder_path = manualFolderPath;
        } else if (this.defaultFolderPath) {
            // デフォルトのフォルダパス
            requestBody.folder_path = this.defaultFolderPath;
        } else if (this.defaultJobId) {
            // デフォルトのJOB_ID
            requestBody.job_id = this.defaultJobId;
        } else {
            this.showError('検索対象が設定されていません');
            return;
        }
        
        // クエリ送信
        try {
            const response = await fetch(`${this.apiEndpoint}/api/query`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${this.accessToken}`
                },
                body: JSON.stringify(requestBody)
            });
            
            const data = await response.json();
            this.displayAnswer(data.body);
        } catch (error) {
            this.showError('クエリの送信に失敗しました');
        }
    }
}
```

##### CSS追加

```css
.search-config {
    background: #f5f5f5;
    padding: 16px;
    border-radius: 8px;
    margin-bottom: 20px;
}

.main-search-info {
    margin-bottom: 12px;
}

.folder-path-badge {
    display: inline-block;
    background: #2196f3;
    color: white;
    padding: 6px 12px;
    border-radius: 4px;
    font-weight: bold;
}

.job-info {
    color: #666;
    font-size: 0.9em;
    margin-left: 8px;
}

.advanced-settings {
    margin-top: 16px;
    border-top: 1px solid #ddd;
    padding-top: 12px;
}

.advanced-settings summary {
    cursor: pointer;
    color: #666;
    font-size: 0.9em;
}

.advanced-content {
    margin-top: 12px;
    padding: 12px;
    background: white;
    border-radius: 4px;
}

.help-text {
    display: block;
    color: #999;
    font-size: 0.85em;
    margin-top: 4px;
}
```

---

### 実装優先順位

| 機能 | 優先度 | 実装場所 |
|-----|--------|----------|
| フォルダ選択UI | 🔴 最高 | `index.html` |
| デフォルトJOB_ID設定 | 🔴 最高 | `index.html` (ジョブ作成後) |
| デフォルトJOB_ID読み込み | 🔴 最高 | `knowledge-query.html` |
| JOB_ID詳細設定 | 🟡 中 | `knowledge-query.html` (折りたたみ) |
| フォルダパス検索 | 🟡 中 | `knowledge-query.js` |

---

### 5. CloudFormation テンプレート

#### ✅ 実装完了

| 項目 | 状態 |
|-----|------|
| DynamoDBJobTable追加 | ✅ 完了 |
| IAMロール更新 | ✅ 完了 |
| Lambda環境変数更新 | ✅ 完了 |
| Outputs更新 | ✅ 完了 |

---

## 実装状況

### ✅ 完了済み

- [x] CloudFormation テンプレート更新（DynamoDBJobTable追加）
- [x] DynamoDB スキーマ設計（複合キー + GSI）
- [x] データマイグレーション（jobs → jobs-v2）
- [x] S3 ファイル階層構造への移行

### 🔄 実装中・未実装

| コンポーネント | 状態 | 備考 |
|--------------|------|------|
| Backend (job_creator.py) | ⏳ 未実装 | フォルダパス対応が必要 |
| Backend (worker.py) | ⏳ 未実装 | S3パス・メタデータ更新が必要 |
| Backend (knowledge_querier.py) | ⏳ 未実装 | フォルダパスフィルター実装が必要 |
| Backend (result_fetcher.py) | ⏳ 未実装 | GSI クエリ対応が必要 |
| **Frontend (index.html/app.js)** | ❌ **未実装** | **フォルダ選択UI が必要** |
| **Frontend (knowledge-query)** | ❌ **未実装** | **フォルダパス・デフォルトJOB_ID設定が必要** |

---

**作成者**: GitHub Copilot  
**最終更新**: 2025年11月5日

