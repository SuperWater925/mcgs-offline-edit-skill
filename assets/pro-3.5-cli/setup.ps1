$ErrorActionPreference = 'Stop'
$taskArgs = @()
if ($env:MCGS_PYTHON) {
    $taskExecutable = $env:MCGS_PYTHON
} else {
    $taskCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($taskCommand) { $taskExecutable = $taskCommand.Source } else {
        $taskExecutable = (Get-Command py -ErrorAction Stop).Source
        $taskArgs = @('-3')
    }
}
& $taskExecutable @taskArgs (Join-Path $PSScriptRoot 'scripts/mcgs_file.py') doctor --workdir $PSScriptRoot
if ($LASTEXITCODE -ne 0) { throw 'Environment check failed. Read the diagnostic output.' }
Write-Host 'Ready: direct MCP file creation/editing; no pip installation required.'
