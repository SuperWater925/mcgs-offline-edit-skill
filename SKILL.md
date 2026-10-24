---
name: mcgs-offline-edit
description: 离线检查、修改昆仑通态MCGS工程，分Stu与Pro两条路线。McgsStu的原生MCS工程：策略、配方、数据对象和已验证的原生界面归档（含控件生成、样式批量修改、离线预览、文字检查、新建窗口），并保全工程与运行配方。McgsPro 3.5的mcp工程：新建工程、页面、基础控件与变量的生成和修改，功能持续补充。用于工程复读、界面调整及脚本修复。
---

# 昆仑通态MCGS离线工程编辑（Stu / Pro）

把需求落实成可编辑原生工程、有限变更清单和可回读的证据。此技能来自McgsStu 3.5项目中实际使用的离线工具；随包没有厂商DLL、当前用户工程或账号。支持中文变量和中文交付。

## 先选正确路线

- `.MCS`且确认是McgsStu原生Access/Jet数据库：使用本包`run.ps1`及`scripts/native/`。先记录软件完整版本、目标屏、分辨率和当前输入SHA，检查归档标记与schema。不要把扩展名当成兼容性证明。
- McgsPro 3.5.1.6963的`.mcp`：使用[Pro路线](references/environment-and-tools.md#pro路线)，工具在`assets/pro-3.5-cli`，入口见其中的`SKILL.md`。目前支持新建工程、页面、标签/线/矩形/数值输入和变量的生成与修改，其余功能陆续补充；没有证据的能力不要假称已支持。它走32位Jet数据库，与Stu的ACE路径不同；不要拿它处理Stu的MCS，也不要拿Stu的工具处理mcp。
- 其他版本或未知格式：先只读识别，保留未知内容；不要改扩展名套格式，不宣称支持任意控件。

工程扩展名`.mcp`与模型上下文协议MCP无关。此工程离线改写不需要项目专用MCP服务；可用接口及本地替代见[工具链](references/environment-and-tools.md)。

## 实施入口

1. 读取[数据库与事务](references/database-and-transactions.md)。用`doctor`确认当前电脑能读取数据库，再对用户正在使用的路径取得共享快照和全表指纹。用户保存新版本后重新取基线，不硬锁历史SHA，不以旧交付副本覆盖新保存。
2. 按任务读取对应参考：
   - 接手具体工程时，先在工程自己的文件夹里建一份项目约定（模板见[项目约定](references/project-profile.md)），以实际生产源码为准，旧变量注释可能已过期。
   - 窗口、按钮、输入、文字、原生样式与缓存，以及原厂运行时实测规律：[原生界面](references/native-ui.md)。
   - 改界面、新建窗口、离线预览、文字检查的工具和流程：[界面工具](references/ui-tools.md)。
   - 配方注册、100组、别名、增减段和单框全秒阶梯：[配方与预览](references/recipes-and-preview.md)。
   - HMI与PLC握手要点、EVOs驱动类型码与iFA接口：[PLC对接](references/plc-handoff.md)。
   - 原生时间范围、原始CSV导出、可调存盘及真实完成：[统计与导出](references/statistics-and-export.md)。
3. 生成明确BLOB和字段清单。现成`scripts/native_tool.py strategy-source`只替换已有单脚本策略源码，同时更新两份策略容器，清除该动作缓存，保留其他策略与触发器。复杂控件改动使用随包解析类，先字节回环再生成有限增量；没有模板/格式证据的能力不得假称已经实现。
4. `apply`默认只校验。用户已授权修改时用`-Commit`，可输出新副本；用户已指定就地修改时用`-InPlace -Backup <新备份路径>`，不额外强制要求新工程副本。必须通过源SHA、字段前指纹、固定白名单、排他事务和全表后验。锁冲突或基线变动即停止该次写入，不强关用户编辑器，不绕守卫。
5. 按[验收与已知坑](references/pitfalls-and-validation.md)对实际输出复读。结构通过不等于原厂编译或运行通过；分别记录原厂打开/检查/保存重开/编译、本机模拟和现场结果。未做的项目保留`false/pending`。

## 可执行能力与边界

`run.ps1`提供`doctor/inspect/snapshot/fingerprints/compare/apply`。Stu写入器只实现已有行的已验证BLOB字段更新，不实现任意SQL、建空白Stu工程、删除数据库行或PLC下载。新建窗口用`tools/新增窗口事务.ps1`（只多允许新增WndUser行）；以工程里同类控件为模板的控件生成、样式批量修改、离线预览和文字检查在`tools/`，见[界面工具](references/ui-tools.md)。指纹覆盖所有实际数据库表；账户值不导出，未知表仅输出哈希。完整命令和清单格式见[数据库与事务](references/database-and-transactions.md)。

离线编辑授权不自动包含现场下载、设备写入或运行配方改写。保持原变量ID、地址、权限、驱动、未知字节和未列字段；缺少PLC地址/协议依据时报告待配置，不编造可投运配置。若用户请求进一步能力，在明确格式证据与当前授权范围内实现，并验证新增能力。

## 包内来源

这是可搬移的主包；运行入口和`tools/`都按自身路径加载依赖，不读取原作者工作目录，也不含任何具体工程的资料。`references/source-provenance.json`记录复制/裁剪的源码来源与原SHA；`references/package-files.sha256.json`记录交付文件SHA。独立安装整个目录即可；依赖前提见[环境](references/environment-and-tools.md)。
