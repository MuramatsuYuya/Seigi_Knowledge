# =====================================================
# Document to Knowledge System - Deployment Script
# HTML + JavaScript Frontend (No build required)
# =====================================================

param(
    [string]$FrontendS3BucketName = "doctoknow-frontend",
    [string]$DataS3BucketName = "doctoknow-data",
    [string]$CloudFormationStackName = "doctoknow-stack2",
    [string]$Region = "us-west-2",
    [string]$Environment = "dev",
    [string]$projectName = "doctoknow-dev2"

)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Document to Knowledge System - Deployment Script" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$scriptDir = $PSScriptRoot
$frontendDir = Join-Path $scriptDir "frontend"

# =====================================================
# 1. Prerequisites Check
# =====================================================
Write-Host "[1/6] Checking prerequisites..." -ForegroundColor Yellow

$backendDir = Join-Path $scriptDir "backend"

if (-not (Test-Path $frontendDir)) {
    Write-Host "✗ Frontend directory not found: $frontendDir" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $backendDir)) {
    Write-Host "✗ Backend directory not found: $backendDir" -ForegroundColor Red
    exit 1
}

Write-Host "✓ Prerequisites check passed" -ForegroundColor Green
Write-Host ""

# =====================================================
# 2. Check CloudFormation Stack Status
# =====================================================
Write-Host "[2/6] Checking existing CloudFormation stack..." -ForegroundColor Yellow
Write-Host "Stack name: $CloudFormationStackName" -ForegroundColor Cyan
Write-Host "Region: $Region" -ForegroundColor Cyan
Write-Host ""

