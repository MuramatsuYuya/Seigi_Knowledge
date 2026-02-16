# =====================================================
# Agent Aliasのバージョン切り替えスクリプト
# =====================================================

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("default", "verification", "specification", "all")]
    [string]$AgentType,
    
    [string]$Version = "",  # 空の場合は最新バージョンを使用
    [string]$Region = "us-west-2"
)

$ErrorActionPreference = "Stop"

# Agent情報
$agents = @{
    "default" = @{
        Name = "AI質問Agent"
        AgentId = "M89ZN5FKB4"
        AliasName = "production"
    }
    "verification" = @{
        Name = "検証計画Agent"
        AgentId = "S8BOQ5QBEU"
        AliasName = "production"
    }
    "specification" = @{
        Name = "仕様書作成Agent"
        AgentId = "T09BSIALNO"
        AliasName = "production"
    }
}

function Update-AgentAliasVersion {
    param($AgentInfo, $TargetVersion)
    
    $agentId = $AgentInfo.AgentId
    $aliasName = $AgentInfo.AliasName
    
    Write-Host "`n=== $($AgentInfo.Name) ($agentId) ===" -ForegroundColor Cyan
    
    # 現在のエイリアス情報を取得
    $aliases = aws bedrock-agent list-agent-aliases `
        --agent-id $agentId `
        --region $Region | ConvertFrom-Json
    
    $alias = $aliases.agentAliasSummaries | Where-Object { $_.agentAliasName -eq $aliasName } | Select-Object -First 1
    
    if (-not $alias) {
        Write-Host "✗ エラー: '$aliasName' エイリアスが見つかりません" -ForegroundColor Red
        return $false
    }
    
    $aliasId = $alias.agentAliasId
    $currentVersion = $alias.routingConfiguration[0].agentVersion
    
    Write-Host "現在のバージョン: $currentVersion (Alias ID: $aliasId)"
    
    # バージョンが指定されていない場合は最新を取得
    if ([string]::IsNullOrEmpty($TargetVersion)) {
        $versions = aws bedrock-agent list-agent-versions `
            --agent-id $agentId `
            --region $Region `
            --query "agentVersionSummaries[?agentStatus=='PREPARED'].agentVersion" `
            --output json | ConvertFrom-Json
        
        $TargetVersion = ($versions | Measure-Object -Maximum).Maximum
        Write-Host "最新バージョン: $TargetVersion"
    }
    
    if ($currentVersion -eq $TargetVersion) {
        Write-Host "✓ 既に指定バージョンです: $TargetVersion" -ForegroundColor Green
        return $true
    }
    
    # バージョン更新
    Write-Host "バージョンを更新中: $currentVersion → $TargetVersion ..." -ForegroundColor Yellow
    
    aws bedrock-agent update-agent-alias `
        --agent-id $agentId `
        --agent-alias-id $aliasId `
        --agent-alias-name $aliasName `
        --region $Region | Out-Null
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ バージョン更新完了: $TargetVersion" -ForegroundColor Green
        return $true
    } else {
        Write-Host "✗ 更新失敗" -ForegroundColor Red
        return $false
    }
}

# メイン処理
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Agent Aliasバージョン切り替えスクリプト" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

if ($AgentType -eq "all") {
    # 全Agent更新
    $success = $true
    foreach ($key in $agents.Keys) {
        $result = Update-AgentAliasVersion -AgentInfo $agents[$key] -TargetVersion $Version
        $success = $success -and $result
    }
    
    Write-Host "`n========================================" -ForegroundColor Cyan
    if ($success) {
        Write-Host "✓ 全Agent更新完了" -ForegroundColor Green
    } else {
        Write-Host "✗ 一部のAgentで更新に失敗しました" -ForegroundColor Red
    }
} else {
    # 個別Agent更新
    $result = Update-AgentAliasVersion -AgentInfo $agents[$AgentType] -TargetVersion $Version
    
    Write-Host "`n========================================" -ForegroundColor Cyan
    if ($result) {
        Write-Host "✓ 更新完了" -ForegroundColor Green
    } else {
        Write-Host "✗ 更新失敗" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "使用方法:" -ForegroundColor Yellow
Write-Host "  # 最新バージョンに更新" -ForegroundColor White
Write-Host "  .\update-agent-alias-version.ps1 -AgentType all" -ForegroundColor Cyan
Write-Host ""
Write-Host "  # 特定のAgentだけ更新" -ForegroundColor White
Write-Host "  .\update-agent-alias-version.ps1 -AgentType verification" -ForegroundColor Cyan
Write-Host ""
Write-Host "  # 特定のバージョンを指定" -ForegroundColor White
Write-Host "  .\update-agent-alias-version.ps1 -AgentType default -Version 3" -ForegroundColor Cyan
