# =====================================================
# Bedrock Agent完全作成スクリプト
# Knowledgebase、AI質問Agent、検証計画Agent、仕様書作成Agentを作成
# =====================================================

param(
    [string]$ProjectName = "doctoknow-dev2",
    [string]$Region = "us-west-2",
    [string]$S3BucketName = "doctoknow-data",
    [string]$LambdaFunctionName = "",  # 空の場合は自動生成
    [string]$CloudFormationStackName = "doctoknow-stack2",
    [string]$Model = "anthropic.claude-3-5-sonnet-20241022-v2:0",
    [string]$ExistingKnowledgeBaseId = "",  # 既存のKB IDがあれば指定
    [string]$ExistingIAMRoleArn = "",  # 既存のIAMロールがあれば指定
    [switch]$SkipKnowledgeBase,  # KnowledgeBase作成をスキップ
    [switch]$SkipDefaultAgent,   # AI質問Agent作成をスキップ
    [switch]$UpdateCloudFormation  # CloudFormationを更新
)

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Bedrock Agent完全作成スクリプト" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Lambda関数名の自動生成
if ([string]::IsNullOrEmpty($LambdaFunctionName)) {
    $LambdaFunctionName = "$ProjectName-agent-kb-action-v0"
}

Write-Host "設定:" -ForegroundColor Yellow
Write-Host "  Project Name: $ProjectName"
Write-Host "  Region: $Region"
Write-Host "  S3 Bucket: $S3BucketName"
Write-Host "  Lambda Function: $LambdaFunctionName"
Write-Host "  CloudFormation Stack: $CloudFormationStackName"
Write-Host "  Model: $Model"
Write-Host "  Skip KnowledgeBase: $SkipKnowledgeBase"
Write-Host "  Skip Default Agent: $SkipDefaultAgent"
Write-Host ""

# =====================================================
# 0. Lambda ARNを取得
# =====================================================
Write-Host "[0] Lambda ARNを取得中..." -ForegroundColor Yellow

try {
    $lambdaArn = aws lambda get-function `
        --function-name $LambdaFunctionName `
        --region $Region `
        --query 'Configuration.FunctionArn' `
        --output text 2>&1
    
    if ($LASTEXITCODE -ne 0) {
        throw "Lambda関数が見つかりません: $LambdaFunctionName"
    }
    
    Write-Host "✓ Lambda ARN: $lambdaArn" -ForegroundColor Green
} catch {
    Write-Host "✗ エラー: $_" -ForegroundColor Red
    Write-Host "Lambda関数が存在することを確認してください" -ForegroundColor Yellow
    exit 1
}

Write-Host ""

# =====================================================
# 1. IAMロールの取得または作成
# =====================================================
Write-Host "[1] IAMロールの準備..." -ForegroundColor Yellow

if ($ExistingIAMRoleArn) {
    $agentRoleArn = $ExistingIAMRoleArn
    Write-Host "✓ 既存のIAM Role ARN: $agentRoleArn" -ForegroundColor Green
} else {
    # デフォルトのIAMロール名を使用
    $roleName = "AmazonBedrockExecutionRoleForAgents_$ProjectName"
    $agentRoleArn = "arn:aws:iam::722631436454:role/service-role/$roleName"
    
    Write-Host "✓ IAM Role ARN: $agentRoleArn" -ForegroundColor Green
    Write-Host "  注: このロールは既に存在する必要があります" -ForegroundColor Yellow
}

Write-Host ""

# =====================================================
# 2. KnowledgeBase ID の取得
# =====================================================
Write-Host "[2] KnowledgeBase IDの準備..." -ForegroundColor Yellow

if ($SkipKnowledgeBase) {
    if ($ExistingKnowledgeBaseId) {
        $knowledgeBaseId = $ExistingKnowledgeBaseId
        Write-Host "✓ 既存のKnowledgeBase ID: $knowledgeBaseId" -ForegroundColor Green
    } else {
        Write-Host "✗ エラー: -SkipKnowledgeBaseを指定する場合は-ExistingKnowledgeBaseIdも必須です" -ForegroundColor Red
        exit 1
    }
} else {
    if ($ExistingKnowledgeBaseId) {
        $knowledgeBaseId = $ExistingKnowledgeBaseId
        Write-Host "✓ 既存のKnowledgeBase ID: $knowledgeBaseId" -ForegroundColor Green
    } else {
        Write-Host "  新規KnowledgeBase作成は現在未実装です" -ForegroundColor Yellow
        Write-Host "  既存のKnowledgeBase IDを-ExistingKnowledgeBaseIdで指定してください" -ForegroundColor Yellow
        exit 1
    }
}