try {
    $stackStatus = aws cloudformation describe-stacks `
        --stack-name $CloudFormationStackName `
        --region $Region `
        --query 'Stacks[0].StackStatus' `
        --output text 2>$null

    if ($LASTEXITCODE -ne 0) {
        Write-Host "✗ CloudFormation stack '$CloudFormationStackName' not found" -ForegroundColor Red
        Write-Host "Please create the stack manually first using the CloudFormation template" -ForegroundColor Yellow
        exit 1
    }
    
    Write-Host "✓ CloudFormation stack exists with status: $stackStatus" -ForegroundColor Green
    
    if ($stackStatus -notmatch "COMPLETE$") {
        Write-Host "⚠ Stack is not in a complete state. Current status: $stackStatus" -ForegroundColor Yellow
        Write-Host "Please ensure the stack deployment is complete before proceeding" -ForegroundColor Yellow
    }
} catch {
    Write-Host "✗ Error checking CloudFormation stack: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""

# =====================================================
# 3. Get Stack Outputs
# =====================================================
Write-Host "[2/6] Retrieving stack outputs..." -ForegroundColor Yellow

try {
    $stackOutputs = aws cloudformation describe-stacks `
        --stack-name $CloudFormationStackName `
        --region $Region `
        --query 'Stacks[0].Outputs' | ConvertFrom-Json

    $FrontendS3BucketActual = ($stackOutputs | Where-Object { $_.OutputKey -eq "FrontendS3BucketName" }).OutputValue
    $DataS3BucketActual = ($stackOutputs | Where-Object { $_.OutputKey -eq "DataS3BucketName" }).OutputValue
    $APIEndpoint = ($stackOutputs | Where-Object { $_.OutputKey -eq "APIGatewayEndpoint" }).OutputValue
    $CloudFrontDomain = ($stackOutputs | Where-Object { $_.OutputKey -eq "CloudFrontDomain" }).OutputValue
    $CloudFrontDistributionId = ($stackOutputs | Where-Object { $_.OutputKey -eq "CloudFrontDistributionId" }).OutputValue
    $APIProxyPath = ($stackOutputs | Where-Object { $_.OutputKey -eq "APIProxyPath" }).OutputValue
    
    Write-Host "✓ Frontend S3 Bucket: $FrontendS3BucketActual" -ForegroundColor Green
    Write-Host "✓ Data S3 Bucket: $DataS3BucketActual" -ForegroundColor Green
    Write-Host "✓ API Endpoint (Direct): $APIEndpoint" -ForegroundColor Green
    Write-Host "✓ CloudFront Domain: $CloudFrontDomain" -ForegroundColor Green
    Write-Host "✓ CloudFront Distribution ID: $CloudFrontDistributionId" -ForegroundColor Green
    Write-Host "✓ API Proxy Path: $APIProxyPath" -ForegroundColor Green
} catch {
    Write-Host "✗ Error retrieving stack outputs: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""

# =====================================================
# 3. Deploy Frontend Files
# =====================================================
Write-Host "[3/6] Uploading frontend files to S3..." -ForegroundColor Yellow
Write-Host "  Note: API calls are configured to use CloudFront proxy (/api/*)" -ForegroundColor Cyan
Write-Host "  Make sure CloudFront Origins and Behaviors are configured correctly" -ForegroundColor Cyan
Write-Host ""

try {
    # Prepare frontend files with proper charset
    Write-Host "  Preparing frontend files..." -ForegroundColor Cyan
    
    $frontendFiles = Get-ChildItem -Path $frontendDir -Recurse -File
    
    foreach ($file in $frontendFiles) {
        $relPath = $file.FullName.Substring($frontendDir.Length + 1)
        $s3Path = $relPath.Replace('\', '/')
        
        # Determine content type based on file extension
        $contentType = "application/octet-stream"
        switch ($file.Extension.ToLower()) {
            ".html" { $contentType = "text/html; charset=utf-8" }
            ".js"   { $contentType = "application/javascript; charset=utf-8" }
            ".css"  { $contentType = "text/css; charset=utf-8" }
            ".json" { $contentType = "application/json; charset=utf-8" }
            ".svg"  { $contentType = "image/svg+xml" }
            ".png"  { $contentType = "image/png" }
            ".jpg"  { $contentType = "image/jpeg" }
            ".gif"  { $contentType = "image/gif" }
            ".ico"  { $contentType = "image/x-icon" }
            ".woff" { $contentType = "font/woff" }
            ".woff2" { $contentType = "font/woff2" }
        }
        
        # For index.html, inject API configuration
        if ($file.Name -eq "index.html" -and $APIEndpoint) {
            Write-Host "  Injecting API endpoint and Cognito config into index.html..." -ForegroundColor Cyan
            
            # Read with UTF-8 encoding to preserve Japanese characters
            $htmlContent = Get-Content $file.FullName -Raw -Encoding UTF8
            
            # Get Cognito outputs from CloudFormation
            $CognitoUserPoolId = ($stackOutputs | Where-Object { $_.OutputKey -eq "CognitoUserPoolId" }).OutputValue
            $CognitoClientId = ($stackOutputs | Where-Object { $_.OutputKey -eq "CognitoClientId" }).OutputValue
            
            # Create API_CONFIG with endpoint, Cognito info, and Region
            $apiConfig = "window.API_CONFIG = window.API_CONFIG || { endpoint: '$APIEndpoint', cognitoUserPoolId: '$CognitoUserPoolId', cognitoClientId: '$CognitoClientId', region: '$Region' };"
            
            # Replace the API_CONFIG placeholder with actual endpoint and Cognito config
            # Security: Only non-secret configuration is injected
            $htmlContent = $htmlContent -replace `
                "window\.API_CONFIG\s*=\s*window\.API_CONFIG\s*\|\|\s*\{\};", `
                $apiConfig
            
            # Upload modified content with correct charset
            $tempHtmlFile = Join-Path $env:TEMP "index-$((Get-Date).Ticks).html"
            Set-Content -Path $tempHtmlFile -Value $htmlContent -NoNewline -Encoding UTF8
            
            aws s3 cp $tempHtmlFile "s3://$FrontendS3BucketActual/$s3Path" `
                --region $Region `
                --content-type $contentType `
                --metadata "Content-Type=$contentType" | Out-Null
            
            Remove-Item -Path $tempHtmlFile -Force -ErrorAction SilentlyContinue
            Write-Host "  ✓ index.html uploaded with API endpoint and Cognito config injected (UTF-8)" -ForegroundColor Green
            Write-Host "    - User Pool ID: $CognitoUserPoolId" -ForegroundColor Cyan
            Write-Host "    - Client ID: $CognitoClientId" -ForegroundColor Cyan
            Write-Host "    - Region: $Region" -ForegroundColor Cyan
        } else {
            # Upload other files with correct content type
            aws s3 cp $file.FullName "s3://$FrontendS3BucketActual/$s3Path" `
                --region $Region `
                --content-type $contentType | Out-Null
            
            Write-Host "  ✓ Uploaded: $s3Path ($contentType)" -ForegroundColor Green
        }
    }
    
    Write-Host "✓ Frontend files deployed successfully" -ForegroundColor Green
} catch {
    Write-Host "✗ Error uploading frontend files: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""

# =====================================================
# 4. Invalidate CloudFront Cache
# =====================================================
Write-Host "[4/6] Invalidating CloudFront cache..." -ForegroundColor Yellow

try {
    $CloudFrontDomain = ($stackOutputs | Where-Object { $_.OutputKey -eq "CloudFrontDomain" }).OutputValue
    
    if ($CloudFrontDomain) {
        # Get CloudFront distribution ID
        $distributionId = aws cloudfront list-distributions `
            --region $Region `
            --query "DistributionList.Items[?DomainName=='$CloudFrontDomain'].Id" `
            --output text 2>$null
        
        if ($distributionId -and $distributionId -ne "None") {
            # Create invalidation
            $invalidationId = aws cloudfront create-invalidation `
                --distribution-id $distributionId `
                --paths "/*" `
                --query 'Invalidation.Id' `
                --output text
            
            Write-Host "  ✓ CloudFront cache invalidation created: $invalidationId" -ForegroundColor Green
            Write-Host "  ✓ CloudFront Domain: $CloudFrontDomain" -ForegroundColor Green
        } else {
            Write-Host "  ⚠ CloudFront distribution not found, skipping cache invalidation" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  ⚠ CloudFront domain not found in stack outputs" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  ⚠ Error invalidating CloudFront cache: $_" -ForegroundColor Yellow
}

Write-Host ""

# =====================================================
# 5. Update Backend Lambda Functions
# =====================================================
Write-Host "[5/6] Updating backend Lambda functions..." -ForegroundColor Yellow

try {
    # Create temporary directory for ZIP files
    $tempDir = Join-Path $env:TEMP "lambda-deploy-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
    
    # Job Creator Lambda
    Write-Host "  Processing Job Creator Lambda..." -ForegroundColor Cyan
    $jobCreatorZip = Join-Path $tempDir "job-creator.zip"
    $jobCreatorPy = Join-Path $backendDir "job_creator.py"
    $folderTreeHelperPy = Join-Path $backendDir "folder_tree_helper.py"
    
    if (Test-Path $jobCreatorPy) {
        # Create ZIP file for Job Creator (include folder_tree_helper.py)
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $zip = [System.IO.Compression.ZipFile]::Open($jobCreatorZip, 'Create')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $jobCreatorPy, "index.py")
        
        # Add folder_tree_helper.py if it exists
        if (Test-Path $folderTreeHelperPy) {
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $folderTreeHelperPy, "folder_tree_helper.py")
            Write-Host "  ✓ Added folder_tree_helper.py to Job Creator package" -ForegroundColor Green
        }
        
        $zip.Dispose()
        
        # Update Job Creator Lambda
        $jobCreatorFunctionName = "$projectName-job-creator-v0"
        aws lambda update-function-code `
            --function-name $jobCreatorFunctionName `
            --zip-file "fileb://$jobCreatorZip" `
            --region $Region | Out-Null
            
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  ✓ Job Creator Lambda updated successfully" -ForegroundColor Green
        } else {
            Write-Host "  ✗ Failed to update Job Creator Lambda" -ForegroundColor Red
        }
    } else {
        Write-Host "  ⚠ job_creator.py not found, skipping" -ForegroundColor Yellow
    }
    
    # Worker Lambda
    Write-Host "  Processing Worker Lambda..." -ForegroundColor Cyan
    $workerZip = Join-Path $tempDir "worker.zip"
    $workerPy = Join-Path $backendDir "worker.py"
    
    if (Test-Path $workerPy) {
        # Create ZIP file for Worker
        $zip = [System.IO.Compression.ZipFile]::Open($workerZip, 'Create')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $workerPy, "index.py")
        $zip.Dispose()
        
        # Update Worker Lambda
        $workerFunctionName = "$projectName-worker-v0"
        aws lambda update-function-code `
            --function-name $workerFunctionName `
            --zip-file "fileb://$workerZip" `
            --region $Region | Out-Null
            
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  ✓ Worker Lambda updated successfully" -ForegroundColor Green
        } else {
            Write-Host "  ✗ Failed to update Worker Lambda" -ForegroundColor Red
        }
    } else {
        Write-Host "  ⚠ worker.py not found, skipping" -ForegroundColor Yellow
    }
    
    # Result Fetcher Lambda
    Write-Host "  Processing Result Fetcher Lambda..." -ForegroundColor Cyan
    $resultFetcherZip = Join-Path $tempDir "result-fetcher.zip"
    $resultFetcherPy = Join-Path $backendDir "result_fetcher.py"
    
    if (Test-Path $resultFetcherPy) {
        # Create ZIP file for Result Fetcher
        $zip = [System.IO.Compression.ZipFile]::Open($resultFetcherZip, 'Create')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $resultFetcherPy, "index.py")
        $zip.Dispose()
        
        # Update Result Fetcher Lambda
        $resultFetcherFunctionName = "$projectName-result-fetcher-v0"
        aws lambda update-function-code `
            --function-name $resultFetcherFunctionName `
            --zip-file "fileb://$resultFetcherZip" `
            --region $Region | Out-Null
            
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  ✓ Result Fetcher Lambda updated successfully" -ForegroundColor Green
        } else {
            Write-Host "  ✗ Failed to update Result Fetcher Lambda" -ForegroundColor Red
        }
    } else {
        Write-Host "  ⚠ result_fetcher.py not found, skipping" -ForegroundColor Yellow
    }
    
    # Knowledge Querier Lambda
    Write-Host "  Processing Knowledge Querier Lambda..." -ForegroundColor Cyan
    $knowledgeQuerierZip = Join-Path $tempDir "knowledge-querier.zip"
    $knowledgeQuerierPy = Join-Path $backendDir "knowledge_querier.py"
    
    if (Test-Path $knowledgeQuerierPy) {
        # Create ZIP file for Knowledge Querier
        $zip = [System.IO.Compression.ZipFile]::Open($knowledgeQuerierZip, 'Create')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $knowledgeQuerierPy, "index.py")
        $zip.Dispose()
        
        # Update Knowledge Querier Lambda
        $knowledgeQuerierFunctionName = "$projectName-knowledge-querier-v0"
        aws lambda update-function-code `
            --function-name $knowledgeQuerierFunctionName `
            --zip-file "fileb://$knowledgeQuerierZip" `
            --region $Region | Out-Null
            
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  ✓ Knowledge Querier Lambda updated successfully" -ForegroundColor Green
        } else {
            Write-Host "  ✗ Failed to update Knowledge Querier Lambda" -ForegroundColor Red
        }
    } else {
        Write-Host "  ⚠ knowledge_querier.py not found, skipping" -ForegroundColor Yellow
    }
    
    # Agent KB Action Lambda
    Write-Host "  Processing Agent KB Action Lambda..." -ForegroundColor Cyan
    $agentKBActionZip = Join-Path $tempDir "agent-kb-action.zip"
    $agentKBActionPy = Join-Path $backendDir "agent_kb_action.py"
    
    if (Test-Path $agentKBActionPy) {
        # Create ZIP file for Agent KB Action
        $zip = [System.IO.Compression.ZipFile]::Open($agentKBActionZip, 'Create')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $agentKBActionPy, "index.py")
        $zip.Dispose()
        
        # Update Agent KB Action Lambda
        $agentKBActionFunctionName = "$projectName-agent-kb-action-v0"
        aws lambda update-function-code `
            --function-name $agentKBActionFunctionName `
            --zip-file "fileb://$agentKBActionZip" `
            --region $Region | Out-Null
            
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  ✓ Agent KB Action Lambda updated successfully" -ForegroundColor Green
        } else {
            Write-Host "  ✗ Failed to update Agent KB Action Lambda" -ForegroundColor Red
        }
    } else {
        Write-Host "  ⚠ agent_kb_action.py not found, skipping" -ForegroundColor Yellow
    }
    
    # History Manager Lambda
    Write-Host "  Processing History Manager Lambda..." -ForegroundColor Cyan
    $historyManagerZip = Join-Path $tempDir "history-manager.zip"
    $historyManagerPy = Join-Path $backendDir "history_manager.py"
    
    if (Test-Path $historyManagerPy) {
        # Create ZIP file for History Manager
        $zip = [System.IO.Compression.ZipFile]::Open($historyManagerZip, 'Create')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $historyManagerPy, "index.py")
        $zip.Dispose()
        
        # Update History Manager Lambda
        $historyManagerFunctionName = "$projectName-history-manager-v0"
        aws lambda update-function-code `
            --function-name $historyManagerFunctionName `
            --zip-file "fileb://$historyManagerZip" `
            --region $Region | Out-Null
            
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  ✓ History Manager Lambda updated successfully" -ForegroundColor Green
        } else {
            Write-Host "  ✗ Failed to update History Manager Lambda" -ForegroundColor Red
        }
    } else {
        Write-Host "  ⚠ history_manager.py not found, skipping" -ForegroundColor Yellow
    }
    
    # Bedrock KB Sync Lambda
    Write-Host "  Processing Bedrock KB Sync Lambda..." -ForegroundColor Cyan
    $kbSyncZip = Join-Path $tempDir "kb-sync.zip"
    $kbSyncPy = Join-Path $backendDir "bedrock_kb_sync_lambda.py"
    
    if (Test-Path $kbSyncPy) {
        # Create ZIP file for KB Sync Lambda
        $zip = [System.IO.Compression.ZipFile]::Open($kbSyncZip, 'Create')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $kbSyncPy, "index.py")
        $zip.Dispose()
        
        # Update KB Sync Lambda
        $kbSyncFunctionName = "$projectName-bedrock-kb-sync-v0"
        aws lambda update-function-code `
            --function-name $kbSyncFunctionName `
            --zip-file "fileb://$kbSyncZip" `
            --region $Region | Out-Null
            
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  ✓ Bedrock KB Sync Lambda updated successfully" -ForegroundColor Green
        } else {
            Write-Host "  ✗ Failed to update Bedrock KB Sync Lambda" -ForegroundColor Red
        }
    } else {
        Write-Host "  ⚠ bedrock_kb_sync_lambda.py not found, skipping" -ForegroundColor Yellow
    }
    
    # Folder Management Lambda
    Write-Host "  Processing Folder Management Lambda..." -ForegroundColor Cyan
    $folderMgmtZip = Join-Path $tempDir "folder-management.zip"
    $folderMgmtPy = Join-Path $backendDir "folder_management_lambda.py"
    
    if (Test-Path $folderMgmtPy) {
        # Create ZIP file for Folder Management Lambda (include folder_tree_helper.py)
        $zip = [System.IO.Compression.ZipFile]::Open($folderMgmtZip, 'Create')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $folderMgmtPy, "index.py")
        
        # Add folder_tree_helper.py if it exists
        if (Test-Path $folderTreeHelperPy) {
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $folderTreeHelperPy, "folder_tree_helper.py")
            Write-Host "  ✓ Added folder_tree_helper.py to Folder Management package" -ForegroundColor Green
        }
        
        $zip.Dispose()
        
        # Update Folder Management Lambda
        $folderMgmtFunctionName = "$projectName-folder-management-v0"
        aws lambda update-function-code `
            --function-name $folderMgmtFunctionName `
            --zip-file "fileb://$folderMgmtZip" `
            --region $Region | Out-Null
            
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  ✓ Folder Management Lambda updated successfully" -ForegroundColor Green
        } else {
            Write-Host "  ✗ Failed to update Folder Management Lambda" -ForegroundColor Red
        }
    } else {
        Write-Host "  ⚠ folder_management_lambda.py not found, skipping" -ForegroundColor Yellow
    }
    
    # Prompt Management Lambda (新規追加)
    Write-Host "  Processing Prompt Management Lambda..." -ForegroundColor Cyan
    $promptMgmtZip = Join-Path $tempDir "prompt-management.zip"
    $promptMgmtPy = Join-Path $backendDir "prompt_management_lambda.py"
    
    if (Test-Path $promptMgmtPy) {
        # Create ZIP file for Prompt Management Lambda
        $zip = [System.IO.Compression.ZipFile]::Open($promptMgmtZip, 'Create')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $promptMgmtPy, "index.py")
        $zip.Dispose()
        
        # Update Prompt Management Lambda
        $promptMgmtFunctionName = "$projectName-prompt-management-v0"
        aws lambda update-function-code `
            --function-name $promptMgmtFunctionName `
            --zip-file "fileb://$promptMgmtZip" `
            --region $Region | Out-Null
            
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  ✓ Prompt Management Lambda updated successfully" -ForegroundColor Green
        } else {
            Write-Host "  ✗ Failed to update Prompt Management Lambda" -ForegroundColor Red
        }
    } else {
        Write-Host "  ⚠ prompt_management_lambda.py not found, skipping" -ForegroundColor Yellow
    }
    
    # Start Query Lambda (新規追加)
    Write-Host "  Processing Start Query Lambda..." -ForegroundColor Cyan
    $startQueryZip = Join-Path $tempDir "start-query.zip"
    $startQueryPy = Join-Path $backendDir "start_query_lambda.py"
    
    if (Test-Path $startQueryPy) {
        # Create ZIP file for Start Query Lambda
        $zip = [System.IO.Compression.ZipFile]::Open($startQueryZip, 'Create')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $startQueryPy, "index.py")
        $zip.Dispose()
        
        # Update Start Query Lambda
        $startQueryFunctionName = "$projectName-start-query-v0"
        aws lambda update-function-code `
            --function-name $startQueryFunctionName `
            --zip-file "fileb://$startQueryZip" `
            --region $Region | Out-Null
            
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  ✓ Start Query Lambda updated successfully" -ForegroundColor Green
        } else {
            Write-Host "  ✗ Failed to update Start Query Lambda" -ForegroundColor Red
        }
    } else {
        Write-Host "  ⚠ start_query_lambda.py not found, skipping" -ForegroundColor Yellow
    }
    
    # Poll Status Lambda (新規追加)
    Write-Host "  Processing Poll Status Lambda..." -ForegroundColor Cyan
    $pollStatusZip = Join-Path $tempDir "poll-status.zip"
    $pollStatusPy = Join-Path $backendDir "poll_status_lambda.py"
    
    if (Test-Path $pollStatusPy) {
        # Create ZIP file for Poll Status Lambda
        $zip = [System.IO.Compression.ZipFile]::Open($pollStatusZip, 'Create')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $pollStatusPy, "index.py")
        $zip.Dispose()
        
        # Update Poll Status Lambda
        $pollStatusFunctionName = "$projectName-poll-status-v0"
        aws lambda update-function-code `
            --function-name $pollStatusFunctionName `
            --zip-file "fileb://$pollStatusZip" `
            --region $Region | Out-Null
            
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  ✓ Poll Status Lambda updated successfully" -ForegroundColor Green
        } else {
            Write-Host "  ✗ Failed to update Poll Status Lambda" -ForegroundColor Red
        }
    } else {
        Write-Host "  ⚠ poll_status_lambda.py not found, skipping" -ForegroundColor Yellow
    }
    
    # Cleanup temporary files
    Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    
} catch {
    Write-Host "✗ Error updating backend Lambda functions: $_" -ForegroundColor Red
    # Cleanup on error
    if (Test-Path $tempDir) {
        Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    exit 1
}

Write-Host ""

# =====================================================
# 6. Update API Gateway Stage
# =====================================================
Write-Host "[6/6] Updating API Gateway stage..." -ForegroundColor Yellow

try {
    # Extract API Gateway ID from endpoint URL
    if ($APIEndpoint -match "https://([^.]+)\.execute-api\.") {
        $apiGatewayId = $matches[1]
        
        # Create new deployment
        $deploymentId = aws apigateway create-deployment `
            --rest-api-id $apiGatewayId `
            --stage-name $Environment `
            --region $Region `
            --query 'id' `
            --output text 2>$null
        
        if ($LASTEXITCODE -eq 0 -and $deploymentId -ne "None") {
            Write-Host "  ✓ API Gateway stage updated with deployment: $deploymentId" -ForegroundColor Green
        } else {
            Write-Host "  ⚠ API Gateway stage update failed or not needed" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  ⚠ Could not extract API Gateway ID from endpoint" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  ⚠ Error updating API Gateway stage: $_" -ForegroundColor Yellow
}

Write-Host ""

# =====================================================
# Summary & Website Access
# =====================================================
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Deployment Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "System Information:" -ForegroundColor Cyan
Write-Host "  Frontend S3 Bucket: $FrontendS3BucketActual" -ForegroundColor White
Write-Host "  Data S3 Bucket: $DataS3BucketActual" -ForegroundColor White
Write-Host "  API Endpoint (Direct): $APIEndpoint" -ForegroundColor White
Write-Host "  CloudFront Domain: $CloudFrontDomain" -ForegroundColor White
Write-Host "  CloudFront Distribution ID: $CloudFrontDistributionId" -ForegroundColor White
Write-Host "  Region: $Region" -ForegroundColor White
Write-Host "  Environment: $Environment" -ForegroundColor White
Write-Host ""
Write-Host "Architecture:" -ForegroundColor Cyan
Write-Host "  Static Files: https://$CloudFrontDomain/* (from S3)" -ForegroundColor White
Write-Host "  API Calls: https://$CloudFrontDomain/api/* (proxied to API Gateway)" -ForegroundColor White
Write-Host ""

# Open website automatically
if ($CloudFrontDomain) {
    $websiteUrl = "https://$CloudFrontDomain/index.html"
    Write-Host "🌐 Website URL:" -ForegroundColor Cyan
    Write-Host "   $websiteUrl" -ForegroundColor White
    Write-Host ""
    
    # Try to open the website in default browser
    try {
        Start-Process $websiteUrl
        Write-Host "  ✓ Website opened in default browser" -ForegroundColor Green
    } catch {
        Write-Host "  ⚠ Could not auto-open browser. Please manually visit the URL above." -ForegroundColor Yellow
    }
} else {
    Write-Host "⚠ CloudFront domain not available. Check AWS Console for the distribution URL." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host "  1. Upload PDF files to: s3://$DataS3BucketActual/PDF/" -ForegroundColor White
Write-Host "  2. Verify API is working by accessing: https://$CloudFrontDomain/api/job" -ForegroundColor White
Write-Host "  3. Monitor Lambda execution in CloudWatch Logs" -ForegroundColor White
Write-Host "  4. Test the system by uploading a PDF through the web interface" -ForegroundColor White
Write-Host ""
Write-Host "Cache Management:" -ForegroundColor Cyan
Write-Host "  To invalidate CloudFront cache (if needed):" -ForegroundColor White
Write-Host "  aws cloudfront create-invalidation --distribution-id $CloudFrontDistributionId --paths \"/*\" --region $Region" -ForegroundColor White
Write-Host ""