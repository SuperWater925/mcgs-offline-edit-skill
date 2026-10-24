param(
 [Parameter(Mandatory,Position=0)][ValidateSet('doctor','inspect','snapshot','fingerprints','compare','apply')][string]$Command,
 [string]$Project, [string]$Out, [string]$Left, [string]$Right, [string]$Manifest,
 [string]$RecipeRoot, [string]$Report, [string]$Backup,
 [ValidateSet('auto','Microsoft.ACE.OLEDB.16.0','Microsoft.ACE.OLEDB.12.0')][string]$Provider='auto',
 [switch]$Commit, [switch]$InPlace
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if($PSVersionTable.PSVersion.Major -lt 7){throw 'PowerShell 7 or newer is required; Windows PowerShell 5.1 is the separate Pro CLI route.'}
if(-not $IsWindows){throw 'The McgsStu ACE database route requires Windows.'}
$script:SelectedProvider=$null
$script:RawTables=@('Alarm','Data','DDEConnection','DDEConnectionPoint','Stgy','System','Trigger','WndControl','WndDevice','WndUser')
$script:KeyColumns=@{System='strName';Stgy='iStgyID';Trigger='iID';WndUser='iID';WndControl='iID'}
$script:WriteFields=@{System=@('lbContext');Stgy=@('lbObjects');Trigger=@('lbContext');WndUser=@('lbObjects');WndControl=@('lbObjects')}

function FullPath([string]$Path){return [IO.Path]::GetFullPath($Path)}
function Need([string]$Value,[string]$Name){if([string]::IsNullOrWhiteSpace($Value)){throw "Missing -$Name"}}
function Sha([byte[]]$Bytes){return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($Bytes)).ToLowerInvariant()}
function SharedHash([string]$Path){
 $s=[IO.File]::Open($Path,'Open','Read',([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
 try{return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($s)).ToLowerInvariant()}finally{$s.Dispose()}
}
function ValueFingerprint($Value){
 if($null -eq $Value -or $Value -is [DBNull]){return 'null'}
 if($Value -is [byte[]]){return 'binary:'+$Value.Length+':'+(Sha $Value)}
 $v=$Value.GetType().FullName+':'+[Convert]::ToString($Value,[Globalization.CultureInfo]::InvariantCulture)
 return Sha ([Text.Encoding]::UTF8.GetBytes($v))
}
function SensitiveTable([string]$Table){return $Table -notin $script:RawTables}
function SafeSystemRow([string]$Key){
 # Account, connection and access-control objects remain fingerprint-only.
 # MCGSLINGUIST is the UI multi-language string table; the offline preview needs it to resolve caption tokens.
 return $Key -match '^(ObjData|ObjPointerRule|StgyAndTrigger|MCGS_RECIPE_.+|MCGSVER|MCGSTPCSize|ProWndBGColor|MCGS_PICTURE_.+|VARCOLLECTTABLE|VARCOLLECTTABLEWND|MCGSLINGUIST)$'
}
function SafeKey([string]$Table,[string]$Key){
 if(SensitiveTable $Table){return 'rowkey_sha256:'+(Sha ([Text.Encoding]::UTF8.GetBytes($Key)))}
 return $Key
}
function WriteJson([string]$Path,$Data){
 $p=FullPath $Path
 if(Test-Path -LiteralPath $p){throw "Refusing to overwrite report: $p"}
 $parent=[IO.Path]::GetDirectoryName($p)
 if(-not (Test-Path -LiteralPath $parent -PathType Container)){[void][IO.Directory]::CreateDirectory($parent)}
 [IO.File]::WriteAllText($p,($Data|ConvertTo-Json -Depth 45),[Text.UTF8Encoding]::new($false))
}
function Connection([string]$Path,[string]$Mode='Read'){
 $providers=if($script:SelectedProvider){@($script:SelectedProvider)}elseif($Provider -eq 'auto'){@('Microsoft.ACE.OLEDB.16.0','Microsoft.ACE.OLEDB.12.0')}else{@($Provider)}
 foreach($p in $providers){
  $b=[Data.OleDb.OleDbConnectionStringBuilder]::new();$b['Provider']=$p;$b['Data Source']=$Path;$b['Mode']=$Mode;$b['Persist Security Info']=$false
  $c=[Data.OleDb.OleDbConnection]::new($b.ConnectionString)
  try{$c.Open();$script:SelectedProvider=$p;return ,$c}catch{$c.Dispose()}
 }
 throw 'ACE could not open this project in the requested mode. Check provider/process bitness, database format, file locks and path; no editor process was closed.'
}
function ReadDatabase($Conn,$Transaction=$null,[string]$ExportDirectory=''){
 $tables=[ordered]@{};$schemas=[Collections.Generic.List[object]]::new();$exports=[Collections.Generic.List[object]]::new()
 foreach($table in @($Conn.GetSchema('Tables')|Where-Object TABLE_TYPE -eq 'TABLE'|Select-Object -ExpandProperty TABLE_NAME|Sort-Object)){
  if($table -notmatch '^[A-Za-z0-9_]+$'){throw 'Unexpected database table identifier; refusing to interpolate it.'}
  $cmd=$Conn.CreateCommand();$cmd.CommandText='SELECT * FROM ['+$table+']';if($Transaction){$cmd.Transaction=$Transaction}
  $reader=$cmd.ExecuteReader();$rows=@{};$count=0
  try{
   $columns=@(for($i=0;$i -lt $reader.FieldCount;$i++){[ordered]@{name=$reader.GetName($i);type=$reader.GetDataTypeName($i)}})
   while($reader.Read()){
    $count++;$rawKey=if($table -eq 'System'){[string]$reader['strName']}else{[string]$reader.GetValue(0)}
    $key=SafeKey $table $rawKey
    if($rows.ContainsKey($key)){throw "Duplicate row key in $table"}
    $fp=[ordered]@{};$export=[ordered]@{table=$table;row_key=$key}
    $rawAllowed=(-not (SensitiveTable $table)) -and ($table -ne 'System' -or (SafeSystemRow $rawKey))
    for($i=0;$i -lt $reader.FieldCount;$i++){
     $name=$reader.GetName($i);$v=$reader.GetValue($i);$fp[$name]=ValueFingerprint $v
     if($ExportDirectory -and $rawAllowed){
      if($v -is [DBNull]){$export[$name]=$null}
      elseif($v -is [byte[]]){
       $file=$table+'_'+(Sha ([Text.Encoding]::UTF8.GetBytes($rawKey))).Substring(0,16)+'_'+$name+'.bin'
       [IO.File]::WriteAllBytes((Join-Path $ExportDirectory $file),$v)
       $export[$name]=[ordered]@{file=$file;bytes=$v.Length;sha256=(Sha $v)}
      }else{$export[$name]=$v}
     }
    }
    $rows[$key]=$fp
    if($ExportDirectory -and $rawAllowed){$exports.Add($export)}
   }
   $schemas.Add([ordered]@{table=$table;rows=$count;columns=$columns;account_values_withheld=(SensitiveTable $table)})
  }finally{$reader.Dispose();$cmd.Dispose()}
  $tables[$table]=$rows
 }
 return [ordered]@{tables=@($schemas.ToArray());fingerprints=$tables;rows=@($exports.ToArray())}
}
function Capture([string]$Path,[string]$ExportDirectory=''){
 $before=SharedHash $Path;$conn=Connection $Path
 try{$data=ReadDatabase $conn $null $ExportDirectory}finally{$conn.Dispose()}
 if((SharedHash $Path) -ne $before){throw 'Project changed while reading. Re-snapshot and rebase instead of using this result.'}
 $data['input']=$Path;$data['sha256']=$before;$data['table_count']=$data.tables.Count
 $data['source_unchanged']=$true;$data['provider']=$script:SelectedProvider;$data['mode']='ACE Mode=Read'
 $data['all_field_values_fingerprinted']=$true;$data['account_values_withheld']=$true
 $data['native_compile_verified']=$false;$data['native_runtime_verified']=$false;$data['physically_tested']=$false
 return $data
}
function StableCopy([string]$Source,[string]$Destination){
 if(Test-Path -LiteralPath $Destination){throw "Destination already exists: $Destination"}
 $item=Get-Item -LiteralPath $Source;$size=$item.Length;$mtime=$item.LastWriteTimeUtc;$before=SharedHash $Source
 $parent=[IO.Path]::GetDirectoryName($Destination);[void][IO.Directory]::CreateDirectory($parent)
 $src=[IO.File]::Open($Source,'Open','Read',([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
 try{$dst=[IO.File]::Open($Destination,'CreateNew','Write',[IO.FileShare]::None);try{$src.CopyTo($dst)}finally{$dst.Dispose()}}finally{$src.Dispose()}
 $after=Get-Item -LiteralPath $Source;$copyHash=SharedHash $Destination
 if($before -ne $copyHash -or (SharedHash $Source) -ne $copyHash -or $size -ne $after.Length -or $mtime -ne $after.LastWriteTimeUtc){throw 'Source changed during shared copy; this candidate must not be used.'}
 return [ordered]@{source=$Source;output=$Destination;sha256=$copyHash;bytes=$size;stable_shared_copy=$true;source_written=$false}
}
function CompareMaps($A,$B){
 $changes=[Collections.Generic.List[object]]::new()
 foreach($t in @(@($A.Keys)+@($B.Keys)|Sort-Object -Unique)){
  if(-not $A.Contains($t) -or -not $B.Contains($t)){$changes.Add(@{table=$t;action='table_changed'});continue}
  foreach($k in @(@($A[$t].Keys)+@($B[$t].Keys)|Sort-Object -Unique)){
   if(-not $A[$t].Contains($k) -or -not $B[$t].Contains($k)){$changes.Add(@{table=$t;key=$k;action='row_changed'});continue}
   foreach($f in @(@($A[$t][$k].Keys)+@($B[$t][$k].Keys)|Sort-Object -Unique)){
    if(-not $A[$t][$k].Contains($f) -or -not $B[$t][$k].Contains($f) -or $A[$t][$k][$f] -ne $B[$t][$k][$f]){$changes.Add(@{table=$t;key=$k;field=$f;before=$A[$t][$k][$f];after=$B[$t][$k][$f];action='field_changed'})}
   }
  }
 }
 return ,@($changes.ToArray())
}
function ManifestBlob($Value,[string]$Directory){
 if($Value -isnot [Collections.IDictionary] -or -not $Value.Contains('blob') -or -not $Value.Contains('sha256')){throw 'Only blob + sha256 values are supported by this bounded updater.'}
 if([IO.Path]::IsPathRooted([string]$Value.blob)){throw 'Manifest BLOB paths must be relative.'}
 $p=FullPath ([IO.Path]::Combine($Directory,[string]$Value.blob))
 if(-not $p.StartsWith($Directory+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Manifest BLOB path escapes its directory.'}
 $raw=[IO.File]::ReadAllBytes($p)
 if([string]$Value.sha256 -notmatch '^[0-9a-fA-F]{64}$' -or (Sha $raw) -ne $Value.sha256.ToLowerInvariant()){throw 'Manifest BLOB SHA256 mismatch.'}
 return ,$raw
}
function CheckChanges($Before,$After,$Allowed,$Expected){
 $changes=CompareMaps $Before $After
 foreach($d in $changes){
  if($d.action -ne 'field_changed' -or -not $Allowed.ContainsKey($d.table+'/'+$d.key+'/'+$d.field)){throw 'Transaction changed an unlisted table, row or field.'}
 }
 foreach($id in $Expected.Keys){$v=$Expected[$id];if($After[$v.table][[string]$v.key][$v.field] -ne $v.fingerprint){throw 'A written BLOB did not read back exactly.'}}
 return ,$changes
}

try{
 if($Project -and $Command -ne 'compare' -and [IO.Path]::GetExtension($Project) -ine '.MCS'){throw 'This entry point handles McgsStu .MCS. Route McgsPro .mcp to assets/pro-3.5-cli with the matching version.'}
 if($Report -and (Test-Path -LiteralPath (FullPath $Report))){throw 'Report path already exists; choose a new report before starting.'}
 $result=$null
 switch($Command){
  'doctor'{
   $providers=[Collections.Generic.List[string]]::new()
   $r=[Data.OleDb.OleDbEnumerator]::GetRootEnumerator();try{while($r.Read()){if([string]$r['SOURCES_NAME'] -match '^Microsoft\.ACE\.OLEDB\.(12|16)\.0$'){$providers.Add([string]$r['SOURCES_NAME'])}}}finally{$r.Dispose()}
   $python=$null
   if($env:MCGS_PYTHON){$python=$env:MCGS_PYTHON}else{$p=Get-Command python -ErrorAction SilentlyContinue;if($p){$python=$p.Source}}
   $result=[ordered]@{powershell=$PSVersionTable.PSVersion.ToString();process_bits=([IntPtr]::Size*8);ace_providers=@($providers.ToArray());python=$python;source_written=$false;database_write_tested=$false}
   if($Project){$d=Capture (FullPath $Project);$result['project_sha256']=$d.sha256;$result['tables']=@($d.tables|ForEach-Object {@{table=$_.table;rows=$_.rows}});$result['project_read_passed']=$true}
  }
  'snapshot'{
   Need $Project 'Project';Need $Out 'Out';$src=FullPath $Project;$dest=FullPath $Out
   $copy=StableCopy $src $dest;$files=[Collections.Generic.List[object]]::new()
   if($RecipeRoot){
    $root=FullPath $RecipeRoot;$recipeDest=$dest+'.recipes'
    if(Test-Path -LiteralPath $recipeDest){throw 'Recipe snapshot directory already exists.'}
    [void][IO.Directory]::CreateDirectory($recipeDest)
    $namesBefore=@(Get-ChildItem -LiteralPath $root -File -Recurse|ForEach-Object {[IO.Path]::GetRelativePath($root,$_.FullName)}|Sort-Object)
    foreach($name in $namesBefore){$files.Add((StableCopy (Join-Path $root $name) (Join-Path $recipeDest $name)))}
    $namesAfter=@(Get-ChildItem -LiteralPath $root -File -Recurse|ForEach-Object {[IO.Path]::GetRelativePath($root,$_.FullName)}|Sort-Object)
    if(($namesBefore -join "`n") -cne ($namesAfter -join "`n")){throw 'Runtime recipe membership changed during the snapshot.'}
    foreach($file in $files){if((SharedHash $file.source) -ne $file.sha256){throw 'A runtime recipe changed during the snapshot.'}}
   }
   if((SharedHash $src) -ne $copy.sha256){throw 'Project changed during recipe snapshot.'}
   $result=[ordered]@{project=$copy;runtime_recipes=@($files.ToArray());runtime_count=$files.Count;time=(Get-Date).ToString('o');source_written=$false;cross_file_transaction_snapshot=$false}
   WriteJson ($dest+'.snapshot.json') $result
  }
  'inspect'{
   Need $Project 'Project';$directory=''
   if($Out){$directory=FullPath $Out;if(Test-Path -LiteralPath $directory){throw 'Inspect output directory must be new.'};[void][IO.Directory]::CreateDirectory($directory)}
   $data=Capture (FullPath $Project) $directory
   if($directory){$index=[ordered]@{};foreach($key in $data.Keys){if($key -ne 'fingerprints'){$index[$key]=$data[$key]}};WriteJson (Join-Path $directory 'index.json') $index;$fp=[ordered]@{};foreach($key in $data.Keys){if($key -ne 'rows'){$fp[$key]=$data[$key]}};WriteJson (Join-Path $directory 'fingerprints.json') $fp}
   $result=[ordered]@{input=$data.input;sha256=$data.sha256;tables=@($data.tables|ForEach-Object {@{table=$_.table;rows=$_.rows}});table_count=$data.table_count;safe_export_rows=$data.rows.Count;export_directory=$directory;source_unchanged=$true;account_values_withheld=$true;native_compile_verified=$false}
  }
  'fingerprints'{
   Need $Project 'Project';$data=Capture (FullPath $Project);$data.Remove('rows')
   if($Out){WriteJson $Out $data;$result=@{sha256=$data.sha256;tables=$data.table_count;fingerprints=(FullPath $Out);source_unchanged=$true}}else{$result=$data}
  }
  'compare'{
   Need $Left 'Left';Need $Right 'Right';$a=Get-Content -LiteralPath $Left -Raw -Encoding utf8|ConvertFrom-Json -AsHashtable;$b=Get-Content -LiteralPath $Right -Raw -Encoding utf8|ConvertFrom-Json -AsHashtable
   $delta=CompareMaps $a.fingerprints $b.fingerprints;$result=[ordered]@{left_sha256=$a.sha256;right_sha256=$b.sha256;equal=($delta.Count -eq 0);changes=$delta;count=$delta.Count;source_written=$false}
  }
  'apply'{
   Need $Project 'Project';Need $Manifest 'Manifest';$src=FullPath $Project;$manifestPath=FullPath $Manifest;$manifestDirectory=[IO.Path]::GetDirectoryName($manifestPath)
   if([IO.Path]::GetExtension($src) -ine '.MCS'){throw 'This updater accepts McgsStu .MCS only. Route Pro .mcp to pro-cli.'}
   $m=Get-Content -LiteralPath $manifestPath -Raw -Encoding utf8|ConvertFrom-Json -AsHashtable
   if(-not $m.Contains('input_sha256') -or $m.input_sha256 -notmatch '^[0-9a-fA-F]{64}$'){throw 'Manifest requires input_sha256.'}
   $base=Capture $src
   if($base.sha256 -ne $m.input_sha256.ToLowerInvariant()){throw 'Input SHA256 differs from the manifest baseline. Rebase; do not weaken the guard.'}
   if(-not $m.Contains('operations') -or $m.operations.Count -eq 0){throw 'Empty operation list.'}
   $allowed=@{};$expected=@{};$prepared=[Collections.Generic.List[object]]::new()
   foreach($op in $m.operations){
    if($op.action -ne 'update' -or -not $script:WriteFields.ContainsKey($op.table)){throw 'Only existing-row updates in the fixed table whitelist are implemented.'}
    if($op.key_column -ne $script:KeyColumns[$op.table]){throw 'Wrong table key column.'}
    $key=[string]$op.key
    if(-not $base.fingerprints[$op.table].Contains($key)){throw 'Manifest target row does not exist.'}
    if($op.table -eq 'System' -and $key -notmatch '^(ObjData|ObjPointerRule|StgyAndTrigger|MCGS_RECIPE_.+)$'){throw 'System row is outside the editing whitelist.'}
    if($op.table -eq 'Stgy' -and $key -ne '0'){throw 'Only the proven Stgy row 0 strategy-array container is supported.'}
    if($op.values.Count -eq 0 -or $op.before.Count -ne $op.values.Count){throw 'Every written field must have one before fingerprint.'}
    foreach($field in $op.values.Keys){
     if($field -notin $script:WriteFields[$op.table] -or -not $op.before.Contains($field) -or -not $base.fingerprints[$op.table][$key].Contains($field)){throw 'Field is outside the fixed whitelist.'}
     if($op.before[$field] -ne $base.fingerprints[$op.table][$key][$field]){throw 'Field before fingerprint mismatch.'}
     $id=$op.table+'/'+$key+'/'+$field;if($allowed.ContainsKey($id)){throw 'Duplicate field write.'}
     $raw=ManifestBlob $op.values[$field] $manifestDirectory;$allowed[$id]=$true
     $expected[$id]=@{table=$op.table;key=$key;field=$field;fingerprint=(ValueFingerprint $raw)}
     $prepared.Add(@{table=$op.table;key_column=$op.key_column;key=$op.key;field=$field;raw=$raw})
    }
   }
   $pairA=$allowed.ContainsKey('Stgy/0/lbObjects');$pairB=$allowed.ContainsKey('System/StgyAndTrigger/lbContext')
   if($pairA -ne $pairB){throw 'Strategy-source changes require both native strategy containers in one transaction.'}
   if($InPlace){Need $Backup 'Backup';if($Out){throw '-InPlace and -Out are mutually exclusive.'};$target=$src;$backupPath=FullPath $Backup;if($backupPath -ieq $src){throw 'Backup must be a separate new path.'}}
   else{Need $Out 'Out';$target=FullPath $Out;if($target -ieq $src -or (Test-Path -LiteralPath $target)){throw 'Copy output must be a new path. For authorized in-place work use -InPlace -Backup.'}}
   $result=[ordered]@{input=$src;input_sha256=$base.sha256;target=$target;manifest_sha256=(SharedHash $manifestPath);fields=$prepared.Count;preflight_passed=$true;committed=$false;in_place=[bool]$InPlace;source_written=$false;native_compile_verified=$false;native_runtime_verified=$false;physically_tested=$false}
   if($Commit){
    if($InPlace){$saved=StableCopy $src $backupPath;$result['backup']=$saved;if($saved.sha256 -ne $base.sha256){throw 'Backup is not the approved baseline.'}}
    else{$saved=StableCopy $src $target;if($saved.sha256 -ne $base.sha256){throw 'Copied baseline changed.'}}
    if((SharedHash $src) -ne $base.sha256){throw 'Input changed after preflight.'}
    $conn=Connection $target 'Share Exclusive';$tx=$null
    try{
     $locked=ReadDatabase $conn
     if((CompareMaps $base.fingerprints $locked.fingerprints).Count -ne 0){throw 'Database changed before exclusive transaction.'}
     $tx=$conn.BeginTransaction()
     foreach($p in $prepared){
      $cmd=$conn.CreateCommand();$cmd.Transaction=$tx;$cmd.CommandText='UPDATE ['+$p.table+'] SET ['+$p.field+']=? WHERE ['+$p.key_column+']=?'
      try{
       $param=$cmd.Parameters.Add('value',[Data.OleDb.OleDbType]::LongVarBinary,$p.raw.Length);$param.Value=$p.raw
       $keyValue=if($p.key_column -eq 'strName'){[string]$p.key}else{[int]$p.key};[void]$cmd.Parameters.AddWithValue('rowkey',$keyValue)
       if($cmd.ExecuteNonQuery() -ne 1){throw 'An update did not affect exactly one row.'}
      }finally{$cmd.Dispose()}
     }
     $inside=ReadDatabase $conn $tx;$delta=CheckChanges $base.fingerprints $inside.fingerprints $allowed $expected
     $tx.Commit();$tx.Dispose();$tx=$null
     $after=ReadDatabase $conn;$delta=CheckChanges $base.fingerprints $after.fingerprints $allowed $expected
    }catch{if($tx){try{$tx.Rollback()}catch{}};throw}finally{if($tx){$tx.Dispose()};$conn.Dispose()}
    if(-not $InPlace -and (SharedHash $src) -ne $base.sha256){throw 'Original source changed during copy build.'}
    $result['committed']=$true;$result['source_written']=[bool]$InPlace;$result['output_sha256']=SharedHash $target;$result['changes']=$delta
    $result['all_unlisted_fields_unchanged']=$true;$result['all_original_rows_preserved']=$true;$result['all_written_values_reread_equal']=$true
   }
  }
 }
 if($Report){WriteJson $Report $result}
 $result|ConvertTo-Json -Depth 45
}catch{
 [Console]::Error.WriteLine((@{ok=$false;command=$Command;error=$_.Exception.Message;committed_success_not_claimed=$true}|ConvertTo-Json -Compress));exit 1
}
