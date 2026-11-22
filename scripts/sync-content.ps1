<#
 sync-content.ps1 -Source <textbook v2 dir>
 Reads the textbook repo (READ ONLY) and mirrors whitelisted files into <repo>/content/.
 Blacklist wins over whitelist. Every whitelist line must match >= 1 file, or the sync fails.
 Writes SYNC.json (sha256 per file, source commit). Never writes outside <repo>/content and <repo>/SYNC.json.
#>
param(
  [Parameter(Mandatory = $true)][string]$Source,
  [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Src = (Resolve-Path -LiteralPath $Source).Path.TrimEnd('\')
$Dest = Join-Path $Repo 'content'
if (-not (Test-Path -LiteralPath (Join-Path $Src 'chapters'))) { throw "Source does not look like textbook v2 dir: $Src" }
if ($Dest.StartsWith($Src, [StringComparison]::OrdinalIgnoreCase)) { throw 'content/ is inside source; refuse.' }

function ConvertTo-GlobRegex([string]$g) {
  $sb = New-Object System.Text.StringBuilder
  $i = 0
  while ($i -lt $g.Length) {
    $c = $g[$i]
    if ($c -eq '*') {
      if (($i + 1 -lt $g.Length) -and ($g[$i + 1] -eq '*')) {
        if (($i + 2 -lt $g.Length) -and ($g[$i + 2] -eq '/')) { [void]$sb.Append('(?:.*/)?'); $i += 3; continue }
        [void]$sb.Append('.*'); $i += 2; continue
      }
      [void]$sb.Append('[^/]*'); $i++; continue
    }
    if ($c -eq '?') { [void]$sb.Append('[^/]'); $i++; continue }
    [void]$sb.Append([regex]::Escape([string]$c)); $i++
  }
  return '^' + $sb.ToString() + '$'
}
function Read-Patterns([string]$file) {
  Get-Content -LiteralPath $file -Encoding UTF8 | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' -and -not $_.StartsWith('#') }
}

$white = @(Read-Patterns (Join-Path $PSScriptRoot 'whitelist.txt') | ForEach-Object { [pscustomobject]@{ Pat = $_; Rx = (ConvertTo-GlobRegex $_); Hits = 0 } })
$blackRaw = @(Read-Patterns (Join-Path $PSScriptRoot 'blacklist.txt'))
$black = @(); $except = @()
foreach ($b in $blackRaw) {
  if ($b.StartsWith('!')) { $except += (ConvertTo-GlobRegex $b.Substring(1)); continue }
  if ($b.EndsWith('/')) { $black += [pscustomobject]@{ Kind = 'dir'; Rx = (ConvertTo-GlobRegex $b.TrimEnd('/')) } }
  elseif ($b.Contains('/')) { $black += [pscustomobject]@{ Kind = 'path'; Rx = (ConvertTo-GlobRegex $b) } }
  else { $black += [pscustomobject]@{ Kind = 'name'; Rx = (ConvertTo-GlobRegex $b) } }
}
function Test-Blacklisted([string]$rel) {
  $segs = $rel.Split('/')
  $hit = $false
  foreach ($b in $black) {
    switch ($b.Kind) {
      'dir' { for ($k = 0; $k -lt $segs.Length - 1; $k++) { if ($segs[$k] -match $b.Rx) { $hit = $true } } }
      'path' { if ($rel -match $b.Rx) { $hit = $true } }
      'name' { if ($segs[$segs.Length - 1] -match $b.Rx) { $hit = $true } }
    }
  }
  if ($hit) { foreach ($e in $except) { if ($rel -match $e) { return $false } } }
  return $hit
}

$all = Get-ChildItem -LiteralPath $Src -Recurse -File -Force
$picked = New-Object System.Collections.Generic.List[object]
$blocked = 0
foreach ($f in $all) {
  $rel = $f.FullName.Substring($Src.Length + 1).Replace('\', '/')
  if (Test-Blacklisted $rel) { $blocked++; continue }
  $ok = $false
  foreach ($w in $white) { if ($rel -match $w.Rx) { $w.Hits++; $ok = $true } }
  if ($ok) { $picked.Add([pscustomobject]@{ Rel = $rel; Full = $f.FullName }) }
}
$missing = @($white | Where-Object { $_.Hits -eq 0 })
if ($missing.Count -gt 0) { throw ('Whitelist entries matched no file: ' + (($missing | ForEach-Object { $_.Pat }) -join '; ')) }
Write-Host ("whitelist entries: {0}, files picked: {1}, blacklisted (skipped): {2}, other (not whitelisted): {3}" -f $white.Count, $picked.Count, $blocked, ($all.Count - $blocked - $picked.Count))
if ($DryRun) { $picked | ForEach-Object { $_.Rel }; return }

if (Test-Path -LiteralPath $Dest) {
  if ((Resolve-Path -LiteralPath $Dest).Path -ne (Join-Path $Repo 'content')) { throw 'unexpected content path' }
  Remove-Item -LiteralPath $Dest -Recurse -Force
}
New-Item -ItemType Directory -Path $Dest | Out-Null
$records = New-Object System.Collections.Generic.List[object]
foreach ($p in ($picked | Sort-Object Rel)) {
  $to = Join-Path $Dest ($p.Rel.Replace('/', '\'))
  $dir = Split-Path -Parent $to
  if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
  Copy-Item -LiteralPath $p.Full -Destination $to
  $h = (Get-FileHash -LiteralPath $to -Algorithm SHA256).Hash.ToLower()
  $records.Add([ordered]@{ path = $p.Rel; sha256 = $h; bytes = (Get-Item -LiteralPath $to).Length })
}

# source commit (read-only git calls; tolerated to fail)
$commit = $null; $dirty = $null
try {
  $commit = (& git -C $Src rev-parse HEAD 2>$null)
  if ($LASTEXITCODE -ne 0) { $commit = $null }
  if ($commit) { $dirty = ((& git -C $Src status --porcelain -- . 2>$null | Measure-Object).Count -gt 0) }
} catch { $commit = $null }

$srcName = (Split-Path -Leaf (Split-Path -Parent $Src)) + '/' + (Split-Path -Leaf $Src)
$meta = [ordered]@{
  synced_at     = (Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
  source        = $srcName
  source_commit = $commit
  source_dirty  = $dirty
  file_count    = $records.Count
  files         = $records
}
$json = $meta | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText((Join-Path $Repo 'SYNC.json'), $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Host ("synced {0} files -> content/ ; SYNC.json written (source commit: {1}, dirty: {2})" -f $records.Count, $commit, $dirty)
