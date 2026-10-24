param(
 [Parameter(Mandatory)][string]$输入快照,
 [Parameter(Mandatory)][string]$事务清单,
 [Parameter(Mandatory)][string]$预期清单哈希,
 [Parameter(Mandatory)][string]$输出工程,
 [Parameter(Mandatory)][string]$报告路径,
 [string]$保护文件='',
 [switch]$Commit
)
# 新增窗口受限事务：在 run.ps1 apply 的更新白名单之外，只多允许“新增 WndUser 行”（六列齐全、窗口号和窗口名都不重复）。
# 不删行、不改旧行标量。只写到一个新文件；事务内与提交后都做全表比对。不带 -Commit 时只做预检，不复制、不写。
# 清单由 tools/mcgs_ui.py 的 Candidate 生成：update 与 run.ps1 apply 同格式；insert 为
#   {action:'insert', table:'WndUser', key_column:'iID', key:N, values:{iID:N, strName, strNote, lbObjects:{blob,sha256}, iDeleteFlag:0, iCompileFlag:0}}
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if($PSVersionTable.PSVersion.Major -lt 7){throw '必须使用 PowerShell 7。'}
$技能脚本=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\scripts\stu_project.ps1'))
$Provider='auto';$script:SelectedProvider=$null
$script:RawTables=@('Alarm','Data','DDEConnection','DDEConnectionPoint','Stgy','System','Trigger','WndControl','WndDevice','WndUser')
$令牌=$null;$语法错误=$null
$语法树=[Management.Automation.Language.Parser]::ParseFile($技能脚本,[ref]$令牌,[ref]$语法错误)
foreach($函数名 in @('FullPath','Sha','SharedHash','ValueFingerprint','SensitiveTable','SafeSystemRow','SafeKey','Connection','ReadDatabase','Capture','StableCopy','CompareMaps','ManifestBlob')){
 $节点=@($语法树.FindAll({param($项) $项 -is [Management.Automation.Language.FunctionDefinitionAst]},$true)|Where-Object Name -eq $函数名)
 if($节点.Count -ne 1){throw "技能函数定位不唯一：$函数名"}
 . ([scriptblock]::Create($节点[0].Extent.Text))
}
$键列=@{System='strName';Stgy='iStgyID';Trigger='iID';WndUser='iID';WndControl='iID'}
$可写字段=@{System=@('lbContext');Stgy=@('lbObjects');Trigger=@('lbContext');WndUser=@('lbObjects');WndControl=@('lbObjects')}
$新增列=@('iID','strName','strNote','lbObjects','iDeleteFlag','iCompileFlag')
$输入快照=FullPath $输入快照;$事务清单=FullPath $事务清单;$输出工程=FullPath $输出工程;$报告路径=FullPath $报告路径
if([IO.Path]::GetExtension($输入快照) -ine '.MCS' -or [IO.Path]::GetExtension($输出工程) -ine '.MCS'){throw '输入和输出都必须是 McgsStu .MCS。'}
if($输出工程 -ieq $输入快照){throw '输出必须是新文件，不能就地改。'}
if((Test-Path -LiteralPath $输出工程) -or (Test-Path -LiteralPath $报告路径)){throw '输出或报告已存在，禁止覆盖。'}
if((SharedHash $事务清单) -cne $预期清单哈希.ToLowerInvariant()){throw '事务清单哈希不符。'}
$保护=@($保护文件 -split ';' | Where-Object {$_} | ForEach-Object {FullPath $_})
$保护前=@{};foreach($f in $保护){$保护前[$f]=SharedHash $f}
$清单=Get-Content -LiteralPath $事务清单 -Raw -Encoding utf8|ConvertFrom-Json -AsHashtable
$清单目录=[IO.Path]::GetDirectoryName($事务清单)
$基线=Capture $输入快照
if($基线.sha256 -cne ([string]$清单.input_sha256).ToLowerInvariant()){throw '输入快照与清单基线不符。底稿变了就重新导出、重新生成清单，不要放宽校验。'}
$前=$基线.fingerprints
if(-not $清单.Contains('operations') -or $清单.operations.Count -eq 0){throw '清单没有操作。'}
$已有窗口名=@{};foreach($k in $前.WndUser.Keys){$已有窗口名[$前.WndUser[$k].strName]=$k}
$允许=@{};$期望=@{};$新增=@{};$新增名=@{};$准备=[Collections.Generic.List[object]]::new()
foreach($op in $清单.operations){
 $表=[string]$op.table;$键=[string]$op.key
 if(-not $键列.ContainsKey($表) -or $op.key_column -cne $键列[$表]){throw "表或键列不在白名单：$表/$键"}
 if($op.action -eq 'update'){
  if(-not $前[$表].Contains($键)){throw "更新原行不存在：$表/$键"}
  if($表 -eq 'System' -and $键 -notmatch '^(ObjData|ObjPointerRule|StgyAndTrigger|MCGS_RECIPE_.+)$'){throw "System 行不在白名单：$键"}
  if($表 -eq 'Stgy' -and $键 -ne '0'){throw '只支持 Stgy 第 0 行策略容器。'}
  if($op.values.Count -ne 1 -or $op.before.Count -ne 1){throw "每条更新只写一个字段并带一个前指纹：$表/$键"}
  $f=@($op.values.Keys)[0]
  if($f -notin $可写字段[$表] -or -not $op.before.Contains($f)){throw "字段不在白名单：$表/$键/$f"}
  if($op.before[$f] -cne $前[$表][$键][$f]){throw "更新前指纹不符：$表/$键/$f"}
  $id="$表/$键/$f";if($允许.ContainsKey($id)){throw "重复写同一字段：$id"}
  $raw=ManifestBlob $op.values[$f] $清单目录
  $允许[$id]=$true;$期望[$id]=@{table=$表;key=$键;field=$f;fingerprint=(ValueFingerprint $raw)}
  $准备.Add(@{action='update';table=$表;key_column=$op.key_column;key=$键;field=$f;raw=$raw})
 }elseif($op.action -eq 'insert'){
  if($表 -ne 'WndUser'){throw "只允许新增 WndUser 行：$表/$键"}
  if($前.WndUser.Contains($键) -or $新增.Contains($键)){throw "窗口号已存在：$键"}
  if((@($op.values.Keys|Sort-Object) -join ',') -cne (@($新增列|Sort-Object) -join ',')){throw "新增列不齐：$键"}
  if([int]$op.values.iID -ne [int]$键 -or [int]$op.values.iDeleteFlag -ne 0 -or [int]$op.values.iCompileFlag -ne 0){throw "新增行 ID/flag 不符：$键"}
  $名=[string]$op.values.strName
  if([string]::IsNullOrWhiteSpace($名)){throw "新增窗口没有名称：$键"}
  $名指纹=ValueFingerprint $名
  if($已有窗口名.ContainsKey($名指纹) -or $新增名.ContainsKey($名指纹)){throw "窗口名已存在：$名"}
  $新增名[$名指纹]=$true
  $值=[ordered]@{iID=[int]$op.values.iID;strName=$名;strNote=[string]$op.values.strNote;
   lbObjects=(ManifestBlob $op.values.lbObjects $清单目录);iDeleteFlag=[int]0;iCompileFlag=[int]0}
  $新增[$键]=[ordered]@{};foreach($列 in $新增列){$新增[$键][$列]=ValueFingerprint $值[$列]}
  $准备.Add(@{action='insert';table=$表;key=$键;values=$值})
 }else{throw '只接受 update/insert。'}
}
if($允许.ContainsKey('Stgy/0/lbObjects') -ne $允许.ContainsKey('System/StgyAndTrigger/lbContext')){throw '两份策略容器必须在同一事务里一起改。'}
function 核对($后){
 $变化=CompareMaps $前 $后
 foreach($d in $变化){
  if($d.action -eq 'field_changed' -and $允许.ContainsKey("$($d.table)/$($d.key)/$($d.field)")){continue}
  if($d.action -eq 'row_changed' -and $d.table -eq 'WndUser' -and $新增.Contains([string]$d.key) -and -not $前.WndUser.Contains([string]$d.key)){continue}
  throw "出现未批准的变化：$($d.table)/$($d.key)/$(if($d.Contains('field')){$d.field})/$($d.action)"
 }
 foreach($id in $期望.Keys){$v=$期望[$id];if($后[$v.table][$v.key][$v.field] -cne $v.fingerprint){throw "写入值复读不符：$id"}}
 foreach($k in $新增.Keys){
  if(-not $后.WndUser.Contains($k)){throw "新增行未写入：WndUser/$k"}
  if((@($后.WndUser[$k].Keys|Sort-Object) -join ',') -cne (@($新增列|Sort-Object) -join ',')){throw "新增行列集不符：$k"}
  foreach($列 in $新增列){if($后.WndUser[$k][$列] -cne $新增[$k][$列]){throw "新增行复读不符：WndUser/$k/$列"}}
 }
 if($后.WndUser.Count -ne $前.WndUser.Count+$新增.Count){throw '窗口行数不符。'}
 return ,$变化
}
$结果=[ordered]@{input=$输入快照;input_sha256=$基线.sha256;output=$输出工程;manifest_sha256=$预期清单哈希.ToLowerInvariant();
 updated_fields=@($允许.Keys|Sort-Object);inserted_rows=@($新增.Keys|Sort-Object|ForEach-Object {"WndUser/$_"});preflight_passed=$true;committed=$false;
 gui=$false;vendor_code_executed=$false;native_compile_verified=$false}