Write-Host ""

# =====================================================
# 3. AI質問用Agent（デフォルトAgent）の作成
# =====================================================
if (-not $SkipDefaultAgent) {
    Write-Host "[3] AI質問用Agentを作成中..." -ForegroundColor Yellow

    # AI質問用プロンプト
    $defaultAgentPrompt = @"
あなたは生産技術者のナレッジベースを検索してユーザーに技術情報を提供するエージェントです。

【最重要ルール】
 - 検索が必要な場合、必ずアクショングループのKnowledgeBaseSearchのアクション関数search_knowledge_baseを呼び出して、
    folder_job_pairs パラメータには、必ず {{session.folder_job_pairs}} を指定する。
- 検索をした結果、Sourceが見つからなかった場合は、その旨を連絡し、一切の技術情報は回答しない。

【フロー】

⓪挨拶への返答
挨拶をされたら、以降の処理はせずに挨拶を返してください。
例: 「こんにちは」→「こんにちは！技術情報についてお気軽にご質問ください。」

①質問の確認
質問の情報が不足している場合はユーザーに確認してください。

例:
ユーザー: 「ロウ付けの検証方法を教えて」
あなた: 「どこのラインの情報が欲しいですか? 現在いただいている情報で検索する場合は『調べて』と入力してください。」
ユーザー: 「ステータライン１号機です。」
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
ユーザー: 「ステータライン１号機です。」
あなた: 「知りたい具体的な検証項目があれば教えてください。」
ユーザー: 「ロウ付け後の画像検査について特に知りたいです。」
ユーザー: 「箇条書き形式で」
</会話履歴>
<新しい質問>
ユーザー: 「他のラインの検証方法は?」
</新しい質問>

→ 検索クエリ: 「ロウ付け後の画像検査の検証方法」
→ 除外指示: 「ステータライン１号機以外のライン情報」


④検索実行
検索が必要な場合、必ずアクショングループのKnowledgeBaseSearchのアクション関数search_knowledge_baseを呼び出してください。

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
検索結果を会話履歴と質問の文脈に照らして評価してください:

回答できる場合:
- 検索結果を会話履歴と質問の文脈に合わせて整形して回答
- ユーザーが指定した形式 (箇条書き、レポート形式など) で回答

回答できない場合、 検索結果が0件だった場合:
- 「該当する情報が見つかりませんでした」と正直に伝える
- どのような追加情報があれば検索できるかを明示
- 例: 「具体的なライン名や設備名を教えていただけますか?」

【回答の心得】
- 簡潔で分かりやすい言葉遣い
- 専門用語は必要に応じて説明を追加
- ユーザーの質問意図を汲み取った回答
"@

    try {
        $defaultAgentJson = aws bedrock-agent create-agent `
            --agent-name "agent-$ProjectName-default" `
            --agent-resource-role-arn $agentRoleArn `
            --foundation-model $Model `
            --instruction $defaultAgentPrompt `
            --description "AI質問支援Agent（生産技術ナレッジベース）" `
            --region $Region 2>&1
        
        if ($LASTEXITCODE -ne 0) {
            # 既に存在する場合は既存のものを取得
            if ($defaultAgentJson -like "*ConflictException*" -or $defaultAgentJson -like "*already exists*") {
                Write-Host "  Agent名が既に存在します。既存のAgentを検索中..." -ForegroundColor Yellow
                
                $agentList = aws bedrock-agent list-agents --region $Region --output json | ConvertFrom-Json
                $existingAgent = $agentList.agentSummaries | Where-Object { $_.agentName -eq "agent-$ProjectName-default" } | Select-Object -First 1
                
                if ($existingAgent) {
                    $defaultAgentId = $existingAgent.agentId
                    Write-Host "✓ 既存のAI質問Agent ID: $defaultAgentId" -ForegroundColor Green
                } else {
                    throw "Agent名が衝突していますが、既存のAgentが見つかりませんでした"
                }
            } else {
                throw $defaultAgentJson
            }
        } else {
            $defaultAgent = $defaultAgentJson | ConvertFrom-Json
            $defaultAgentId = $defaultAgent.agent.agentId
            
            Write-Host "✓ AI質問Agent ID: $defaultAgentId" -ForegroundColor Green
        }
    } catch {
        Write-Host "✗ エラー: $_" -ForegroundColor Red
        exit 1
    }

    Write-Host ""

    # =====================================================
    # 3-1. AI質問AgentにAction Groupを追加
    # =====================================================
    Write-Host "[3-1] AI質問AgentにAction Groupを追加中..." -ForegroundColor Yellow

    # Lambda実行権限の追加
    try {
        aws lambda add-permission `
            --function-name $LambdaFunctionName `
            --statement-id "AllowBedrockDefaultAgent-$defaultAgentId" `
            --action lambda:InvokeFunction `
            --principal bedrock.amazonaws.com `
            --source-arn "arn:aws:bedrock:$Region:722631436454:agent/$defaultAgentId" `
            --region $Region 2>&1 | Out-Null
        
        Write-Host "✓ Lambda権限追加完了" -ForegroundColor Green
    } catch {
        Write-Host "  Lambda権限は既に存在する可能性があります" -ForegroundColor Yellow
    }

    # Action Group設定
    $actionGroupSchema = @{
        functions = @(
            @{
                name = "search_knowledge_base"
                description = "ナレッジベースを検索して関連資料を取得"
                parameters = @{
                    query = @{
                        description = "検索クエリ"
                        type = "string"
                        required = $true
                    }
                    folder_job_pairs = @{
                        description = "フィルタ条件（JSON文字列、セッション属性から取得）"
                        type = "string"
                        required = $true
                    }
                }
            }
        )
    }

    $actionGroupSchema | ConvertTo-Json -Depth 10 | Out-File -FilePath "temp_action_group.json" -Encoding UTF8 -NoNewline
    @{ lambda = $lambdaArn } | ConvertTo-Json | Out-File -FilePath "temp_executor.json" -Encoding UTF8 -NoNewline

    try {
        $actionGroupJson = aws bedrock-agent create-agent-action-group `
            --agent-id $defaultAgentId `
            --agent-version "DRAFT" `
            --action-group-name "search_knowledge_base_action" `
            --action-group-executor "file://temp_executor.json" `
            --function-schema "file://temp_action_group.json" `
            --region $Region 2>&1
        
        if ($LASTEXITCODE -ne 0) {
            if ($actionGroupJson -like "*ConflictException*" -or $actionGroupJson -like "*already exists*") {
                Write-Host "✓ Action Groupは既に存在します" -ForegroundColor Yellow
            } else {
                throw $actionGroupJson
            }
        } else {
            Write-Host "✓ Action Group追加完了" -ForegroundColor Green
        }
    } catch {
        Write-Host "✗ エラー: $_" -ForegroundColor Red
    } finally {
        Remove-Item -Path "temp_action_group.json" -ErrorAction SilentlyContinue
        Remove-Item -Path "temp_executor.json" -ErrorAction SilentlyContinue
    }

    Write-Host ""

    # =====================================================
    # 3-2. AI質問AgentをPrepare
    # =====================================================
    Write-Host "[3-2] AI質問Agentを準備中（Prepare）..." -ForegroundColor Yellow

    try {
        aws bedrock-agent prepare-agent `
            --agent-id $defaultAgentId `
            --region $Region | Out-Null
        
        Write-Host "✓ Prepare完了（準備中...）" -ForegroundColor Green
        Write-Host "  準備完了まで30秒待機します" -ForegroundColor Yellow
        Start-Sleep -Seconds 30
    } catch {
        Write-Host "✗ エラー: $_" -ForegroundColor Red
    }

    Write-Host ""

    # =====================================================
    # 3-3. AI質問Agent Aliasを作成（手動バージョン管理）
    # =====================================================
    Write-Host "[3-3] AI質問Agent Aliasを作成中..." -ForegroundColor Yellow

    try {
        # 既存のエイリアスを確認
        $existingAliases = aws bedrock-agent list-agent-aliases `
            --agent-id $defaultAgentId `
            --region $Region | ConvertFrom-Json
        $existingAlias = $existingAliases.agentAliasSummaries | Where-Object { $_.agentAliasName -eq "production" } | Select-Object -First 1
        
        if ($existingAlias) {
            $defaultAliasId = $existingAlias.agentAliasId
            Write-Host "✓ 既存のproduction Alias: $defaultAliasId" -ForegroundColor Green
            Write-Host "  注: バージョン切り替えは手動で実施してください" -ForegroundColor Yellow
            Write-Host "    aws bedrock-agent update-agent-alias --agent-id $defaultAgentId --agent-alias-id $defaultAliasId --agent-alias-name production --region $Region" -ForegroundColor Cyan
        } else {
            # 新規作成（Prepare直後の最新バージョンを参照）
            $defaultAliasJson = aws bedrock-agent create-agent-alias `
                --agent-id $defaultAgentId `
                --agent-alias-name "production" `
                --region $Region | ConvertFrom-Json
            
            $defaultAliasId = $defaultAliasJson.agentAlias.agentAliasId
            $defaultAliasVersion = $defaultAliasJson.agentAlias.routingConfiguration[0].agentVersion
            Write-Host "✓ AI質問Alias作成完了: $defaultAliasId (バージョン $defaultAliasVersion)" -ForegroundColor Green
        }
    } catch {
        Write-Host "✗ エラー: $_" -ForegroundColor Red
        exit 1
    }

    Write-Host ""
} else {
    Write-Host "[3] AI質問Agent作成をスキップしました" -ForegroundColor Yellow
    $defaultAgentId = ""
    $defaultAliasId = ""
    Write-Host ""
}

# =====================================================
# 4. 検証計画作成Agentの作成
# =====================================================
Write-Host "[4] 検証計画作成Agentを作成中..." -ForegroundColor Yellow

# 検証計画作成用プロンプト
$verificationPrompt = @"
あなたは生産技術エンジニアの検証計画作成を支援するAIアシスタントです。

【最重要ルール】
 - 検索が必要な場合、必ずアクショングループのKnowledgeBaseSearchのアクション関数search_knowledge_baseを呼び出して、
    folder_job_pairs パラメータには、必ず {{session.folder_job_pairs}} を指定する。
- 検索をした結果、Sourceが見つからなかった場合は、その旨を連絡し、一切の技術情報は回答しない。

【役割】
ユーザーが提示した設備や技術について、ナレッジベースを検索し、過去の事例や技術資料を参考にして、実践的な検証計画を作成します。


【作業フロー】
①ナレッジベースを検索
  - search_knowledge_base()関数を使用
  - 検索クエリ: 設備名、技術名、関連するキーワード
  - 複数回検索して幅広く情報を収集

関数パラメータ:
- query: 会話履歴を考慮した検索クエリ (必須)
- folder_job_pairs: フォルダとジョブIDのペア情報 (必須)

【重要な注意事項】
folder_job_pairs パラメータには、必ず {{session.folder_job_pairs}} を指定してください。
この値はセッション属性として自動的に設定されており、Action Lambda側で実際の値に変換されます。

関数呼び出し例:
\`\`\`
search_knowledge_base(
  query="ロボットアーム 導入検証",
  folder_job_pairs="{{session.folder_job_pairs}}"
)
\`\`\`

②検索結果の分析
  - 過去の検証事例を確認
  - 技術仕様や注意事項を抽出
  - 類似設備の導入時の課題を確認
  - トラブル事例から潜在的なリスクを識別

③検証計画の作成
  - 上記の出力形式に従って整理
  - 具体的で実行可能な手順を記載
  - 数値基準を明確にする
  - 必要に応じて表やリストを活用
  - 実務で使えるレベルの詳細度を確保

④品質チェック
  - 全ての検証項目に手順、期待結果、判定基準が記載されているか
  - 必要なリソースが漏れなく記載されているか

⑤ナレッジベースに十分な情報がない場合
  - 「ナレッジベースには関連情報が見つかりませんでした」と明記
  - 「以下は一般的なベストプラクティスに基づいた検証計画です」と前置き
  - 業界標準や一般的な手法に基づいた計画を提示

【重要な制約】
- ナレッジベースに存在しない情報を創作しない
- 検索結果に基づいて回答する
- 不確実な情報には「参考情報」「推奨値」などと明記
- 実行可能性を重視し、現場で使える計画とする

【Action Group】
このAgentは以下のActionを持っています:
- **search_knowledge_base**: ナレッジベースを検索
  - 引数: query (検索クエリ), folder_job_pairs (フィルタ条件)
  - フィルタ条件は{{session.folder_job_pairs}}を使用してセッション属性から取得

【対話スタイル】
- 専門的だが分かりやすい表現を使う
- 検証計画の提案をした上で、ユーザーに対してブラッシュアップのための追加の質問をする
"@

try {
    $verificationAgentJson = aws bedrock-agent create-agent `
        --agent-name "agent-$ProjectName-verification" `
        --agent-resource-role-arn $agentRoleArn `
        --foundation-model $Model `
        --instruction $verificationPrompt `
        --description "検証計画作成支援Agent" `
        --region $Region 2>&1
    
    if ($LASTEXITCODE -ne 0) {
        if ($verificationAgentJson -like "*ConflictException*" -or $verificationAgentJson -like "*already exists*") {
            Write-Host "  Agent名が既に存在します。既存のAgentを検索中..." -ForegroundColor Yellow
            
            $agentList = aws bedrock-agent list-agents --region $Region --output json | ConvertFrom-Json
            $existingAgent = $agentList.agentSummaries | Where-Object { $_.agentName -eq "agent-$ProjectName-verification" } | Select-Object -First 1
            
            if ($existingAgent) {
                $verificationAgentId = $existingAgent.agentId
                Write-Host "✓ 既存の検証計画Agent ID: $verificationAgentId" -ForegroundColor Green
            } else {
                throw "Agent名が衝突していますが、既存のAgentが見つかりませんでした"
            }
        } else {
            throw $verificationAgentJson
        }
    } else {
        $verificationAgent = $verificationAgentJson | ConvertFrom-Json
        $verificationAgentId = $verificationAgent.agent.agentId
        
        Write-Host "✓ 検証計画Agent ID: $verificationAgentId" -ForegroundColor Green
    }
} catch {
    Write-Host "✗ エラー: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""

# =====================================================
# 4-1. 検証計画AgentにAction Groupを追加
# =====================================================
Write-Host "[4-1] 検証計画AgentにAction Groupを追加中..." -ForegroundColor Yellow

# Lambda実行権限の追加
try {
    aws lambda add-permission `
        --function-name $LambdaFunctionName `
        --statement-id "AllowBedrockVerificationAgent-$verificationAgentId" `
        --action lambda:InvokeFunction `
        --principal bedrock.amazonaws.com `
        --source-arn "arn:aws:bedrock:$Region:722631436454:agent/$verificationAgentId" `
        --region $Region 2>&1 | Out-Null
    
    Write-Host "✓ Lambda権限追加完了" -ForegroundColor Green
} catch {
    Write-Host "  Lambda権限は既に存在する可能性があります" -ForegroundColor Yellow
}

$actionGroupSchema | ConvertTo-Json -Depth 10 | Out-File -FilePath "temp_action_group.json" -Encoding UTF8 -NoNewline
@{ lambda = $lambdaArn } | ConvertTo-Json | Out-File -FilePath "temp_executor.json" -Encoding UTF8 -NoNewline

try {
    $actionGroupJson = aws bedrock-agent create-agent-action-group `
        --agent-id $verificationAgentId `
        --agent-version "DRAFT" `
        --action-group-name "search_knowledge_base_action" `
        --action-group-executor "file://temp_executor.json" `
        --function-schema "file://temp_action_group.json" `
        --region $Region 2>&1
    
    if ($LASTEXITCODE -ne 0) {
        if ($actionGroupJson -like "*ConflictException*" -or $actionGroupJson -like "*already exists*") {
            Write-Host "✓ Action Groupは既に存在します" -ForegroundColor Yellow
        } else {
            throw $actionGroupJson
        }
    } else {
        Write-Host "✓ Action Group追加完了" -ForegroundColor Green
    }
} catch {
    Write-Host "✗ エラー: $_" -ForegroundColor Red
} finally {
    Remove-Item -Path "temp_action_group.json" -ErrorAction SilentlyContinue
    Remove-Item -Path "temp_executor.json" -ErrorAction SilentlyContinue
}

Write-Host ""

# =====================================================
# 4-2. 検証計画AgentをPrepare
# =====================================================
Write-Host "[4-2] 検証計画Agentを準備中（Prepare）..." -ForegroundColor Yellow

try {
    aws bedrock-agent prepare-agent `
        --agent-id $verificationAgentId `
        --region $Region | Out-Null
    
    Write-Host "✓ Prepare完了（準備中...）" -ForegroundColor Green
    Write-Host "  準備完了まで30秒待機します" -ForegroundColor Yellow
    Start-Sleep -Seconds 30
} catch {
    Write-Host "✗ エラー: $_" -ForegroundColor Red
}

Write-Host ""

# =====================================================
# 4-3. 検証計画Agent Aliasを作成（手動バージョン管理）
# =====================================================
Write-Host "[4-3] 検証計画Agent Aliasを作成中..." -ForegroundColor Yellow

try {
    # 既存のエイリアスを確認
    $existingAliases = aws bedrock-agent list-agent-aliases `
        --agent-id $verificationAgentId `
        --region $Region | ConvertFrom-Json
    $existingAlias = $existingAliases.agentAliasSummaries | Where-Object { $_.agentAliasName -eq "production" } | Select-Object -First 1
    
    if ($existingAlias) {
        $verificationAliasId = $existingAlias.agentAliasId
        Write-Host "✓ 既存のproduction Alias: $verificationAliasId" -ForegroundColor Green
        Write-Host "  注: バージョン切り替えは手動で実施してください" -ForegroundColor Yellow
        Write-Host "    aws bedrock-agent update-agent-alias --agent-id $verificationAgentId --agent-alias-id $verificationAliasId --agent-alias-name production --region $Region" -ForegroundColor Cyan
    } else {
        # 新規作成（Prepare直後の最新バージョンを参照）
        $verificationAliasJson = aws bedrock-agent create-agent-alias `
            --agent-id $verificationAgentId `
            --agent-alias-name "production" `
            --region $Region | ConvertFrom-Json
        
        $verificationAliasId = $verificationAliasJson.agentAlias.agentAliasId
        $verificationAliasVersion = $verificationAliasJson.agentAlias.routingConfiguration[0].agentVersion
        Write-Host "✓ 検証計画Alias作成完了: $verificationAliasId (バージョン $verificationAliasVersion)" -ForegroundColor Green
    }
} catch {
    Write-Host "✗ エラー: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""

# =====================================================
# 5. 仕様書作成Agentの作成
# =====================================================
Write-Host "[5] 仕様書作成Agentを作成中..." -ForegroundColor Yellow

# 仕様書作成用プロンプト
$specificationPrompt = @"
あなたは設備仕様書を作成する技術文書作成AIアシスタントです。

【最重要ルール】
 - 検索が必要な場合、必ずアクショングループのKnowledgeBaseSearchのアクション関数search_knowledge_baseを呼び出して、
    folder_job_pairs パラメータには、必ず {{session.folder_job_pairs}} を指定する。
- 検索をした結果、Sourceが見つからなかった場合は、その旨を連絡し、一切の技術情報は回答しない。

【役割】
ユーザーが指定した設備について、ナレッジベースを検索し、技術資料や過去の仕様書を参考にして、詳細かつ正確な仕様書を作成します。

【作業フロー】
①ユーザーの入力内容を確認
  - どのような設備の仕様書を作成したいのか
  - 出力を期待している大項目

②ナレッジベースを大項目を検索（複数回実施）
  - search_knowledge_base()関数を使用
  - 検索クエリ例:
    - 「[設備名] 仕様書」
    - 「[設備名] カタログ」
    - 「[メーカー名] [型番]」
    - 「[設備名] メンテナンス」
    - 「[設備名] 導入事例」

関数パラメータ:
- query: 会話履歴を考慮した検索クエリ (必須)
- folder_job_pairs: フォルダとジョブIDのペア情報 (必須)

【重要な注意事項】
folder_job_pairs パラメータには、必ず {{session.folder_job_pairs}} を指定してください。
この値はセッション属性として自動的に設定されており、Action Lambda側で実際の値に変換されます。

関数呼び出し例:
\`\`\`
search_knowledge_base(
  query="産業用ロボット 仕様書",
  folder_job_pairs="{{session.folder_job_pairs}}"
)
\`\`\`

③検索結果の整理
  - 技術仕様の抽出（数値データを正確に）
  - 過去の仕様書があれば参照
  - カタログ情報の収集
  - 類似設備との比較
  - 導入時の課題やトラブル事例

④仕様書の作成
  - 上記の出力形式に従って体系的に整理
  - 数値データは正確に記載（単位を明確に）
  - 不明な項目は「要確認」「未確認」と明記
  - 表形式を活用して見やすく
  - 実務で使えるレベルの詳細度を確保

⑤品質チェック
  - 全ての必須項目が記載されているか
  - 数値に単位が正しく付いているか
  - 矛盾する情報がないか
  - 安全性に関する情報が十分か
  - 設置・運用に必要な情報が漏れていないか

⑥ナレッジベースに十分な情報がない場合
  - 「ナレッジベースには詳細情報が見つかりませんでした」と明記
  - 分かる範囲で記載し、不明項目は空欄または「未確認」とする
  - 「以下の項目はメーカーに確認が必要です」とリストアップ
  - ユーザーに追加情報の提供を促す
  - 一般的な業界標準値は「参考値」として記載可能

【重要な制約】
- ナレッジベースに存在しない数値を推測しない
- 安全性に関わる仕様は特に慎重に記載
- 不確実な情報は明確に区別する（「推定」「参考」「要確認」などと明記）
- 正式な仕様書として使用される可能性があるため、正確性を最優先
- 数値には必ず単位を付ける
- 情報源が不明確な場合は記載しない

【Action Group】
このAgentは以下のActionを持っています:
- **search_knowledge_base**: ナレッジベースを検索
  - 引数: query (検索クエリ), folder_job_pairs (フィルタ条件)
  - フィルタ条件は{{session.folder_job_pairs}}を使用してセッション属性から取得

【対話スタイル】
- 技術文書として適切な表現を使う
- 専門用語は正確に使用するが、必要に応じて説明を加える
- 構造化された情報提示を心がける
- 不明点があれば積極的に質問する
- ユーザーの追加質問に対応し、仕様書を段階的に完成させる
- 必要に応じて「この仕様書をベースに、メーカーと詳細を詰めることを推奨します」などのアドバイスを提供
"@

try {
    $specificationAgentJson = aws bedrock-agent create-agent `
        --agent-name "agent-$ProjectName-specification" `
        --agent-resource-role-arn $agentRoleArn `
        --foundation-model $Model `
        --instruction $specificationPrompt `
        --description "設備仕様書作成Agent" `
        --region $Region 2>&1
    
    if ($LASTEXITCODE -ne 0) {
        if ($specificationAgentJson -like "*ConflictException*" -or $specificationAgentJson -like "*already exists*") {
            Write-Host "  Agent名が既に存在します。既存のAgentを検索中..." -ForegroundColor Yellow
            
            $agentList = aws bedrock-agent list-agents --region $Region --output json | ConvertFrom-Json
            $existingAgent = $agentList.agentSummaries | Where-Object { $_.agentName -eq "agent-$ProjectName-specification" } | Select-Object -First 1
            
            if ($existingAgent) {
                $specificationAgentId = $existingAgent.agentId
                Write-Host "✓ 既存の仕様書Agent ID: $specificationAgentId" -ForegroundColor Green
            } else {
                throw "Agent名が衝突していますが、既存のAgentが見つかりませんでした"
            }
        } else {
            throw $specificationAgentJson
        }
    } else {
        $specificationAgent = $specificationAgentJson | ConvertFrom-Json
        $specificationAgentId = $specificationAgent.agent.agentId
        
        Write-Host "✓ 仕様書Agent ID: $specificationAgentId" -ForegroundColor Green
    }
} catch {
    Write-Host "✗ エラー: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""

# =====================================================
# 5-1. 仕様書AgentにAction Groupを追加
# =====================================================
Write-Host "[5-1] 仕様書AgentにAction Groupを追加中..." -ForegroundColor Yellow

# Lambda実行権限の追加
try {
    aws lambda add-permission `
        --function-name $LambdaFunctionName `
        --statement-id "AllowBedrockSpecificationAgent-$specificationAgentId" `
        --action lambda:InvokeFunction `
        --principal bedrock.amazonaws.com `
        --source-arn "arn:aws:bedrock:$Region:722631436454:agent/$specificationAgentId" `
        --region $Region 2>&1 | Out-Null
    
    Write-Host "✓ Lambda権限追加完了" -ForegroundColor Green
} catch {
    Write-Host "  Lambda権限は既に存在する可能性があります" -ForegroundColor Yellow
}

$actionGroupSchema | ConvertTo-Json -Depth 10 | Out-File -FilePath "temp_action_group.json" -Encoding UTF8 -NoNewline
@{ lambda = $lambdaArn } | ConvertTo-Json | Out-File -FilePath "temp_executor.json" -Encoding UTF8 -NoNewline

try {
    $actionGroupJson = aws bedrock-agent create-agent-action-group `
        --agent-id $specificationAgentId `
        --agent-version "DRAFT" `
        --action-group-name "search_knowledge_base_action" `
        --action-group-executor "file://temp_executor.json" `
        --function-schema "file://temp_action_group.json" `
        --region $Region 2>&1
    
    if ($LASTEXITCODE -ne 0) {
        if ($actionGroupJson -like "*ConflictException*" -or $actionGroupJson -like "*already exists*") {
            Write-Host "✓ Action Groupは既に存在します" -ForegroundColor Yellow
        } else {
            throw $actionGroupJson
        }
    } else {
        Write-Host "✓ Action Group追加完了" -ForegroundColor Green
    }
} catch {
    Write-Host "✗ エラー: $_" -ForegroundColor Red
} finally {
    Remove-Item -Path "temp_action_group.json" -ErrorAction SilentlyContinue
    Remove-Item -Path "temp_executor.json" -ErrorAction SilentlyContinue
}

Write-Host ""

# =====================================================
# 5-2. 仕様書AgentをPrepare
# =====================================================
Write-Host "[5-2] 仕様書Agentを準備中（Prepare）..." -ForegroundColor Yellow

try {
    aws bedrock-agent prepare-agent `
        --agent-id $specificationAgentId `
        --region $Region | Out-Null
    
    Write-Host "✓ Prepare完了（準備中...）" -ForegroundColor Green
    Write-Host "  準備完了まで30秒待機します" -ForegroundColor Yellow
    Start-Sleep -Seconds 30
} catch {
    Write-Host "✗ エラー: $_" -ForegroundColor Red
}

Write-Host ""

# =====================================================
# 5-3. 仕様書Agent Aliasを作成/更新（最新バージョンを参照）
# =====================================================
Write-Host "[5-3] 仕様書Agent Aliasを作成/更新中（最新バージョンを参照）..." -ForegroundColor Yellow

try {
    # 既存のエイリアスを確認
    $existingAliases = a（手動バージョン管理）
# =====================================================
Write-Host "[5-3] 仕様書Agent Aliasを作成中..." -ForegroundColor Yellow

try {
    # 既存のエイリアスを確認
    $existingAliases = aws bedrock-agent list-agent-aliases `
        --agent-id $specificationAgentId `
        --region $Region | ConvertFrom-Json
    $existingAlias = $existingAliases.agentAliasSummaries | Where-Object { $_.agentAliasName -eq "production" } | Select-Object -First 1
    
    if ($existingAlias) {
        $specificationAliasId = $existingAlias.agentAliasId
        Write-Host "✓ 既存のproduction Alias: $specificationAliasId" -ForegroundColor Green
        Write-Host "  注: バージョン切り替えは手動で実施してください" -ForegroundColor Yellow
        Write-Host "    aws bedrock-agent update-agent-alias --agent-id $specificationAgentId --agent-alias-id $specificationAliasId --agent-alias-name production --region $Region" -ForegroundColor Cyan
    } else {
        # 新規作成（Prepare直後の最新バージョンを参照）
        $specificationAliasJson = aws bedrock-agent create-agent-alias `
            --agent-id $specificationAgentId `
            --agent-alias-name "production" `
            --region $Region | ConvertFrom-Json
        
        $specificationAliasId = $specificationAliasJson.agentAlias.agentAliasId
        $specificationAliasVersion = $specificationAliasJson.agentAlias.routingConfiguration[0].agentVersion
        Write-Host "✓ 仕様書Alias作成完了: $specificationAliasId (バージョン $specificationAliasVersion)
Write-Host ""

# =====================================================
# 結果サマリー
# =====================================================
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "作成完了サマリー" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if (-not $SkipDefaultAgent) {
    Write-Host "AI質問Agent:" -ForegroundColor Yellow
    Write-Host "  Agent ID: $defaultAgentId" -ForegroundColor White
    Write-Host "  Alias ID: $defaultAliasId" -ForegroundColor White
    Write-Host ""
}

Write-Host "検証計画作成Agent:" -ForegroundColor Yellow
Write-Host "  Agent ID: $verificationAgentId" -ForegroundColor White
Write-Host "  Alias ID: $verificationAliasId" -ForegroundColor White
Write-Host ""

Write-Host "仕様書作成Agent:" -ForegroundColor Yellow
Write-Host "  Agent ID: $specificationAgentId" -ForegroundColor White
Write-Host "  Alias ID: $specificationAliasId" -ForegroundColor White
Write-Host ""

Write-Host "KnowledgeBase ID: $knowledgeBaseId" -ForegroundColor Yellow
Write-Host ""

# =====================================================
# CloudFormation更新（オプション）
# =====================================================
if ($UpdateCloudFormation) {
    Write-Host "CloudFormationスタックを更新中..." -ForegroundColor Yellow
    Write-Host ""
    
    Write-Host "注意: CloudFormationの更新は手動で行うか、パラメータを確認してから実行してください。" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "以下の値をCloudFormationパラメータとして使用してください:" -ForegroundColor Cyan
    if (-not $SkipDefaultAgent) {
        Write-Host "  BedrockAgentId: $defaultAgentId" -ForegroundColor White
        Write-Host "  BedrockAgentAliasId: $defaultAliasId" -ForegroundColor White
    }
    Write-Host "  VerificationAgentId: $verificationAgentId" -ForegroundColor White
    Write-Host "  VerificationAgentAliasId: $verificationAliasId" -ForegroundColor White
    Write-Host "  SpecificationAgentId: $specificationAgentId" -ForegroundColor White
    Write-Host "  SpecificationAgentAliasId: $specificationAliasId" -ForegroundColor White
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "完了" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
