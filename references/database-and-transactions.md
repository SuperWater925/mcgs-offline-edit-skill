# Stu数据库、共享快照与事务

## 结构

McgsStu MCS与McgsPro MCP使用原生Access/Jet数据库，以ACE只读/排他连接处理。已验证工程为12表：`Alarm`、`Data`、`DDEConnection`、`DDEConnectionPoint`、`SecurityGroup`、`SecurityUser`、`Stgy`、`System`、`Trigger`、`WndControl`、`WndDevice`、`WndUser`。其他项目应枚举实际表；未知表保持不动，仍纳入字段指纹。

`System`行键是`strName`，`Stgy`是`iStgyID`，`Trigger/WndUser/WndControl`是`iID`。只读全表指纹对所有字段使用类型+值哈希，二进制为`binary:长度:sha256`；账户表行键也哈希，不输出账号或口令值。

`inspect -Out`导出安全表及BLOB（含图片资源和多语言表MCGSLINGUIST，离线预览要用），敏感账户表和System权限/连接等记录仅在`fingerprints.json`中保留哈希。安全导出故意不等于完整数据库备份；完整原生工程快照保留原权限，应作为用户工程资料保管，不能嵌进通用技能包。

## 命令

在技能文件夹运行。参数中的盘符路径均是示例，请使用实际路径；每个输出必须是新路径。

```powershell
pwsh -NoProfile -File .\run.ps1 baseline -Project 'D:\工程\当前.MCS' -Out 'D:\验收\基线目录' -RecipeRoot 'C:\McgsStu\Program\data\recipe'
# 基线目录/project.MCS 是稳定快照；export/index.json 和 export/fingerprints.json 已完整生成
pwsh -NoProfile -File .\run.ps1 fingerprints -Project 'D:\其他时点\工程.MCS' -Out 'D:\验收\after.json'
pwsh -NoProfile -File .\run.ps1 compare -Left 'D:\验收\基线目录\export\fingerprints.json' -Right 'D:\验收\after.json'
& 'C:\本机Python\python.exe' -X utf8 .\scripts\native_tool.py audit --export 'D:\验收\基线目录\export'
```

`snapshot`使用`Open/Read/FileShare.ReadWrite|Delete`，校验复制前/后/副本SHA、大小和mtime。若附带配方根目录，逐文件保全并复核文件名集及最终哈希，产生`.snapshot.json`。这是稳定共享复制，跨工程与配方的原子事务快照并未保证；变化即报错，不能拿失败快照继续写。不要把正在被原厂改写的活文件当作固定基线。

### 现成策略源码补丁

从最新安全导出生成两个候选BLOB。策略名必须精确命中已有策略；多动作时用明确的 `--action-path '0,0,0'` 指定已有程序动作，详见[有界修改](bounded-edits.md)。源文件是UTF-8，保留其实际换行。此工具不是MCGS编译器。

```powershell
& 'C:\本机Python\python.exe' -X utf8 .\scripts\native_tool.py strategy-source --export 'D:\验收\基线' --strategy-name '<已有单脚本策略名>' --source 'D:\修改\源码.txt' --out 'D:\验收\候选'
pwsh -NoProfile -File .\run.ps1 apply -Project 'D:\验收\最新快照.MCS' -Manifest 'D:\验收\候选\manifest.json' -Out 'D:\验收\候选工程.MCS'
```

末条命令只有preflight，默认不复制/不改MCS。用户已授权落地时加`-Commit`。就地修改需要用户的任务授权，并提供独立新备份路径：

```powershell
pwsh -NoProfile -File .\run.ps1 apply -Project 'D:\工程\当前.MCS' -Manifest 'D:\验收\候选\manifest.json' -InPlace -Backup 'D:\验收\就地写入前.MCS' -Commit -Report 'D:\验收\事务报告.json'
```

用户此前已指定就地修改且授权仍有效时，直接按此流程备份写入，不为了本技能重复确认。未授权实际写入时只检查清单。

## 固定写入白名单

