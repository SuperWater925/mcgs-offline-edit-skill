$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'scripts/stu_project.ps1') @args
if(-not $?){exit 1}
exit 0
