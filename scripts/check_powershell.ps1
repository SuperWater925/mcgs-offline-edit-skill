param([string]$Root = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$rootPath = (Resolve-Path -LiteralPath $Root).Path
$files = @(Get-ChildItem -LiteralPath $rootPath -File -Recurse -Filter '*.ps1' |
    Where-Object { $_.FullName -notmatch '[\\/](\.git|__pycache__|\.venv|local-artifacts)[\\/]' })
$failures = [Collections.Generic.List[string]]::new()
foreach ($file in $files) {
    $tokens = $null
    $parseErrors = $null
    [void][Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$parseErrors)
    foreach ($item in $parseErrors) {
        $failures.Add("$($file.Name):$($item.Extent.StartLineNumber): $($item.Message)")
    }
}
[pscustomobject]@{
    passed = ($failures.Count -eq 0)
    powershell_files = $files.Count
    errors = @($failures)
    scripts_executed = $false
    vendor_compile_verified = $false
} | ConvertTo-Json -Depth 4
if ($failures.Count -gt 0) { exit 1 }
