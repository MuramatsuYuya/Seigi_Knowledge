# CloudFormation テンプレート分割デプロイガイド

**更新日**: 2025-10-29  
**目的**: CloudFrontのWAFをus-east-1で管理し、その他のリソースをus-west-2で管理

---

## 📋 テンプレート構成

### 1. **cloudformation-waf-template.json** (us-east-1)
CloudFront用のWAFリソース：
- `AllowedIPSet`: IP許可リスト
- `WebACL`: WAFルール（IP制限 + レート制限）

**デプロイリージョン**: `us-east-1` ⚠️ **必須**

### 2. **cloudformation-doctoknow-template.json** (us-west-2)
その他すべてのAWSリソース：
- S3バケット（フロントエンド、データ）
- DynamoDB テーブル
- Lambda 関数
- API Gateway
- CloudFront（WAFと連携）

**デプロイリージョン**: `us-west-2`

---

## 📚 参考

- [CloudFormation 複数リージョン管理](https://docs.aws.amazon.com/cloudformation/latest/userguide/stacksets.html)
- [AWS WAF CloudFront 統合](https://docs.aws.amazon.com/waf/latest/developerguide/cloudfront-chapter.html)
- [AWS CLI リージョン指定](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-quickstart.html)

