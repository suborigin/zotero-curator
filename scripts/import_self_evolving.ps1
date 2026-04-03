param(
    [string]$PlanPath = "examples/self-evolving-agent-plan.yaml",
    [switch]$KeepClientEnv
)

$ErrorActionPreference = "Stop"

function Read-SecretText {
    param([string]$Prompt)

    $secure = Read-Host -Prompt $Prompt -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
        if ($bstr -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        }
    }
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not (Test-Path $PlanPath)) {
    throw "Plan file not found: $PlanPath"
}

if (-not $env:ZOTERO_OAUTH_CLIENT_KEY) {
    $env:ZOTERO_OAUTH_CLIENT_KEY = Read-Host "Enter Zotero OAuth client key"
}

if (-not $env:ZOTERO_OAUTH_CLIENT_SECRET) {
    $env:ZOTERO_OAUTH_CLIENT_SECRET = Read-SecretText "Enter Zotero OAuth client secret"
}

try {
    python -m zotero_curator.cli sync `
        --plan $PlanPath `
        --oauth-authorize `
        --delete-api-key-after `
        --exclusive-target-collection
}
finally {
    if (-not $KeepClientEnv) {
        Remove-Item Env:ZOTERO_OAUTH_CLIENT_KEY -ErrorAction SilentlyContinue
        Remove-Item Env:ZOTERO_OAUTH_CLIENT_SECRET -ErrorAction SilentlyContinue
    }
}