if(-not $Commit){
 [IO.File]::WriteAllText($报告路径,($结果|ConvertTo-Json -Depth 20),[Text.UTF8Encoding]::new($false))
 $结果|ConvertTo-Json -Depth 5;exit 0
}
$复制=StableCopy $输入快照 $输出工程
if($复制.sha256 -cne $基线.sha256){throw '复制后的新文件不是底稿。'}
$连接=Connection $输出工程 'Share Exclusive';$事务=$null
try{
 if((CompareMaps $前 (ReadDatabase $连接).fingerprints).Count -ne 0){throw '新文件与底稿不一致。'}
 $事务=$连接.BeginTransaction()
 foreach($p in $准备){
  $命令=$连接.CreateCommand();$命令.Transaction=$事务
  try{
   if($p.action -eq 'update'){
    $命令.CommandText='UPDATE ['+$p.table+'] SET ['+$p.field+']=? WHERE ['+$p.key_column+']=?'
    $参数=$命令.Parameters.Add('value',[Data.OleDb.OleDbType]::LongVarBinary,$p.raw.Length);$参数.Value=$p.raw
    $键值=if($p.key_column -eq 'strName'){[string]$p.key}else{[int]$p.key}
    [void]$命令.Parameters.AddWithValue('rowkey',$键值)
   }else{
    $命令.CommandText='INSERT INTO [WndUser] (['+($新增列 -join '],[')+']) VALUES ('+(($新增列|ForEach-Object {'?'}) -join ',')+')'
    foreach($列 in $新增列){
     $v=$p.values[$列]
     if($v -is [byte[]]){$参数=$命令.Parameters.Add($列,[Data.OleDb.OleDbType]::LongVarBinary,$v.Length);$参数.Value=$v}
     elseif($v -is [int]){$参数=$命令.Parameters.Add($列,[Data.OleDb.OleDbType]::Integer);$参数.Value=$v}
     else{$参数=$命令.Parameters.Add($列,[Data.OleDb.OleDbType]::VarWChar,[Math]::Max(1,$v.Length));$参数.Value=$v}
    }
   }
   if($命令.ExecuteNonQuery() -ne 1){throw "操作未精确影响一行：$($p.table)/$($p.key)"}
  }finally{$命令.Dispose()}
 }
 [void](核对 (ReadDatabase $连接 $事务).fingerprints)
 $事务.Commit();$事务.Dispose();$事务=$null
}catch{if($事务){try{$事务.Rollback()}catch{}};throw}
finally{if($事务){$事务.Dispose()};$连接.Dispose()}
$复读=Capture $输出工程
$变化=核对 $复读.fingerprints
if((SharedHash $输入快照) -cne $基线.sha256){throw '输入快照发生变化。'}
foreach($f in $保护){if((SharedHash $f) -cne $保护前[$f]){throw "受保护文件发生变化：$f"}}
$结果.committed=$true;$结果['output_sha256']=$复读.sha256;$结果['windows_before']=$前.WndUser.Count;$结果['windows_after']=$复读.fingerprints.WndUser.Count
$结果['all_unlisted_rows_and_fields_exact']=$true;$结果['all_written_values_reread_equal']=$true;$结果['protected_files_unchanged']=$保护.Count;$结果['changes']=$变化
[IO.File]::WriteAllText($报告路径,($结果|ConvertTo-Json -Depth 20),[Text.UTF8Encoding]::new($false))
[pscustomobject]$结果|Select-Object output_sha256,updated_fields,inserted_rows,windows_before,windows_after,all_unlisted_rows_and_fields_exact,all_written_values_reread_equal,protected_files_unchanged|ConvertTo-Json
