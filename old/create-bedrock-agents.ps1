# =====================================================
# Bedrock Agent作成スクリプト
# 検証計画作成Agentと仕様書作成Agentを作成し、CloudFormationを更新
# =====================================================

param(
    [string]$ProjectName = "doctoknow-dev",
    [string]$Region = "us-west-2",
    [string]$KnowledgeBaseId = "QBRNP5FY8E",
    [string]$LambdaFunctionName = "",  # 空の場合は自動生成
    [string]$CloudFormationStackName = "doctoknow-dev",
    [string]$Model = "anthropic.claude-3-5-sonnet-20241022-v2:0",
    [string]$DefaultAgentId = "M89ZN5FKB4"  # デフォルトAgentからIAMロールを取得
)

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Bedrock Agent作成スクリプト" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Lambda関数名の自動生成
if ([string]::IsNullOrEmpty($LambdaFunctionName)) {
    $LambdaFunctionName = "$ProjectName-agent-kb-action-v0"
}

Write-Host "設定:" -ForegroundColor Yellow
Write-Host "  Project Name: $ProjectName"
Write-Host "  Region: $Region"
Write-Host "  Knowledge Base ID: $KnowledgeBaseId"
Write-Host "  Lambda Function: $LambdaFunctionName"
Write-Host "  CloudFormation Stack: $CloudFormationStackName"
Write-Host "  Model: $Model"
Write-Host "  Default Agent ID: $DefaultAgentId"
Write-Host ""

# =====================================================
# 1. デフォルトAgentからIAMロールを取得
# =====================================================
Write-Host "[1/9] デフォルトAgentからIAMロールを取得中..." -ForegroundColor Yellow

try {
    $defaultAgentJson = aws bedrock-agent get-agent `
        --agent-id $DefaultAgentId `
        --region $Region 2>&1
    
    if ($LASTEXITCODE -ne 0) {
        throw "デフォルトAgentが見つかりません: $DefaultAgentId"
    }
    
    $defaultAgent = $defaultAgentJson | ConvertFrom-Json
    $agentRoleArn = $defaultAgent.agent.agentResourceRoleArn
    
    Write-Host "✓ IAM Role ARN: $agentRoleArn" -ForegroundColor Green
} catch {
    Write-Host "✗ エラー: $_" -ForegroundColor Red
    Write-Host "IAMロールを手動で指定してください" -ForegroundColor Yellow
    exit 1
}

Wr3. 検証計画作成Agentの作成
# =====================================================
Write-Host "[3/9] 検証計画作成Agentを作成中..." -ForegroundColor Yellow

# Instructionsを読み込み
$verificationPrompt = Get-Content -Path "document\Verification_Agent_Prompt.txt" -Raw -Encoding UTF8

