# CloudFormation テンプレート修正内容

**修正日**: 2025年11月5日  
**ファイル**: `cloudformation-doctoknow-template.json`  
**セクション**: `DynamoDBJobTable`

---

## 📋 修正概要

DynamoDB の `jobs-v2` テーブルスキーマを、フラット構造から **マルチフォルダ階層対応** に変更しました。

---

## 🔄 修正前後の比較

### 修正前（旧スキーマ）

```json
"DynamoDBJobTable": {
  "Type": "AWS::DynamoDB::Table",
  "Properties": {
    "TableName": { "Fn::Sub": "${ProjectName}-jobs-v2" },
    "AttributeDefinitions": [
      { "AttributeName": "job_id", "AttributeType": "S" },
      { "AttributeName": "file_name", "AttributeType": "S" }
    ],
    "KeySchema": [
      { "AttributeName": "job_id", "KeyType": "HASH" },
      { "AttributeName": "file_name", "KeyType": "RANGE" }
    ],
    "BillingMode": "PAY_PER_REQUEST"
  }
}
```

**特徴**:
- ❌ フォルダパス非対応
- ❌ フォルダ単位での検索不可
- ❌ GSI（二次インデックス）なし

### 修正後（新スキーマ）

```json
"DynamoDBJobTable": {
  "Type": "AWS::DynamoDB::Table",
  "Properties": {
    "TableName": { "Fn::Sub": "${ProjectName}-jobs-v2" },
    "AttributeDefinitions": [
      { "AttributeName": "job_id", "AttributeType": "S" },
      { "AttributeName": "folder_path#file_name", "AttributeType": "S" },
      { "AttributeName": "folder_path", "AttributeType": "S" }
    ],
    "KeySchema": [
      { "AttributeName": "job_id", "KeyType": "HASH" },
      { "AttributeName": "folder_path#file_name", "KeyType": "RANGE" }
    ],
    "GlobalSecondaryIndexes": [
      {
        "IndexName": "folder_path-index",
        "KeySchema": [
          { "AttributeName": "folder_path", "KeyType": "HASH" },
          { "AttributeName": "job_id", "KeyType": "RANGE" }
        ],
        "Projection": { "ProjectionType": "ALL" },
        "BillingMode": "PAY_PER_REQUEST"
      }
    ],
    "BillingMode": "PAY_PER_REQUEST"
  }
}
```

**特徴**:
- ✅ フォルダパス対応
- ✅ フォルダ単位でのジョブ検索可能
- ✅ GSI（`folder_path-index`）で高速クエリ

---

## 📊 主な変更点

### 1. AttributeDefinitions（属性定義）

| 修正前 | 修正後 | 理由 |
|--------|--------|------|
| `file_name` | `folder_path#file_name` | ファイル名の前にフォルダパスを付与 |
| - | `folder_path` | GSI用の新しい属性 |

### 2. KeySchema（主キー）

| 項目 | 修正前 | 修正後 | 理由 |
|-----|--------|--------|------|
| HASH キー | `job_id` | `job_id` | 変更なし |
| RANGE キー | `file_name` | `folder_path#file_name` | フォルダパスを含める |

### 3. GlobalSecondaryIndexes（新規追加）

**索引名**: `folder_path-index`

```json
{
  "IndexName": "folder_path-index",
  "KeySchema": [
    { "AttributeName": "folder_path", "KeyType": "HASH" },
    { "AttributeName": "job_id", "KeyType": "RANGE" }
  ],
  "Projection": { "ProjectionType": "ALL" },
  "BillingMode": "PAY_PER_REQUEST"
}
```

**用途**:
- 特定フォルダ配下の全ジョブを検索
- 複数ジョブでの Knowledge Base フィルター生成

**クエリ例**:
```python
response = table.query(
    IndexName='folder_path-index',
    KeyConditionExpression=Key('folder_path').eq('フォルダ1/フォルダ1-1')
)
# → フォルダ 1/フォルダ1-1 配下のすべてのジョブを取得
```

---

## ⚠️ 重要な影響事項

### DynamoDB テーブル再作成

DynamoDB の主キーは **変更できない** ため、以下が発生します：

1. **CloudFormation 適用時**:
   - 旧テーブル `jobs-v2`（スキーマ: `job_id` + `file_name`）が削除される
   - 新テーブル `jobs-v2`（スキーマ: `job_id` + `folder_path#file_name`）が作成される

2. **データについて**:
   - 既存データはすべて `jobs-v2-new`（仮置きテーブル）に安全に保管されています
   - CloudFormation 適用直後は `jobs-v2` は空の新テーブルになります
   - `reorganize_s3_and_migrate_db.py` でデータを復元します

### 実行手順

**重要**: 以下の順序に従ってください

```
1️⃣  CloudFormation テンプレート適用
    ↓
2️⃣  reorganize_s3_and_migrate_db.py 実行
    ↓
3️⃣  jobs-v2-new テーブル削除
```

詳細: `FINAL_MIGRATION_PROCEDURE.md` を参照

---

## 📈 スキーマ比較表

| 項目 | 修正前 | 修正後 |
|-----|--------|--------|
| **テーブル名** | `jobs-v2` | `jobs-v2` |
| **HASH キー** | `job_id` | `job_id` |
| **RANGE キー** | `file_name` | `folder_path#file_name` |
| **GSI** | なし | `folder_path-index` |
| **属性数** | 2 | 3（+`folder_path`） |
| **フォルダ検索** | ❌ 不可 | ✅ 可能 |
| **ジョブ検索精度** | 低い | 高い |

---

## 🔗 関連ドキュメント

- **実行手順**: `FINAL_MIGRATION_PROCEDURE.md`
- **全体仕様書**: `SPECIFICATION_MULTIPLE_FOLDER_HIERARCHY.md`
- **データ移行スクリプト**: `reorganize_s3_and_migrate_db.py`

---

**作成者**: GitHub Copilot  
**最終更新**: 2025年11月5日
