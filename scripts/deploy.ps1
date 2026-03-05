#!/usr/bin/env pwsh
<#
.SYNOPSIS
  VAROS — one-command Fly.io deployment script.

.DESCRIPTION
  Run this ONCE to create the app, volume, set secrets, and deploy.
  After the first run, every push to main auto-deploys via GitHub Actions.

.PREREQUISITES
  1. flyctl installed  : iwr https://fly.io/install.ps1 -useb | iex
  2. flyctl logged in  : flyctl auth login
  3. gh CLI installed  : winget install GitHub.cli  (for GitHub secret step)
  4. gh logged in      : gh auth login

.USAGE
  .\scripts\deploy.ps1 `
    -AnthropicKey "sk-ant-..." `
    -NcbiEmail    "you@lab.edu" `
    -SecretKey    "change-me-to-random-32-chars"

  Optional (billing + email):
    -StripeSecretKey        "sk_test_..." `
    -StripeWebhookSecret    "whsec_..." `
    -StripeStarterPriceId   "price_..." `
    -StripeProPriceId       "price_..." `
    -SendgridApiKey         "SG...." `
    -SendgridFromEmail      "alerts@yourdomain.com"
#>

param(
    # Required
    [Parameter(Mandatory=$true)]  [string] $AnthropicKey,
    [Parameter(Mandatory=$true)]  [string] $NcbiEmail,
    [Parameter(Mandatory=$true)]  [string] $SecretKey,

    # Optional — app works without these (billing + email degrade gracefully)
    [string] $StripeSecretKey      = "",
    [string] $StripeWebhookSecret  = "",
    [string] $StripeStarterPriceId = "",
    [string] $StripeProPriceId     = "",
    [string] $SendgridApiKey       = "",
    [string] $SendgridFromEmail    = "alerts@varos.io",
    [string] $OpenAiKey            = "",
    [string] $NcbiApiKey           = "",
    [string] $OmimApiKey           = "",
    [string] $OnckbToken           = "",

    # Fly.io config
    [string] $AppName   = "varos-api",
    [string] $Region    = "iad",
    [int]    $VolumeGb  = 3
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$fly = "$env:USERPROFILE\.fly\bin\flyctl.exe"
if (-not (Test-Path $fly)) {
    Write-Error "flyctl not found. Install with: iwr https://fly.io/install.ps1 -useb | iex"
    exit 1
}

function Run-Fly {
    param([string[]] $FlyArgs)
    & $fly @FlyArgs
    if ($LASTEXITCODE -ne 0) { throw "flyctl $($FlyArgs[0]) failed (exit $LASTEXITCODE)" }
}

Write-Host "`n=== VAROS Fly.io Deployment ===" -ForegroundColor Cyan

# ---- 1. Verify auth ----
Write-Host "`n[1/6] Verifying Fly.io authentication..." -ForegroundColor Yellow
try {
    $whoami = & $fly auth whoami 2>&1
    Write-Host "  Logged in as: $whoami" -ForegroundColor Green
} catch {
    Write-Error "Not logged in. Run: & '$fly' auth login"
    exit 1
}

# ---- 2. Create app (idempotent) ----
Write-Host "`n[2/6] Creating app '$AppName'..." -ForegroundColor Yellow
$existingApps = & $fly apps list 2>&1
if ("$existingApps" -match $AppName) {
    Write-Host "  App '$AppName' already exists — skipping create." -ForegroundColor DarkGray
} else {
    Run-Fly @("apps", "create", $AppName)
    Write-Host "  Created app '$AppName'" -ForegroundColor Green
}

# ---- 3. Create persistent volume (idempotent) ----
Write-Host "`n[3/6] Creating persistent volume (${VolumeGb}GB)..." -ForegroundColor Yellow
$existingVols = & $fly volumes list --app $AppName 2>&1
if ("$existingVols" -match "varos_data") {
    Write-Host "  Volume 'varos_data' already exists — skipping create." -ForegroundColor DarkGray
} else {
    Run-Fly @("volumes", "create", "varos_data", "--app", $AppName, "--size", "$VolumeGb", "--region", $Region, "--yes")
    Write-Host "  Created volume 'varos_data' (${VolumeGb}GB)" -ForegroundColor Green
}

# ---- 4. Set secrets ----
Write-Host "`n[4/6] Setting secrets..." -ForegroundColor Yellow

$secrets = [System.Collections.Generic.List[string]]@(
    "ANTHROPIC_API_KEY=$AnthropicKey",
    "NCBI_EMAIL=$NcbiEmail",
    "SECRET_KEY=$SecretKey"
)
if ($StripeSecretKey)      { $secrets.Add("STRIPE_SECRET_KEY=$StripeSecretKey") }
if ($StripeWebhookSecret)  { $secrets.Add("STRIPE_WEBHOOK_SECRET=$StripeWebhookSecret") }
if ($StripeStarterPriceId) { $secrets.Add("STRIPE_STARTER_PRICE_ID=$StripeStarterPriceId") }
if ($StripeProPriceId)     { $secrets.Add("STRIPE_PRO_PRICE_ID=$StripeProPriceId") }
if ($SendgridApiKey)       { $secrets.Add("SENDGRID_API_KEY=$SendgridApiKey") }
if ($SendgridFromEmail)    { $secrets.Add("SENDGRID_FROM_EMAIL=$SendgridFromEmail") }
if ($OpenAiKey)            { $secrets.Add("OPENAI_API_KEY=$OpenAiKey") }
if ($NcbiApiKey)           { $secrets.Add("NCBI_API_KEY=$NcbiApiKey") }
if ($OmimApiKey)           { $secrets.Add("OMIM_API_KEY=$OmimApiKey") }
if ($OnckbToken)           { $secrets.Add("ONCKB_API_TOKEN=$OnckbToken") }

$secretArgs = @("secrets", "set", "--app", $AppName) + $secrets.ToArray()
Run-Fly $secretArgs
Write-Host "  Secrets set ($($secrets.Count) values)" -ForegroundColor Green

# ---- 5. Deploy ----
Write-Host "`n[5/6] Deploying (this takes ~3-5 min for first build)..." -ForegroundColor Yellow
Run-Fly @("deploy", "--app", $AppName, "--config", "fly.toml", "--remote-only")
Write-Host "  Deployed!" -ForegroundColor Green

# ---- 6. Verify ----
Write-Host "`n[6/6] Verifying deployment..." -ForegroundColor Yellow
Start-Sleep -Seconds 8

$url = "https://$AppName.fly.dev"
try {
    $resp = Invoke-RestMethod -Uri "$url/health" -TimeoutSec 30
    Write-Host "  Health check PASSED" -ForegroundColor Green
    Write-Host "  Status  : $($resp.status)"
    Write-Host "  Version : $($resp.version)"
    Write-Host "  LLM     : $($resp.llm_available)"
} catch {
    Write-Warning "  Health check pending — app may still be warming up."
    Write-Warning "  Check logs: & '$fly' logs --app $AppName"
}

# ---- 7. Set FLY_API_TOKEN in GitHub for auto-deploy ----
Write-Host "`n[Bonus] Wiring auto-deploy via GitHub Actions..." -ForegroundColor Yellow
$ghAvailable = Get-Command gh -ErrorAction SilentlyContinue
if ($ghAvailable) {
    $token = (& $fly tokens create deploy --app $AppName 2>&1) | Select-Object -Last 1
    if ("$token" -match "^FlyV1") {
        gh secret set FLY_API_TOKEN --body "$token" --repo zekariasasaminew/varos
        Write-Host "  FLY_API_TOKEN set in GitHub — every push to main now auto-deploys!" -ForegroundColor Green
    } else {
        Write-Warning "  Could not extract token automatically."
        Write-Warning "  Run manually: & '$fly' tokens create deploy --app $AppName"
        Write-Warning "  Then: gh secret set FLY_API_TOKEN --body '<token>' --repo zekariasasaminew/varos"
    }
} else {
    Write-Warning "  gh CLI not found. To enable auto-deploy:"
    Write-Warning "  1. Run: & '$fly' tokens create deploy --app $AppName"
    Write-Warning "  2. Add as FLY_API_TOKEN in https://github.com/zekariasasaminew/varos/settings/secrets/actions"
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host " VAROS is LIVE!" -ForegroundColor Green
Write-Host " API       : $url" -ForegroundColor White
Write-Host " Swagger   : $url/docs" -ForegroundColor White
Write-Host " Health    : $url/health" -ForegroundColor White
Write-Host "========================================`n" -ForegroundColor Cyan
Write-Host "Next: register an account and classify your first variant:" -ForegroundColor Yellow
Write-Host "  curl -X POST $url/v1/register -H 'Content-Type: application/json' -d '{`"email`":`"you@lab.edu`",`"name`":`"Test`"}'" -ForegroundColor Gray
