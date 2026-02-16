# Cognito メール送信トラブルシューティングガイド

## 🔍 考えられる原因

### 1. **SES Sandbox Mode 制限** ⚠️ (最も可能性が高い)
- AWS SES は初期状態で **Sandbox モード**
- Sandbox では、**検証済みメールアドレスにのみ** メール送信可能
- Cognito が使用している SES も同じ制限の影響を受ける

**確認方法:**
```
AWS マネジメントコンソール → SES → Sandbox 状態を確認
```

**解決策:**
- AWS SES Sandbox から本番環境への昇格をリクエスト
- または、テスト用メールアドレスを SES で検証

---

### 2. **メール送信元が設定されていない**
Cognito のデフォルト設定では、送信元メールアドレスが明示的に設定されていない可能性

**CloudFormation テンプレートの確認:**
```json
"EmailConfiguration": {
  "EmailSendingAccount": "COGNITO_DEFAULT"
  // ← SourceArn や From が設定されていない
}
```

---

### 3. **IAM ロール権限不足**
Cognito がメール送信権限を持たない

---

## ✅ 推奨される解決策

### **方法A: SES Sandbox から昇格（本番環境用）**
1. AWS Support に昇格リクエストを送信
2. ビジネスユースケースを説明
3. 承認待機（通常1-2営業日）

### **方法B: テストメール検証（開発環境用・早期テスト）**
```bash
# 使用するテストメールアドレスを SES で検証
aws ses verify-email-identity --email-address test-user@ad.melco.co.jp --region us-west-2
```

ユーザーが登録時に使用するメールアドレスを事前に SES で検証しておく

### **方法C: CloudFormation で From アドレスを明示的に設定**
```json
"EmailConfiguration": {
  "EmailSendingAccount": "COGNITO_DEFAULT",
  "SourceArn": "arn:aws:ses:us-west-2:ACCOUNT_ID:identity/no-reply@ad.melco.co.jp"
}
```

---

## 🧪 テスト手順

### **1. SES Sandbox 状態確認**
```
AWS コンソール → SES → Account dashboard
→ "Account sending limit" セクションを確認
→ "Sandbox" または "Production" を表示
```

### **2. 検証済みメール一覧確認**
```
AWS コンソール → SES → Verified identities
```

### **3. Cognito ユーザー確認**
```bash
aws cognito-idp list-users --user-pool-id us-west-2_oB2UtXYeW --region us-west-2
```

---

## 📝 次のステップ

**推奨順序:**
1. ✅ SES Sandbox 状態を確認
2. ✅ 検証済みメール一覧を確認
3. ✅ テストメール検証（早期テスト用）
4. ✅ SES 本番環境昇格リクエスト（本番環境用）
