[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("encrypt", "decrypt")]
    [string]$Action,

    [Parameter(Position = 1)]
    [string]$KeyFile,

    [Parameter()]
    [string]$Key,

    [Parameter()]
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repoRoot

if ($KeyFile) {
    $resolvedKeyFile = (Resolve-Path $KeyFile -ErrorAction Stop).Path
    $env:SOPS_AGE_KEY_FILE = $resolvedKeyFile
}
if ($Key) {
    $env:SOPS_AGE_KEY = $Key
}

function ConvertTo-LF {
    param([string]$Path)
    $enc = [System.Text.UTF8Encoding]::new($false)
    $content = [System.IO.File]::ReadAllText($Path, $enc)
    [System.IO.File]::WriteAllText($Path, $content.Replace("`r`n", "`n").Replace("`r", "`n"), $enc)
}

$files = @(
    ".env",
    ".envs/.local/.django",
    ".envs/.local/.postgres",
    ".envs/.production/.django",
    ".envs/.production/.postgres"
)

foreach ($plainFile in $files) {
    $encryptedFile = "$plainFile.enc"
    if ($Action -eq "encrypt") {
        if ([string]::IsNullOrWhiteSpace($env:SOPS_AGE_RECIPIENT) -or $env:SOPS_AGE_RECIPIENT -eq "age1...") {
            throw "Set SOPS_AGE_RECIPIENT to the real age public key from keys.txt. The placeholder age1... is not valid."
        }
        if (-not (Test-Path $plainFile)) {
            throw "Plaintext file not found: $plainFile"
        }
        if (-not $Force -and (Test-Path $encryptedFile) -and
            (Get-Item $encryptedFile).LastWriteTimeUtc -gt (Get-Item $plainFile).LastWriteTimeUtc) {
            Write-Host "Skipping $plainFile (unchanged)"
            continue
        }
        ConvertTo-LF (Join-Path $repoRoot $plainFile)
        & sops --encrypt --age $env:SOPS_AGE_RECIPIENT --input-type dotenv --output-type dotenv --output $encryptedFile $plainFile
        if ($LASTEXITCODE -ne 0) {
            throw "SOPS failed to encrypt $plainFile"
        }
        Write-Host "Encrypted $plainFile -> $encryptedFile"
    } else {
        if ([string]::IsNullOrWhiteSpace($env:SOPS_AGE_KEY_FILE) -and [string]::IsNullOrWhiteSpace($env:SOPS_AGE_KEY)) {
            throw "Provide -Key <private-key>, -KeyFile <path>, SOPS_AGE_KEY, or SOPS_AGE_KEY_FILE"
        }
        if (-not (Test-Path $encryptedFile)) {
            throw "Encrypted file not found: $encryptedFile"
        }
        ConvertTo-LF (Join-Path $repoRoot $encryptedFile)
        & sops --decrypt --input-type dotenv --output-type dotenv --output $plainFile $encryptedFile
        if ($LASTEXITCODE -ne 0) {
            throw "SOPS failed to decrypt $encryptedFile"
        }
        ConvertTo-LF (Join-Path $repoRoot $plainFile)
        Write-Host "Decrypted $encryptedFile -> $plainFile"
    }
}
