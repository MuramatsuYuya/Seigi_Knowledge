#!/usr/bin/env pwsh
<#
.SYNOPSIS
    CloudFormation Two-Region Deployment Script
    WAF (us-east-1) + Main Stack (us-west-2)

.DESCRIPTION
    CloudFront用のWAFをus-east-1でデプロイし、
    その他のリソースをus-west-2でデプロイします。

.EXAMPLE
    .\deploy-waf-and-stack.ps1
    .\deploy-waf-and-stack.ps1 -ProjectName "doctoknow-prod" -Environment "prod"
#>

param(
    [string]$ProjectName = "doctoknow-dev",
    [string]$Environment = "dev",
    [string]$AllowedIPs = "192.218.140.236/32,192.218.140.237/32,192.218.140.238/32,192.218.140.239/32,192.218.140.240/32,192.218.140.241/32,10.166.0.0/16",
    [string]$FrontendBucket = "doctoknow-seigi25-frontend",
    [string]$DataBucket = "doctoknow-seigi25-data",
    [string]$BedrockAgentId = "M89ZN5FKB4",
    [string]$BedrockAgentAliasId = "HZHJZIHUHR",
    [string]$VerificationAgentId = "",
    [string]$VerificationAgentAliasId = "",
    [string]$SpecificationAgentId = "",
    [string]$SpecificationAgentAliasId = ""
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "CloudFormation Two-Region Deployment" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Configuration:" -ForegroundColor Yellow
Write-Host "  Project Name: $ProjectName"
Write-Host "  Environment: $Environment"
Write-Host "  WAF Region: us-east-1"
Write-Host "  Main Region: us-west-2"
Write-Host ""

$scriptDir = $PSScriptRoot
$wafTemplate = Join-Path $scriptDir "cloudformation-waf-template.json"
$mainTemplate = Join-Path $scriptDir "cloudformation-doctoknow-template.json"

# Verify templates exist
if (-not (Test-Path $wafTemplate)) {
    Write-Host "✗ WAF template not found: $wafTemplate" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $mainTemplate)) {
    Write-Host "✗ Main template not found: $mainTemplate" -ForegroundColor Red
    exit 1
}

Write-Host "✓ Templates found" -ForegroundColor Green
Write-Host ""

# ===================================================
# Step 1: Deploy WAF to us-east-1
# ===================================================
Write-Host "[1/3] Deploying WAF to us-east-1..." -ForegroundColor Yellow

$wafStackName = "$ProjectName-waf"
$wafStackExists = $false

try {
    $wafStatus = aws cloudformation describe-stacks `
        --stack-name $wafStackName `
        --region us-east-1 `
        --query 'Stacks[0].StackStatus' `
        --output text 2>&1
    
    if ($LASTEXITCODE -eq 0) {
        $wafStackExists = $true
        Write-Host "  ⏳ WAF stack exists (status: $wafStatus). Updating..." -ForegroundColor Yellow
        
        aws cloudformation update-stack `
            --stack-name $wafStackName `
            --template-body file://$wafTemplate `
            --parameters `
                ParameterKey=ProjectName,UsePreviousValue=true `
                ParameterKey=Environment,UsePreviousValue=true `
                ParameterKey=AllowedIPAddresses,ParameterValue="$AllowedIPs" `
            --region us-east-1
        
        $waitCommand = "stack-update-complete"
    }
} catch {
    $wafStackExists = $false
}

if (-not $wafStackExists) {
    Write-Host "  Creating new WAF stack..." -ForegroundColor Yellow
    
    aws cloudformation create-stack `
        --stack-name $wafStackName `
        --template-body file://$wafTemplate `
        --parameters `
            ParameterKey=ProjectName,ParameterValue=$ProjectName `
            ParameterKey=Environment,ParameterValue=$Environment `
            ParameterKey=AllowedIPAddresses,ParameterValue="$AllowedIPs" `
        --region us-east-1
    
    $waitCommand = "stack-create-complete"
}

Write-Host "  ⏳ Waiting for WAF stack to complete..." -ForegroundColor Yellow

aws cloudformation wait $waitCommand `
    --stack-name $wafStackName `
    --region us-east-1

if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ WAF stack deployment failed" -ForegroundColor Red
    exit 1
}

Write-Host "✓ WAF stack deployed successfully" -ForegroundColor Green

# Get WebACL ARN
$WebACLArn = aws cloudformation describe-stacks `
    --stack-name $wafStackName `
    --region us-east-1 `
    --query 'Stacks[0].Outputs[?OutputKey==`WebACLArn`].OutputValue' `
    --output text

if (-not $WebACLArn) {
    Write-Host "✗ Failed to retrieve WebACL ARN" -ForegroundColor Red
    exit 1
}

Write-Host "  WebACL ARN: $WebACLArn" -ForegroundColor Cyan
Write-Host ""

# ===================================================
# Step 2: Deploy Main Stack to us-west-2
# ===================================================
Write-Host "[2/3] Deploying Main Stack to us-west-2..." -ForegroundColor Yellow

$mainStackName = "$ProjectName-stack"
$mainStackExists = $false

