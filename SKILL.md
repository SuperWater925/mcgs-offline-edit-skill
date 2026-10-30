---
name: mcgs-offline-edit
description: 在同一环境中离线检查、修改昆仑通态 McgsStu 原生 MCS 和 McgsPro 原生 MCP 工程，处理已有页面、控件、变量、策略与配方，并保留可回读的变更证据。软件大版本、小版本仅记录，按实际归档结构判断能力。
---

# 昆仑通态 MCGS 离线工程编辑（Stu / Pro）

一个技能、一个 `run.ps1` 入口，共用 Windows、PowerShell 7、同位数 ACE 16.0/12.0 和 Python 3.11+；不再要求 Pro 使用 32 位 PowerShell 5.1 / Jet。核心无需 pip 包；Stu 预览/文字工具另用 Pillow，SVG 预览可选 Node.js/sharp。随包没有厂商 DLL、用户工程或账号。安装及命令见[统一环境](references/environment-and-tools.md)。

## 先识别内容

- 原生 `.MCS` 对应 Stu，原生 `.MCP` 对应 Pro。先 `doctor/inspect`，核数据库表、`MCGSVER`、工程 SHA 和实际归档；扩展名或软件版本号不能代替结构证明。
- **不按软件大版本、小版本设置准入白名单。** 版本只记录，不改写版本字段假装兼容；实际字段、长度、记录边界、引用和字节回环决定能否处理。未知结构保留并列出具体缺口。
- Stu/Pro 使用同一数据库层；字节适配器按真实结构选择。Stu 常见 MCGSZIPE 和 ObjData 16.0，当前 Pro 样本为明文封套及 ObjData 12.0/13.0；这些是归档证据，不是软件发行版本限制。不要把 Pro 数据交给不匹配的 Stu 结构解析器。
- `.mcp` 工程扩展名与模型上下文协议 MCP 无关；离线处理不需要额外服务、监听端口或联网 API。

## 实施

1. 读[数据库与事务](references/database-and-transactions.md)，对当前输入做共享快照和完整表指纹。用户重新保存后刷新基线，不能用历史 SHA 或旧交付覆盖新内容。
2. 两种工程都使用 `run.ps1 doctor/inspect/snapshot/fingerprints/compare/apply`；安全导出后的归档检查都调用 `scripts/native_tool.py audit --export ...`。Pro 的有限 JSON 新建/编辑也从主入口调用 `create/edit/demo`，详见[Pro 格式适配](references/pro-adapter.md)。
3. 使用当前样本证明解析、原字节回环、有限修改和逆向恢复。未修改的节点、动画、权限、驱动、变量 ID、地址、未知字节保持原样。Pro 本次的覆盖与缺口见[统一验证](references/unified-validation.md)。
4. 生成明确字段和 BLOB 清单。`apply` 默认只校验；已授权写入时 `-Commit`，需要就地修改时 `-InPlace -Backup <新路径>`。源 SHA、字段前指纹、固定白名单、排他事务、全表后验和提交后复读都须通过；不强关编辑器或绕过锁。
5. 依[验收与已知坑](references/pitfalls-and-validation.md)分别记录文件回读、原厂打开/检查/保存重开/编译、本机模拟、现场通信。未执行的项目写 `false/pending`，结构通过不等于原厂编译或可投运。

## 当前能力

| 项目 | Stu | Pro |
| --- | --- | --- |
| 共享快照、安全导出、全表指纹、比较 | 共用入口 | 共用入口 |
| 已有行的受限 BLOB 更新 | 共用固定白名单与事务守卫 | 共用固定白名单与事务守卫 |
| 变量与基础 JSON 工程创建/编辑 | 不提供空白工程工厂 | `create/edit`；保留原 ObjData 头，能力由结构决定 |
| 窗口封套、属性、事件 | 共用结构适配器 | 共用结构适配器 |
| 原生标准按钮、输入框、文字 | 模板及结构适配 | 已补分支；动画按 CommonEnvelope 投影并恢复 |
| 已有策略源码替换、配方单元格 | 共用 `strategy-source/recipe-cell` | 共用命令，实际提交已测 |
| 已有控件批量修改 | 共用 `controls`，含组内路径及前指纹 | 同左 |
| 历史输入框嵌套长度修复 | `normalize-inputs`，独立主副本精确匹配 | 同左；正常工程无需修复 |

`create/edit` 仅支持文档明确列出的基础控件，不能据此称支持任意控件、建空白 Stu 工程、通用 insert/delete、设备协议生成或 PLC 下载。实际实现扩展应补同样的隔离证据，不能删未知控件让工具通过。

按任务读取：
- 接手具体工程：[项目约定模板](references/project-profile.md)。工程路径、工艺参数与主线资料保存在工程自己的目录。
- 原厂提示缺驱动、只报首个缺失设备：[驱动依赖](references/driver-dependencies.md)。
- 既有 Stu 控件工厂、预览、文字检查及受限新窗口事务：[界面工具](references/ui-tools.md)。这些工具不自动外推为 Pro 工厂。
- 页面、样式、缓存、动画、组与原厂效果：[原生界面](references/native-ui.md)。
- 现成控件、策略与配方命令及规格：[有界修改](references/bounded-edits.md)。
- 配方和预览：[配方](references/recipes-and-preview.md)。
- 触摸屏侧设备变量、类型与绑定：[设备变量](references/device-variables.md)。
- 统计与 CSV：[统计导出](references/statistics-and-export.md)。

离线编辑授权不包含现场下载、设备写入或运行配方改写。地址/协议缺少依据时如实记待配置。包内来源和文件清单见 `references/source-provenance.json`、`references/package-files.sha256.json`；完整目录可搬移，测试用户工程不打包。
