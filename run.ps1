$ErrorActionPreference = 'Stop'
if($args.Count -gt 0 -and $args[0] -in @('audit','controls','strategy-source','recipe-cell','normalize-inputs')){
 $python=if($env:MCGS_PYTHON){$env:MCGS_PYTHON}else{(Get-Command python -ErrorAction Stop).Source}
 & $python -B -X utf8 (Join-Path $PSScriptRoot 'scripts/native_tool.py') @args
 exit $LASTEXITCODE
}
if($args.Count -gt 0 -and $args[0] -in @('create','edit','demo')){
 $python=if($env:MCGS_PYTHON){$env:MCGS_PYTHON}else{(Get-Command python -ErrorAction Stop).Source}
 $env:MCGS_PWSH=(Get-Process -Id $PID).Path
 & $python -B -X utf8 (Join-Path $PSScriptRoot 'assets/pro-3.5-cli/scripts/mcgs_file.py') @args
 exit $LASTEXITCODE
}
& (Join-Path $PSScriptRoot 'scripts/stu_project.ps1') @args
if(-not $?){exit 1}
exit 0
