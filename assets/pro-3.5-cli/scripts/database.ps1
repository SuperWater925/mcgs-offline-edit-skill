$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
. (Join-Path $PSScriptRoot '../../../scripts/ace-runtime.ps1')
$script:DbProvider=@('Microsoft.ACE.OLEDB.16.0','Microsoft.ACE.OLEDB.12.0') | Where-Object {$_ -in (Get-McgsAceProviders)} | Select-Object -First 1
if(-not $script:DbProvider){throw 'Matching-bitness ACE 16.0 or 12.0 required'}
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$request=[Console]::In.ReadToEnd() | ConvertFrom-Json
function Identifier($name) {
    if($name -notmatch '^[A-Za-z][A-Za-z0-9_]*$') { throw 'Unsupported identifier' }
    return '['+$name+']'
}
function Connection-String($path,$readOnly) {
    return New-McgsAceConnectionString $path $(if($readOnly){'Read'}else{''}) $script:DbProvider -Create:(-not $readOnly)
}
function Open-Database($path,$readOnly) {
    $mode=if($readOnly){'Read'}else{'Share Exclusive'}
    $c=Open-McgsAceConnection $path $mode
    $script:DbProvider=$c.Provider
    return ,$c
}
function Dump-Database($connection) {
    $result=[ordered]@{}
    $tables=$connection.GetSchema('Tables')
    $allIndexes=$connection.GetSchema('Indexes')
    foreach($entry in ($tables.Rows | Where-Object TABLE_TYPE -eq 'TABLE' | Sort-Object TABLE_NAME)) {
        $name=[string]$entry.TABLE_NAME
        $cmd=$connection.CreateCommand();$cmd.CommandText='SELECT * FROM '+(Identifier $name)
        $reader=$cmd.ExecuteReader([Data.CommandBehavior]::KeyInfo);$schema=$reader.GetSchemaTable();$fields=@()
        foreach($column in $schema.Rows) {$fields+=@{name=[string]$column.ColumnName;type=[int]$column.ProviderType;size=[int]$column.ColumnSize;auto_increment=[bool]$column.IsAutoIncrement}}
        $rows=@()
        while($reader.Read()) {
            $row=[ordered]@{}
            for($i=0;$i -lt $reader.FieldCount;$i++) {
                $v=$reader.GetValue($i)
                if($v -is [DBNull]) {$v=$null}
                elseif($v -is [byte[]]) {$v=@{binary=[Convert]::ToBase64String($v)}}
                $row[$reader.GetName($i)]=$v
            }
            $rows+=,$row
        }
        $reader.Close();$cmd.Dispose();$indexes=@()
        foreach($group in @($allIndexes.Rows | Where-Object TABLE_NAME -eq $name | Group-Object INDEX_NAME | Sort-Object Name)) {
            $parts=@($group.Group | Sort-Object ORDINAL_POSITION)
            $indexes+=@{name=[string]$group.Name;primary=[bool]$parts[0].PRIMARY_KEY;unique=[bool]$parts[0].UNIQUE;columns=@($parts | ForEach-Object {[string]$_.COLUMN_NAME})}
        }
        $result[$name]=@{fields=$fields;rows=$rows;indexes=$indexes}
    }
    return $result
}
function Add-Value($cmd,$field,$value) {
    if($null -eq $value) {$v=[DBNull]::Value;$size=1}
    elseif($field.type -eq 205) {$v=[Convert]::FromBase64String($value.binary);$size=[Math]::Max(1,$v.Length)}
    elseif($field.type -eq 202 -or $field.type -eq 203) {$v=[string]$value;$size=[Math]::Max(1,$v.Length)}
    elseif($field.type -eq 11) {$v=[bool]$value;$size=1}
    elseif($field.type -eq 4) {$v=[single]$value;$size=4}
    elseif($field.type -eq 3) {$v=[int]$value;$size=4}
    else {throw ('Unsupported field type '+$field.type)}
    $parameter=$cmd.Parameters.Add('p'+$cmd.Parameters.Count,[Data.OleDb.OleDbType][int]$field.type,$size)
    $parameter.Value=$v
}
function Insert-Row($c,$table,$fields,$row,$transaction) {
    $cmd=$c.CreateCommand();$cmd.Transaction=$transaction;$names=@();$marks=@()
    foreach($field in $fields) {$names+=Identifier $field.name;$marks+='?';Add-Value $cmd $field $row.($field.name)}
    $cmd.CommandText='INSERT INTO '+(Identifier $table)+' ('+($names -join ',')+') VALUES ('+($marks -join ',')+')'
    if($cmd.ExecuteNonQuery() -ne 1) {throw 'Insert must affect exactly one row'}
    $cmd.Dispose()
}
if($request.action -eq 'doctor') {
    $cat=New-Object -ComObject ADOX.Catalog
    $c=New-Object Data.OleDb.OleDbConnection
    @{ado_available=$true;process_bits=([IntPtr]::Size*8);powershell=$PSVersionTable.PSVersion.ToString();provider=$script:DbProvider} | ConvertTo-Json -Compress
    exit 0
}
if($request.action -eq 'create') {
    if(Test-Path -LiteralPath $request.path) {throw 'Output already exists'}
    $cat=New-Object -ComObject ADOX.Catalog
    $cat.Create((Connection-String $request.path $false)) | Out-Null
    $cat.ActiveConnection.Close()
    $c=Open-Database $request.path $false
    try {
        foreach($table in $request.seed.PSObject.Properties) {
            $columns=@()
            foreach($field in $table.Value.fields) {
                switch([int]$field.type) {
                    3 {$type='LONG'}
                    4 {$type='SINGLE'}
                    11 {$type='YESNO'}
                    202 {$type='TEXT('+[Math]::Min(255,[int]$field.size)+')'}
                    203 {$type='MEMO'}
                    205 {$type='LONGBINARY'}
                    default {throw 'Unsupported schema type'}
                }
                if($field.auto_increment) {
                    if([int]$field.type -ne 3){throw 'Auto increment requires native integer identity'}
                    $type='COUNTER'
                }
                $columns+=(Identifier $field.name)+' '+$type
            }
            $cmd=$c.CreateCommand();$cmd.CommandText='CREATE TABLE '+(Identifier $table.Name)+' ('+($columns -join ',')+')'
            $cmd.ExecuteNonQuery() | Out-Null;$cmd.Dispose()
            foreach($index in @($table.Value.indexes)) {
                if($null -eq $index){continue}
                if(-not @($index.columns).Count){throw 'Index columns required'}
                foreach($column in $index.columns){if($column -notin @($table.Value.fields.name)){throw 'Unknown index column'}}
                $kind=if($index.unique -or $index.primary){'UNIQUE '}else{''}
                $sql='CREATE '+$kind+'INDEX '+(Identifier $index.name)+' ON '+(Identifier $table.Name)+' ('+((@($index.columns | ForEach-Object {Identifier $_})) -join ',')+')'
                if($index.primary){$sql+=' WITH PRIMARY'}
                $cmd=$c.CreateCommand();$cmd.CommandText=$sql;$cmd.ExecuteNonQuery() | Out-Null;$cmd.Dispose()
            }
        }
        $transaction=$c.BeginTransaction()
        try {
            foreach($table in $request.seed.PSObject.Properties) {
                foreach($row in $table.Value.rows) {Insert-Row $c $table.Name $table.Value.fields $row $transaction}
            }
            $transaction.Commit()
        } catch {$transaction.Rollback();throw}
    } finally {$c.Close()}
    @{status='created'} | ConvertTo-Json -Compress
    exit 0
}
if($request.action -notin @('read','write')) {throw 'Unsupported database action'}
$c=Open-Database $request.path ($request.action -eq 'read')
try {
    if($request.action -eq 'read') {Dump-Database $c | ConvertTo-Json -Depth 40 -Compress}
    else {
        $before=Dump-Database $c;$transaction=$c.BeginTransaction()
        try {
            foreach($change in $request.changes) {
                $table=[string]$change.table
                if(!$before.Contains($table)) {throw 'Unknown table'}
                $fields=@($before[$table].fields)
                if($change.action -ne 'update') {throw 'Only exact updates are supported'}
                $cmd=$c.CreateCommand();$cmd.Transaction=$transaction;$set=@()
                foreach($prop in $change.values.PSObject.Properties) {
                    $field=@($fields | Where-Object name -eq $prop.Name)
                    if($field.Count -ne 1) {throw 'Unknown value field'}
                    $set+=(Identifier $prop.Name)+'=?';Add-Value $cmd $field[0] $prop.Value
                }
                if($set.Count -eq 0) {throw 'Empty change'}
                $key=@($fields | Where-Object name -eq $change.key)
                if($key.Count -ne 1 -or $key[0].type -ne 3) {throw 'Integer identity required'}
                Add-Value $cmd $key[0] $change.id
                $cmd.CommandText='UPDATE '+(Identifier $table)+' SET '+($set -join ',')+' WHERE '+(Identifier $change.key)+'=?'
                if($cmd.ExecuteNonQuery() -ne 1) {throw 'Update must affect exactly one row'}
                $cmd.Dispose()
            }
            $transaction.Commit()
        } catch {$transaction.Rollback();throw}
        @{status='written'} | ConvertTo-Json -Compress
    }
} finally {$c.Close()}