try {
    $verificationAgentJson = aws bedrock-agent create-agent `
        --agent-name "agent-doctoknow-verification" `
        --agent-resource-role-arn $agentRoleArn
        --query 'Configuration.FunctionArn' `
        --output text 2>&1
    
    if ($LASTEXITCODE -ne 0) {
        throw "Lambda関数が見つかりません: $LambdaFunctionName"
    }
    
    Write-Host "✓ Lambda ARN: $lambdaArn" -ForegroundColor Green
} catch {
    Write-Host "✗ エラー: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""

# =====================================================
# 2. 検証計画作成Agentの作成
# =====================================================
Write-Host "[2/8] 検証計画作成Agentを作成中..." -ForegroundColor Yellow

# Instructionsを読み込み
$verificationPrompt = Get-Content -Path "document\Verification_Agent_Prompt.txt" -Raw -Encoding UTF8

try {
    $verificationAgentJson = aws bedrock-agent create-agent `
        --agent-name "agent-doctoknow-verification" `
        --agent-resource-role-arn "arn:aws:iam::722631436454:role/service-role/AmazonBedrockExecutionRoleForAgents_doctoknow" `
        --foundation-model $Model `
        --instruction $verificationPrompt `
        --description "検証計画作成支援Agent" `
        --region $Region 2>&1
    
    if ($LASTEXITCODE -ne 0) {
        throw $verificationAgentJson
    }
    
    $verificationAgent = $verificationAgentJson | ConvertFrom-Json
    $verificationAgentId = $verificationAgent.agent.agentId
    
    Write-Host "✓ 検証計画Agent ID: $verificationAgentId" -ForegroundColor Green
} catch {
    Write-Host "✗ エラー: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""

# =====================================================
# 4. 検証計画AgentにAction Groupを追加
# =====================================================
Write-Host "[4/9] 検証計画AgentにAction Groupを追加中..." -ForegroundColor Yellow

# Action Group設定ファイルを作成
$actionGroupConfig = @{
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
} | ConvertTo-Json -Depth 10 -Compress

$actionGroupConfig | Out-File -FilePath "temp_action_group.json" -Encoding UTF8

$executorConfig = @{
    lambda = $lambdaArn
} | ConvertTo-Json -Compress

$executorConfig | Out-File -FilePath "temp_executor.json" -Encoding UTF8

try {
    $actionGroupJson = aws bedrock-agent create-agent-action-group `
        --agent-id $verificationAgentId `
        --agent-version "DRAFT" `
        --action-group-name "search_knowledge_base_action" `
        --action-group-executor "file://temp_executor.json" `
        --function-schema "file://temp_action_group.json" `
        --region $Region 2>&1
    
    if ($LASTEXITCODE -ne 0) {
        throw $actionGroupJson
    }
    
    Write-Host "✓ Action Group追加完了" -ForegroundColor Green
} catch {
    Write-Host "✗ エラー: $_" -ForegroundColor Red
    Write-Host "注: 既にAction Groupが存在する可能性があります" -ForegroundColor Yellow
} finally {
    # 一時ファイルを削除
    Remove-Item -Path "temp_action_group.json" -ErrorAction SilentlyContinue
    Remove-Item -Path "temp_executor.json" -ErrorAction SilentlyContinue
}

Write-Host ""

# =====================================================
# 5. 検証計画AgentをPrepare
# =====================================================
Write-Host "[5/9] 検証計画Agentを準備中（Prepare）..." -ForegroundColor Yellow

try {
    aws bedrock-agent prepare-agent `
        --agent-id $verificationAgentId `
        --region $Region | Out-Null
    
    Write-Host "✓ Prepare完了（準備中...）" -ForegroundColor Green
    Write-Host "  準備完了まで数分かかります" -ForegroundColor Yellow
    
    # Prepareの完了を待つ
    Start-Sleep -Seconds 30
} catch {
    Write-Host "✗ エラー: $_" -ForegroundColor Red
}

Write-Host ""

# =====================================================
# 6. 仕様書作成Agentの作成
# =====================================================
Write-Host "[6/9] 仕様書作成Agentを作成中..." -ForegroundColor Yellow

# Instructionsを読み込み
$specificationPrompt = Get-Content -Path "document\Specification_Agent_Prompt.txt" -Raw -Encoding UTF8

try {
    $specificationAgentJson = aws bedrock-agent create-agent `
        --agent-name "agent-doctoknow-specification" `
        --agent-resource-role-arn $agentRoleArn `
        --foundation-model $Model `
        --instruction $specificationPrompt `
        --description "設備仕様書作成Agent" `
        --region $Region 2>&1
    
    if ($LASTEXITCODE -ne 0) {
        throw $specificationAgentJson
    }
    
    $specificationAgent = $specificationAgentJson | ConvertFrom-Json
    $specificationAgentId = $specificationAgent.agent.agentId
    
    Write-Host "✓ 仕様書Agent ID: $specificationAgentId" -ForegroundColor Green
} catch {
# Action Group設定ファイルを作成（検証計画Agentと同じ設定）
$actionGroupConfig = @{
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
} | ConvertTo-Json -Depth 10 -Compress

$actionGroupConfig | Out-File -FilePath "temp_action_group.json" -Encoding UTF8

$executorConfig = @{
    lambda = $lambdaArn
} | ConvertTo-Json -Compress

$executorConfig | Out-File -FilePath "temp_executor.json" -Encoding UTF8

try {
    $actionGroupJson = aws bedrock-agent create-agent-action-group `
        --agent-id $specificationAgentId `
        --agent-version "DRAFT" `
        --action-group-name "search_knowledge_base_action" `
        --action-group-executor "file://temp_executor.json" `
        --function-schema "file://temp_action_group.json" `
        --region $Region 2>&1
    
    if ($LASTEXITCODE -ne 0) {
        throw $actionGroupJson
    }
    
    Write-Host "✓ Action Group追加完了" -ForegroundColor Green
} catch {
    Write-Host "✗ エラー: $_" -ForegroundColor Red
    Write-Host "注: 既にAction Groupが存在する可能性があります" -ForegroundColor Yellow
} finally {
    # 一時ファイルを削除
    Remove-Item -Path "temp_action_group.json" -ErrorAction SilentlyContinue
    Remove-Item -Path "temp_executor.json" -ErrorAction SilentlyContinue
        --function-schema "{`"functions`": $actionGroupSchema}" `
        --region $Region 2>&1
    
    if ($LASTEXITCODE -ne 0) {
        throw $actionGroupJson
    }
    
    Write-Host "✓ Action Group追加完了" -ForegroundColor Green
} catch {
    Write-Host "✗ エラー: $_" -ForegroundColor Red
    Write-Host "注: 既にAction Groupが存在する可能性があります" -ForegroundColor Yellow
}

