# SOPS Environment Secrets

This folder contains the cross-platform SOPS + age helpers for encrypting the root `.env` file and the local/production Docker environment files.

For local testing without production credentials, copy the committed template first:

```bash
cp .env.example .env
```

```powershell
Copy-Item .env.example .env
```

The template uses Django's console email backend, so test emails are printed in the terminal. Add real integration values only to your local, ignored `.env` file.

For local Docker testing, create the Docker-specific Django environment file:

```bash
cp .envs/.local/.django.example .envs/.local/.django
cp .envs/.local/.postgres.example .envs/.local/.postgres
```

```powershell
Copy-Item .envs/.local/.django.example .envs/.local/.django
Copy-Item .envs/.local/.postgres.example .envs/.local/.postgres
```

For production, copy both templates to the deployment host and replace every `replace-with-*` value:

```bash
cp .envs/.production/.django.example .envs/.production/.django
cp .envs/.production/.postgres.example .envs/.production/.postgres
```

```powershell
Copy-Item .envs/.production/.django.example .envs/.production/.django
Copy-Item .envs/.production/.postgres.example .envs/.production/.postgres
```

Do not commit plaintext `.django` or `.postgres` files.

## Setup

### 1. Install age and SOPS

`age-keygen` is installed together with `age`. Install both tools before running the helper scripts.

Windows PowerShell with WinGet:

```powershell
winget install --id FiloSottile.age -e --source winget
winget install --id Mozilla.SOPS -e --source winget
```

Close and reopen PowerShell after installation, then verify:

```powershell
age --version
age-keygen --version
sops --version
```

Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install -y age
```

Install the SOPS binary from the official GitHub release. Replace `v3.10.2` with the current release when updating:

```bash
SOPS_VERSION=v3.10.2
curl -Lo /tmp/sops "https://github.com/getsops/sops/releases/download/${SOPS_VERSION}/sops-${SOPS_VERSION}.linux.amd64"
sudo install -m 0755 /tmp/sops /usr/local/bin/sops
rm /tmp/sops
```

For an ARM64 Linux host, use `sops-${SOPS_VERSION}.linux.arm64` instead. Verify:

```bash
age --version
age-keygen --version
sops --version
```

macOS with Homebrew:

```bash
brew install age sops
age --version
age-keygen --version
sops --version
```

### 2. Create an age key

Keep the private key outside this repository. Generate it once per developer or deployment host:

```bash
mkdir -p ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt
export SOPS_AGE_KEY_FILE="$HOME/.config/sops/age/keys.txt"
export SOPS_AGE_RECIPIENT="$(sed -n 's/^# public key: //p' "$SOPS_AGE_KEY_FILE")"
```

On Windows PowerShell:

```powershell
New-Item -ItemType Directory -Force "$HOME\.config\sops\age"
age-keygen -o "$HOME\.config\sops\age\keys.txt"
$env:SOPS_AGE_KEY_FILE = "$HOME\.config\sops\age\keys.txt"
$env:SOPS_AGE_RECIPIENT = (Select-String -Path $env:SOPS_AGE_KEY_FILE -Pattern '^# public key:' | ForEach-Object { $_.Line -replace '^# public key:\s*', '' })
```

Keep the private key file outside Git. The commands above read the real public recipient from the key file. Do not use the literal placeholder `age1...`. Share only the public recipient with maintainers who need to encrypt files. Every maintainer who decrypts must have their own private key included as a recipient when the file is encrypted.

## Encrypt

From any working directory:

```bash
./scripts/sops/sops-env.sh encrypt
```

```powershell
.\scripts\sops\sops-env.ps1 encrypt
```

The helper encrypts these five files:

- `.env`
- `.envs/.local/.django`
- `.envs/.local/.postgres`
- `.envs/.production/.django`
- `.envs/.production/.postgres`

Files that are already encrypted and unchanged since last encryption are skipped automatically. To force re-encrypt all files (e.g. after rotating the age recipient):

```bash
./scripts/sops/sops-env.sh encrypt --force
```

```powershell
.\scripts\sops\sops-env.ps1 encrypt -force
```

Commit only the generated `.env.enc` and `.envs/**/*.enc` files. Plaintext `.env` and `.envs` files are ignored.

## Decrypt

After cloning or pulling:

```bash
./scripts/sops/sops-env.sh decrypt
```

```powershell
.\scripts\sops\sops-env.ps1 decrypt
```

For fast decryption, pass the private key value directly. The key starts with `AGE-SECRET-KEY-`:

```powershell
.\scripts\sops\sops-env.ps1 decrypt -Key "AGE-SECRET-KEY-..."
```

Linux/macOS:

```bash
./scripts/sops/sops-env.sh decrypt 'AGE-SECRET-KEY-...'
```

The direct-key form can expose the private key in shell history or process information. Prefer the safer key-file form for regular use:

```powershell
.\scripts\sops\sops-env.ps1 decrypt -KeyFile "$HOME\.config\sops\age\keys.txt"
```

```bash
export SOPS_AGE_KEY_FILE="$HOME/.config/sops/age/keys.txt"
./scripts/sops/sops-env.sh decrypt
```

The decrypted files are consumed by Django and Docker Compose. Do not commit them or the age private key.
