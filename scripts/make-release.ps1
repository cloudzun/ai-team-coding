<#
 make-release.ps1 -DbSource <homestay.db path> [-Tag v1] [-Repo cloudzun/ai-team-coding] [-Publish]

 Local, DB-backed build, then (only with -Publish) upload the two assets to a GitHub Release.
 Without -Publish this script runs the build and gates, then only PRINTS the gh command. It never pushes code.
 Publishing needs the owner's explicit authorization and a logged-in gh (gh auth status).
#>
param(
  [Parameter(Mandatory = $true)][string]$DbSource,
  [string]$Tag = 'v1',
  [string]$Repo = 'cloudzun/ai-team-coding',
  [switch]$Publish
)
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

# 1 local build with the course DB (verified against content/kit/checksums.txt); writes release-manifest.json
npm run build -- --db-source $DbSource --tag $Tag
if ($LASTEXITCODE -ne 0) { throw 'build failed' }
python scripts/qa_pages.py local
if ($LASTEXITCODE -ne 0) { throw 'qa_pages failed' }
python scripts/scan_sensitive.py
if ($LASTEXITCODE -ne 0) { throw 'scan_sensitive failed' }

$materials = 'dist\downloads\ai-team-coding-materials.zip'
$offline = 'release\ai-team-coding-offline.zip'
$man = Get-Content release-manifest.json -Raw -Encoding UTF8 | ConvertFrom-Json
$notes = "课程材料总包（含课程库，解开后库在 v2/kit/db/homestay.db）与离线包（解压后双击 start.cmd）。`n" +
  "总包 SHA-256：$($man.materials.sha256)`n离线包 SHA-256：$($man.offline.sha256)`n" +
  "核对：Get-FileHash <文件> -Algorithm SHA256"

$cmd = "gh release create $Tag `"$materials`" `"$offline`" --repo $Repo --title `"课程材料 $Tag`" --notes `"<notes>`""
Write-Host ''
Write-Host 'Release command (review before running):'
Write-Host "  $cmd"
Write-Host 'Reminder: commit release-manifest.json (it changed if the content changed) BEFORE pushing main, so CI sees the same numbers.'

if ($Publish) {
  gh release create $Tag $materials $offline --repo $Repo --title "课程材料 $Tag" --notes $notes
} else {
  Write-Host '(dry: add -Publish to actually create the Release)'
}