param(
    [string]$StackName = "doctoknow-dev",
    [string]$Region = "us-west-2",
    [string]$TemplatePath = "cloudformation-doctoknow-template.json",
    [int]$PollingIntervalSeconds = 20,
    [int]$MaxWaitMinutes = 60
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Write-Status {
    param([string]$Message, [string]$Status = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $color = @{
        "INFO"    = "Cyan"
        "SUCCESS" = "Green"
        "WARNING" = "Yellow"
        "ERROR"   = "Red"
    }
    Write-Host "[$timestamp] [$Status] $Message" -ForegroundColor $color[$Status]
}

# ===== 1. テンプレート検証 =====
Write-Status "Step 1: テンプレート検証を開始します..." "INFO"
try {
    $validateResult = aws cloudformation validate-template `
        --template-body file://$TemplatePath `
        --region $Region 2>&1 | ConvertFrom-Json
    Write-Status "テンプレート検証: 成功" "SUCCESS"
    Write-Host "  - 説明: $($validateResult.Description)"
    Write-Host "  - パラメータ数: $($validateResult.Parameters.Count)"
} catch {
    Write-Status "テンプレート検証: 失敗 - $_" "ERROR"
    exit 1
}

# ===== 2. スタック更新 =====
Write-Status "Step 2: スタック更新を開始します..." "INFO"
try {
    $updateResult = aws cloudformation update-stack `
        --stack-name $StackName `
        --template-body file://$TemplatePath `
        --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM `
        --region $Region 2>&1
    
    if ($LASTEXITCODE -ne 0) {
        # No updates are to be performed. エラーの場合もチェック
        if ($updateResult -match "No updates are to be performed") {
            Write-Status "スタック更新: 変更なし（既に最新状態です）" "WARNING"
        } else {
            throw $updateResult
        }
    } else {
        $stackId = $updateResult | ConvertFrom-Json | Select-Object -ExpandProperty StackId
        Write-Status "スタック更新: 開始 (ID: $stackId)" "SUCCESS"
    }
} catch {
    Write-Status "スタック更新: 失敗 - $_" "ERROR"
    exit 1
}

# ===== 3. ポーリングで更新状態を監視 =====
Write-Status "Step 3: 更新状態をポーリングで監視します..." "INFO"
$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$maxWaitSeconds = $MaxWaitMinutes * 60
$previousStatus = $null

while ($stopwatch.Elapsed.TotalSeconds -lt $maxWaitSeconds) {
    try {
        $stackInfo = aws cloudformation describe-stacks `
            --stack-name $StackName `
            --region $Region 2>&1 | ConvertFrom-Json
        
        $currentStatus = $stackInfo.Stacks[0].StackStatus
        $lastUpdated = $stackInfo.Stacks[0].LastUpdatedTime
        
        # ステータスが変わった場合に表示
        if ($currentStatus -ne $previousStatus) {
            $statusColor = switch -Regex ($currentStatus) {
                "COMPLETE$" { "SUCCESS" }
                "IN_PROGRESS$" { "INFO" }
                "ROLLBACK|FAILED" { "ERROR" }
                default { "WARNING" }
            }
            Write-Status "  スタックステータス: $currentStatus (更新時刻: $lastUpdated)" $statusColor
            $previousStatus = $currentStatus
        }
        
        # 更新完了チェック
        if ($currentStatus -match "UPDATE_COMPLETE|UPDATE_ROLLBACK_COMPLETE|CREATE_COMPLETE") {
            Write-Status "Step 3: 更新完了（ステータス: $currentStatus）" "SUCCESS"
            break
        }
        
        # エラー状態チェック
        if ($currentStatus -match "FAILED|ROLLBACK_IN_PROGRESS") {
            Write-Status "Step 3: 更新失敗（ステータス: $currentStatus）" "ERROR"
            
            # イベント情報を取得
            $events = aws cloudformation describe-stack-events `
                --stack-name $StackName `
                --region $Region 2>&1 | ConvertFrom-Json
            
            Write-Status "失敗理由:" "ERROR"
            $events.StackEvents | Where-Object { $_.ResourceStatus -match "FAILED" } | ForEach-Object {
                Write-Host "  - リソース: $($_.LogicalResourceId)" -ForegroundColor Red
                Write-Host "    理由: $($_.ResourceStatusReason)" -ForegroundColor Red
            }
            exit 1
        }
        
        Start-Sleep -Seconds $PollingIntervalSeconds
    } catch {
        Write-Status "ポーリングエラー: $_" "WARNING"
        Start-Sleep -Seconds $PollingIntervalSeconds
    }
}

if ($stopwatch.Elapsed.TotalSeconds -ge $maxWaitSeconds) {
    Write-Status "タイムアウト: ${MaxWaitMinutes}分以内に更新が完了しませんでした" "ERROR"
    exit 1
}

$stopwatch.Stop()
Write-Status "Total: 処理完了 (経過時間: $([int]$stopwatch.Elapsed.TotalSeconds)秒)" "SUCCESS"

# ===== 4. スタックイベントログを取得 =====
Write-Status "Step 4: スタックイベントログを取得します..." "INFO"
try {
    $events = aws cloudformation describe-stack-events `
        --stack-name $StackName `
        --region $Region 2>&1 | ConvertFrom-Json
    
    Write-Status "最新10イベント:" "INFO"
    $events.StackEvents | Select-Object -First 10 | ForEach-Object {
        $statusColor = switch -Regex ($_.ResourceStatus) {
            "_COMPLETE$" { "Green" }
            "_IN_PROGRESS$" { "Cyan" }
            "FAILED" { "Red" }
            default { "Yellow" }
        }
        $timestamp = Get-Date -Date $_.Timestamp -Format "HH:mm:ss"
        Write-Host "  [$timestamp] $($_.LogicalResourceId): $($_.ResourceStatus)" -ForegroundColor $statusColor
        if ($_.ResourceStatusReason) {
            Write-Host "            理由: $($_.ResourceStatusReason)" -ForegroundColor Gray
        }
    }
    Write-Status "イベントログ取得: 完了" "SUCCESS"
} catch {
    Write-Status "イベントログ取得: 失敗 - $_" "WARNING"
}

# ===== 5. スタック出力情報を表示 =====
Write-Status "Step 5: スタック出力情報を表示します..." "INFO"
try {
    $stackInfo = aws cloudformation describe-stacks `
        --stack-name $StackName `
        --region $Region 2>&1 | ConvertFrom-Json
    
    if ($stackInfo.Stacks[0].Outputs) {
        Write-Status "スタック出力:" "SUCCESS"
        $stackInfo.Stacks[0].Outputs | ForEach-Object {
            Write-Host "  - $($_.OutputKey): $($_.OutputValue)" -ForegroundColor Green
        }
    }
} catch {
    Write-Status "スタック出力情報取得: 失敗 - $_" "WARNING"
}

Write-Status "===== 処理完了 =====" "SUCCESS"