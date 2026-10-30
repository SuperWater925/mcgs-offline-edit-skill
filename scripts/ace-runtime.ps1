# Shared Windows PowerShell 7 / ACE runtime for McgsStu and McgsPro.
if($PSVersionTable.PSVersion.Major -lt 7){throw 'PowerShell 7 or newer is required for MCGS.'}
if(-not $IsWindows){throw 'The MCGS ACE runtime requires Windows.'}
function Get-McgsAceProviders {
 $items=[Collections.Generic.List[string]]::new()
 $reader=[Data.OleDb.OleDbEnumerator]::GetRootEnumerator()
 try{while($reader.Read()){if([string]$reader['SOURCES_NAME'] -match '^Microsoft\.ACE\.OLEDB\.(12|16)\.0$'){$items.Add([string]$reader['SOURCES_NAME'])}}}finally{$reader.Dispose()}
 return ,@($items.ToArray())
}
function New-McgsAceConnectionString([string]$Path,[string]$Mode,[string]$Provider,[switch]$Create){
 $builder=[Data.OleDb.OleDbConnectionStringBuilder]::new()
 $builder['Provider']=$Provider;$builder['Data Source']=$Path
 if(-not $Create){$builder['Persist Security Info']=$false}
 if($Mode){$builder['Mode']=$Mode}
 if($Create){$builder['Jet OLEDB:Engine Type']=5}
 return $builder.ConnectionString
}
function Open-McgsAceConnection([string]$Path,[string]$Mode='Read',[string]$Provider='auto'){
 $candidates=if($Provider -eq 'auto'){@('Microsoft.ACE.OLEDB.16.0','Microsoft.ACE.OLEDB.12.0')}else{@($Provider)}
 foreach($candidate in $candidates){
  $connection=[Data.OleDb.OleDbConnection]::new((New-McgsAceConnectionString $Path $Mode $candidate))
  try{$connection.Open();return ,$connection}catch{$connection.Dispose()}
 }
 throw 'ACE could not open the project. Check provider/process bitness, database format, locks and path; no editor process was closed.'
}
