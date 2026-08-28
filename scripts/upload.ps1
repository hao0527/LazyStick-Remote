<#
.SYNOPSIS
Commits and uploads the LazyStick remote-control site.

.EXAMPLE
.\scripts\upload.ps1 -Message "Update remote control page"

.EXAMPLE
.\scripts\upload.ps1 -Remote origin -Branch main -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateNotNullOrEmpty()]
    [string]$Message = "Update remote control page",

    [ValidateNotNullOrEmpty()]
    [string]$Remote = "origin",

    [string]$Branch
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))

function Invoke-CheckedGit {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$GitArguments
    )

    & git @GitArguments
    if ($LASTEXITCODE -ne 0) {
        throw "git $($GitArguments -join ' ') failed with exit code $LASTEXITCODE."
    }
}

try {
    if ($null -eq (Get-Command git.exe -ErrorAction SilentlyContinue)) {
        throw "Git is not installed or is unavailable in PATH."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot ".git") -PathType Container)) {
        throw "Not a Git repository: $projectRoot"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot "index.html") -PathType Leaf)) {
        throw "Remote-control page was not found: index.html"
    }

    Push-Location -LiteralPath $projectRoot
    try {
        $currentBranch = (& git branch --show-current).Trim()
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($currentBranch)) {
            throw "The repository is in detached HEAD state. Check out a branch before uploading."
        }
        if ([string]::IsNullOrWhiteSpace($Branch)) {
            $Branch = $currentBranch
        }

        & git remote get-url $Remote *> $null
        if ($LASTEXITCODE -ne 0) {
            throw "Git remote does not exist: $Remote"
        }

        $conflicts = @(& git diff --name-only --diff-filter=U)
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to inspect Git conflicts."
        }
        if ($conflicts.Count -gt 0) {
            throw "Resolve merge conflicts before uploading: $($conflicts -join ', ')"
        }

        Invoke-CheckedGit -GitArguments @("diff", "--check")
        $target = "$Remote/$Branch"
        if (-not $PSCmdlet.ShouldProcess($target, "Commit repository changes and push the site")) {
            return
        }

        Invoke-CheckedGit -GitArguments @("add", "--all", "--", ".")
        Invoke-CheckedGit -GitArguments @("diff", "--cached", "--check")

        & git diff --cached --quiet
        $stagedExitCode = $LASTEXITCODE
        if ($stagedExitCode -eq 1) {
            Invoke-CheckedGit -GitArguments @("commit", "-m", $Message)
        }
        elseif ($stagedExitCode -ne 0) {
            throw "Unable to inspect staged changes."
        }
        else {
            Write-Host "[LazyStick-Remote] No new changes to commit."
        }

        Write-Host "[LazyStick-Remote] Uploading $currentBranch to $target"
        Invoke-CheckedGit -GitArguments @("push", $Remote, "HEAD:$Branch")
        Write-Host "[LazyStick-Remote] Upload complete."
    }
    finally {
        Pop-Location
    }
}
catch {
    Write-Error $_
    exit 1
}