try {
    $mainStatus = aws cloudformation describe-stacks `
        --stack-name $mainStackName `
        --region us-west-2 `
        --query 'Stacks[0].StackStatus' `
        --output text 2>&1
    
    if ($LASTEXITCODE -eq 0) {
        $mainStackExists = $true
        Write-Host "  ⏳ Main stack exists (status: $mainStatus). Updating..." -ForegroundColor Yellow
        
        aws cloudformation update-stack `
            --stack-name $mainStackName `
            --template-body file://$mainTemplate `
            --parameters `
                ParameterKey=ProjectName,UsePreviousValue=true `
                ParameterKey=Environment,UsePreviousValue=true `
                ParameterKey=FrontendS3BucketName,UsePreviousValue=true `
                ParameterKey=DataS3BucketNameParam,UsePreviousValue=true `
                ParameterKey=WebACLArn,ParameterValue=$WebACLArn `
                ParameterKey=BedrockAgentId,ParameterValue=$BedrockAgentId `
                ParameterKey=BedrockAgentAliasId,ParameterValue=$BedrockAgentAliasId `
                ParameterKey=VerificationAgentId,ParameterValue=$VerificationAgentId `
                ParameterKey=VerificationAgentAliasId,ParameterValue=$VerificationAgentAliasId `
                ParameterKey=SpecificationAgentId,ParameterValue=$SpecificationAgentId `
                ParameterKey=SpecificationAgentAliasId,ParameterValue=$SpecificationAgentAliasId `
            --capabilities CAPABILITY_IAM `
            --region us-west-2
        
        $waitCommand = "stack-update-complete"
    }
} catch {
    $mainStackExists = $false
}

if (-not $mainStackExists) {
    Write-Host "  Creating new Main stack..." -ForegroundColor Yellow
    
    aws cloudformation create-stack `
        --stack-name $mainStackName `
        --template-body file://$mainTemplate `
        --parameters `
            ParameterKey=ProjectName,ParameterValue=$ProjectName `
            ParameterKey=Environment,ParameterValue=$Environment `
            ParameterKey=FrontendS3BucketName,ParameterValue=$FrontendBucket `
            ParameterKey=DataS3BucketNameParam,ParameterValue=$DataBucket `
            ParameterKey=WebACLArn,ParameterValue=$WebACLArn `
            ParameterKey=BedrockAgentId,ParameterValue=$BedrockAgentId `
            ParameterKey=BedrockAgentAliasId,ParameterValue=$BedrockAgentAliasId `
            ParameterKey=VerificationAgentId,ParameterValue=$VerificationAgentId `
            ParameterKey=VerificationAgentAliasId,ParameterValue=$VerificationAgentAliasId `
            ParameterKey=SpecificationAgentId,ParameterValue=$SpecificationAgentId `
            ParameterKey=SpecificationAgentAliasId,ParameterValue=$SpecificationAgentAliasId `
        --capabilities CAPABILITY_IAM `
        --region us-west-2
    
    $waitCommand = "stack-create-complete"
}

Write-Host "  ⏳ Waiting for Main stack to complete..." -ForegroundColor Yellow

aws cloudformation wait $waitCommand `
    --stack-name $mainStackName `
    --region us-west-2

if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ Main stack deployment failed" -ForegroundColor Red
    exit 1
}

Write-Host "✓ Main stack deployed successfully" -ForegroundColor Green
Write-Host ""

# ===================================================
# Step 3: Display Results
# ===================================================
Write-Host "[3/3] Deployment Summary" -ForegroundColor Yellow

$outputs = aws cloudformation describe-stacks `
    --stack-name $mainStackName `
    --region us-west-2 `
    --query 'Stacks[0].Outputs' | ConvertFrom-Json

$cloudFrontUrl = ($outputs | Where-Object { $_.OutputKey -eq "FrontendUrl" }).OutputValue
$cloudFrontDomain = ($outputs | Where-Object { $_.OutputKey -eq "CloudFrontDomain" }).OutputValue
$apiEndpoint = ($outputs | Where-Object { $_.OutputKey -eq "APIGatewayEndpoint" }).OutputValue

Write-Host ""
Write-Host "✓ All deployments completed successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Access Information" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Frontend URL (Use this):" -ForegroundColor Yellow
Write-Host "  $cloudFrontUrl" -ForegroundColor White
Write-Host ""
Write-Host "CloudFront Domain:" -ForegroundColor Yellow
Write-Host "  $cloudFrontDomain" -ForegroundColor White
Write-Host ""
Write-Host "API Endpoint (CloudFront経由):" -ForegroundColor Yellow
Write-Host "  $cloudFrontDomain/api/*" -ForegroundColor White
Write-Host ""
Write-Host "WAF Configuration:" -ForegroundColor Yellow
Write-Host "  Stack: $wafStackName (us-east-1)" -ForegroundColor White
Write-Host "  WebACL ARN: $WebACLArn" -ForegroundColor White
Write-Host ""
Write-Host "Allowed IP Addresses:" -ForegroundColor Yellow
Write-Host "  $AllowedIPs" -ForegroundColor White
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host "  1. Upload frontend files: aws s3 sync frontend/ s3://$FrontendBucket/ --region us-west-2"
Write-Host "  2. Deploy Lambda functions: Update the Lambda functions with your code"
Write-Host "  3. Access the application: $cloudFrontUrl"
Write-Host ""