Write-Host ""

# =====================================================
# 8. 仕様書AgentをPrepare
# =====================================================
Write-Host "[8/9] 仕様書Agentを準備中（Prepare）..." -ForegroundColor Yellow

try {
    aws bedrock-agent prepare-agent `
        --agent-id $specificationAgentId `
        --region $Region | Out-Null
    
    Write-Host "✓ Prepare完了（準備中...）" -ForegroundColor Green
    Write-Host "  準備完了まで数分かかります" -ForegroundColor Yellow
    
    # Prepareの完了を待つ
    Start-Sleep -Seconds 30
} catch {
    Write-Host "✗ エラー: $_" -ForegroundColor Red
}

Write-Host ""

# =====================================================
# 9. Alias作成
# =====================================================
Write-Host "[9/9] Aliasを作成中..." -ForegroundColor Yellow

# 検証計画Agent Alias
try {
    $verificationAliasJson = aws bedrock-agent create-agent-alias `
        --agent-id $verificationAgentId `
        --agent-alias-name "production" `
        --region $Region 2>&1
    
    if ($LASTEXITCODE -ne 0) {
        throw $verificationAliasJson
    }
    
    $verificationAlias = $verificationAliasJson | ConvertFrom-Json
    $verificationAliasId = $verificationAlias.agentAlias.agentAliasId
    
    Write-Host "✓ 検証計画Alias ID: $verificationAliasId" -ForegroundColor Green
} catch {
    Write-Host "✗ エラー: $_" -ForegroundColor Red
    Write-Host "注: 既にAliasが存在する可能性があります" -ForegroundColor Yellow
    # 既存のAliasを取得
    try {
        $existingAliases = aws bedrock-agent list-agent-aliases `
            --agent-id $verificationAgentId `
            --region $Region | ConvertFrom-Json
        $verificationAliasId = $existingAliases.agentAliasSummaries[0].agentAliasId
        Write-Host "✓ 既存のAlias ID: $verificationAliasId" -ForegroundColor Green
    } catch {
        Write-Host "✗ Alias取得失敗" -ForegroundColor Red
        exit 1
    }
}

# 仕様書Agent Alias
try {
    $specificationAliasJson = aws bedrock-agent create-agent-alias `
        --agent-id $specificationAgentId `
        --agent-alias-name "production" `
        --region $Region 2>&1
    
    if ($LASTEXITCODE -ne 0) {
        throw $specificationAliasJson
    }
    
    $specificationAlias = $specificationAliasJson | ConvertFrom-Json
    $specificationAliasId = $specificationAlias.agentAlias.agentAliasId
    
    Write-Host "✓ 仕様書Alias ID: $specificationAliasId" -ForegroundColor Green
} catch {
    Write-Host "✗ エラー: $_" -ForegroundColor Red
    Write-Host "注: 既にAliasが存在する可能性があります" -ForegroundColor Yellow
    # 既存のAliasを取得
    try {
        $existingAliases = aws bedrock-agent list-agent-aliases `
            --agent-id $specificationAgentId `
            --region $Region | ConvertFrom-Json
        $specificationAliasId = $existingAliases.agentAliasSummaries[0].agentAliasId
        Write-Host "✓ 既存のAlias ID: $specificationAliasId" -ForegroundColor Green
    } catch {
        Write-Host "✗ Alias取得失敗" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""

# =====================================================
# 結果サマリー
# =====================================================
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "作成完了サマリー" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "検証計画作成Agent:" -ForegroundColor Yellow
Write-Host "  Agent ID: $verificationAgentId" -ForegroundColor White
Write-Host "  Alias ID: $verificationAliasId" -ForegroundColor White
Write-Host ""
Write-Host "仕様書作成Agent:" -ForegroundColor Yellow
Write-Host "  Agent ID: $specificationAgentId" -ForegroundColor White
Write-Host "  Alias ID: $specificationAliasId" -ForegroundColor White
Write-Host ""

# =====================================================
# CloudFormation更新
# =====================================================
Write-Host "CloudFormationスタックを更新しますか? (y/n): " -ForegroundColor Yellow -NoNewline
$confirm = Read-Host

if ($confirm -eq 'y' -or $confirm -eq 'Y') {
    Write-Host ""
    Write-Host "CloudFormationスタックを更新中..." -ForegroundColor Yellow
    
    try {
        # 現在のパラメータを取得
        $currentParams = aws cloudformation describe-stacks `
            --stack-name $CloudFormationStackName `
            --region $Region `
            --query 'Stacks[0].Parameters' | ConvertFrom-Json
        
        # パラメータ配列を構築
        $params = @()
        foreach ($param in $currentParams) {
            $key = $param.ParameterKey
            
            # 新しい値を設定するパラメータ
            if ($key -eq "VerificationAgentId") {
                $params += "ParameterKey=$key,ParameterValue=$verificationAgentId"
            } elseif ($key -eq "VerificationAgentAliasId") {
                $params += "ParameterKey=$key,ParameterValue=$verificationAliasId"
            } elseif ($key -eq "SpecificationAgentId") {
                $params += "ParameterKey=$key,ParameterValue=$specificationAgentId"
            } elseif ($key -eq "SpecificationAgentAliasId") {
                $params += "ParameterKey=$key,ParameterValue=$specificationAliasId"
            } else {
                # 既存の値を維持
                $params += "ParameterKey=$key,UsePreviousValue=true"
            }
        }
        
        # CloudFormationを更新
        aws cloudformation update-stack `
            --stack-name $CloudFormationStackName `
            --template-body file://cloudformation-doctoknow-template.json `
            --parameters $params `
            --capabilities CAPABILITY_IAM `
            --region $Region
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ CloudFormationスタック更新開始" -ForegroundColor Green
            Write-Host "  スタック名: $CloudFormationStackName" -ForegroundColor White
            Write-Host "  更新完了まで数分かかります" -ForegroundColor Yellow
        } else {
            throw "CloudFormation更新コマンドが失敗しました"
        }
    } catch {
        Write-Host "✗ CloudFormation更新エラー: $_" -ForegroundColor Red
        Write-Host ""
        Write-Host "手動で更新する場合は以下のコマンドを実行してください:" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "aws cloudformation update-stack \" -ForegroundColor Cyan
        Write-Host "  --stack-name $CloudFormationStackName \" -ForegroundColor Cyan
        Write-Host "  --template-body file://cloudformation-doctoknow-template.json \" -ForegroundColor Cyan
        Write-Host "  --parameters \" -ForegroundColor Cyan
        Write-Host "    ParameterKey=VerificationAgentId,ParameterValue=$verificationAgentId \" -ForegroundColor Cyan
        Write-Host "    ParameterKey=VerificationAgentAliasId,ParameterValue=$verificationAliasId \" -ForegroundColor Cyan
        Write-Host "    ParameterKey=SpecificationAgentId,ParameterValue=$specificationAgentId \" -ForegroundColor Cyan
        Write-Host "    ParameterKey=SpecificationAgentAliasId,ParameterValue=$specificationAliasId \" -ForegroundColor Cyan
        Write-Host "    (他のパラメータはUsePreviousValue=true) \" -ForegroundColor Cyan
        Write-Host "  --capabilities CAPABILITY_IAM \" -ForegroundColor Cyan
        Write-Host "  --region $Region" -ForegroundColor Cyan
        exit 1
    }
} else {
    Write-Host ""
    Write-Host "CloudFormation更新をスキップしました" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "後で手動で更新する場合は以下の値を使用してください:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "VerificationAgentId: $verificationAgentId" -ForegroundColor White
    Write-Host "VerificationAgentAliasId: $verificationAliasId" -ForegroundColor White
    Write-Host "SpecificationAgentId: $specificationAgentId" -ForegroundColor White
    Write-Host "SpecificationAgentAliasId: $specificationAliasId" -ForegroundColor White
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "完了" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