当前入口只支持`update`已有行；每条操作必须精确影响1行，不提供任意SQL、insert/delete或账户写入。

| 表 | 行范围 | 可写字段 |
| --- | --- | --- |
| System | ObjData、ObjPointerRule、StgyAndTrigger、MCGS_RECIPE_* | lbContext |
| Stgy | 已证实的iStgyID=0容器 | lbObjects |
| Trigger | 既有iID | lbContext |
| WndUser | 既有iID | lbObjects |
| WndControl | 既有iID | lbObjects |

`Stgy/0/lbObjects`与`System/StgyAndTrigger/lbContext`要求成对列入。调用者负责使用原生解析器证明两份策略语义同步；`native_tool.py strategy-source`已实现此证明。通用写入器校验SHA与字段范围，不声称能验证任意BLOB的业务语义。

新建窗口要新增WndUser行，本入口不支持，用`tools/新增窗口事务.ps1`：只多允许新增清单列出的WndUser行（六列`iID/strName/strNote/lbObjects/iDeleteFlag=0/iCompileFlag=0`），其余照本入口的白名单更新与全表比对，见[界面工具](ui-tools.md#tools新增窗口事务ps1)。
- 该脚本按函数名从`scripts/stu_project.ps1`抽取`FullPath/Sha/SharedHash/ValueFingerprint/SensitiveTable/SafeSystemRow/SafeKey/Connection/ReadDatabase/Capture/StableCopy/CompareMaps/ManifestBlob`。
- 新窗口工具也加载共用 `scripts/ace-runtime.ps1`；改这些函数的名称或参数会让它失效；要改时同步修改，或先把insert正式并入本入口并补隔离测试。

JSON清单格式：

```json
{
  "input_sha256": "64位当前工程SHA256",
  "operations": [{
    "action": "update", "table": "WndUser", "key_column": "iID", "key": 42,
    "before": {"lbObjects": "binary:旧长度:旧sha256"},
    "values": {"lbObjects": {"blob": "Wnd42.bin", "sha256": "64位新BLOB的SHA256"}}
  }]
}
```

BLOB路径必须相对清单目录且不越界；每个字段有前指纹；重复字段拒绝。基线SHA与字段指纹不匹配时重新取快照并重做补丁，不能删除校验。

实际写入先保全副本/备份，再取得ACE排他连接，复核完整逻辑基线，事务内写入和全表对比，通过后提交。关闭写连接后，用新只读连接完整回读并核对读取前后文件 SHA。只允许清单所列字段变化，其余表/原行/字段必须精确保留。`-ExportAfter <新目录>` 复用这次回读输出安全导出和完整指纹，无需再独立 `inspect`；只用于 `-Commit`。锁冲突、行数变化、字段越界、内容复读不符时报告失败；失败候选不作为成果。就地失败时保留备份，检查实际状态后再决定恢复，不自动覆盖用户可能已经保存的新内容。批量修改及耗时字段见[离线提速](offline-performance.md)。

## 原生BLOB封套

- `MCGSZIPE`为8字节标记+两份相同DWORD原文长度+标准zlib数据。随包解码器限已证`78 01`头并做长度、eof、尾部校验；未知封套拒绝。
- `Stgy`行0保存策略数组；`System/StgyAndTrigger`还保存策略/触发注册。两份必须同步，不可只改其一。
- 改某策略源码时只清该`CStgyFuncProg.compiled`；窗口打开/循环/退出事件分别保留未变缓存。不能把全工程缓存全部清空当修复。
- `iCompileFlag`沿原厂值不等于编译通过证据；缓存非空也不证明最近修改经过了原厂检查。

## Stu / Pro 共享更新

两种家族都从主入口使用相同的既有行BLOB白名单、源SHA、字段前指纹、事务、备份与全表复读。策略源码只清变化程序的缓存并同步双容器；配方只改已有行列，见[有界修改](bounded-edits.md)。共用 ACE 连接层，不再有 Pro 独立 Jet 宿主。
