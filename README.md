# 昆仑通态 MCGS 离线工程编辑技能（Stu / Pro）

给 Claude Code / Codex 使用的技能，离线读取、检查和修改 McgsStu `.MCS`、McgsPro `.MCP` 工程。**两种软件共用一个技能、一个 `run.ps1` 主入口及同一套 PowerShell 7 / ACE / Python 环境。**

**不限定软件大版本或小版本。** 版本号只记录，按实际数据库、归档结构、引用、完整回环与有限修改边界判断能力。保留原版本字段和未知字节，未知结构明确报告。

[下载技能包](https://github.com/SuperWater925/mcgs-offline-edit-skill/releases/latest) · [更新记录](CHANGELOG.md) · [验证范围](references/unified-validation.md) · [贡献指南](CONTRIBUTING.md)

## 功能范围

| 功能 | McgsStu | McgsPro |
| --- | --- | --- |
| 共享快照、安全导出、全表指纹、比较 | 共用主入口 | 共用主入口 |
| 现有行的受限 BLOB 更新 | 源 SHA、字段前指纹、白名单、事务与提交复读 | 同左 |
| 已有文字、输入框、标准按钮等控件修改 | `controls`，支持组内路径及控件前指纹 | 同左，按真实结构适配 |
| 已有策略源码、配方单元格 | `strategy-source` / `recipe-cell` | 同左，保留双容器与封套 |
| 已测历史输入框长度异常 | 显式 `normalize-inputs`，只读不自动修复 | 同左 |
| 基础 JSON 工程、变量、控件创建与编辑 | 无空白工程工厂 | `create` / `edit` / `demo` |
| 模板控件工厂、样式、预览、文字检查、受限新增窗口 | 保留既有 `tools/` 工具链 | 未将这组 Stu 工具扩展为通用 Pro 工厂 |

字段、命令和规格见[有界修改](references/bounded-edits.md)、[Pro 适配](references/pro-adapter.md)、[Stu 界面工具](references/ui-tools.md)。不提供任意新控件、通用表增删、设备协议生成或 PLC 程序开发。

文件读写阶段不启动厂商软件、不连接设备。`apply` 默认只预检；提交输出新文件，或在独立备份后就地修改。原厂打开、全工程检查、编译和相关交互另行验收。

重复修改优先使用 `baseline`、`batch-edit` 和 `apply -ExportAfter`：一次准备基线、多项修改合成一次提交，并复用提交后完整回读生成导出。Stu 预览可只解析本次修改页及公共层；命令、规格和实测见[离线提速](references/offline-performance.md)。

优化版 `v2026.10.30-offline-opt` 已完成 211 项离线/预览检查及安装后 9 项检查；六步混合修改本机耗时减少约 88.5%。本轮未重做原厂编译或实机验证，历史原厂验收范围单独保留。

## 安装

从 [Releases](https://github.com/SuperWater925/mcgs-offline-edit-skill/releases/latest) 下载 ZIP，按同页 `SHA256SUMS.txt` 核对 SHA256。解压后的顶层目录是 `mcgs-offline-edit`，放入其中一处：

- Claude Code：`%USERPROFILE%\.claude\skills\mcgs-offline-edit`
- Codex：`%USERPROFILE%\.codex\skills\mcgs-offline-edit`

也可以克隆：

```powershell
# Claude Code
git clone https://github.com/SuperWater925/mcgs-offline-edit-skill.git "$env:USERPROFILE\.claude\skills\mcgs-offline-edit"
# Codex
git clone https://github.com/SuperWater925/mcgs-offline-edit-skill.git "$env:USERPROFILE\.codex\skills\mcgs-offline-edit"
```

目标已存在时，先比较并保全本地修改。保留整个目录结构，不只复制 `SKILL.md`。Codex 中调用 `$mcgs-offline-edit`，Claude Code 中描述任务，或直接执行命令。

## 共用环境

- Windows、PowerShell 7、Python 3.11+。
- 与 PowerShell 位数匹配的 Microsoft ACE OLEDB 16.0 或 12.0；优先 16.0，再试 12.0。
- Pro 新建数据库另需同位数 `ADOX.Catalog`，不再使用独立 32 位 PowerShell 5.1 / Jet OLEDB 环境。
- 核心命令无 pip 依赖；Stu 预览和文字宽度工具另需 Pillow，SVG 预览可选 Node.js / sharp。
- 原厂 McgsStu / McgsPro、驱动、控件和字体用于最终验证，由使用者安装。

`assets/pro-3.5-cli/` 仅保留兼容路径及模板来源，不是版本门槛，也不再注册第二个技能。详见[环境说明](references/environment-and-tools.md)。

## 快速使用

在技能目录执行，替换本次输入与新的输出路径；两种工程使用同样的已有内容处理命令：

```powershell
pwsh -NoProfile -File .\run.ps1 doctor
pwsh -NoProfile -File .\run.ps1 inspect -Project 'D:\工程\当前.MCP' -Out 'D:\验收\导出'
pwsh -NoProfile -File .\run.ps1 audit --export 'D:\验收\导出'
pwsh -NoProfile -File .\run.ps1 controls --export 'D:\验收\导出' --spec 'D:\修改\控件.json' --out 'D:\验收\控件补丁'
pwsh -NoProfile -File .\run.ps1 apply -Project 'D:\工程\当前.MCP' -Manifest 'D:\验收\控件补丁\manifest.json' -Out 'D:\验收\修改.MCP'
```

最后一条只预检。已有写入授权并确认本次清单后，加 `-Commit` 才提交；就地写入另需 `-InPlace -Backup <新备份路径>`。`doctor` 通过仅表示环境可用。

## 本轮验证

2026-10-30 本地验证覆盖 6 份 Pro、38 份厂商样例/模板和新旧 Stu，共 46 个不同工程，完成 7,888 项专项检查及适用记录功能回归。测试工程、业务数据、截图和厂商程序不公开；见[验证摘要](references/unified-validation.md)与[机器统计](references/validation.json)。

- 六份 Pro 修改副本均原厂打开；补齐 H5U_MODBUSTCP、McgsIoT 和另发现的 S7Plus G2 依赖后，全部为零错误，警告按实际结果保留。
- Pro 控件/策略/非空配方综合副本为 0 错误、0 警告；Stu 综合副本为 0 错误、3 条已有警告。
- 两种软件均观察到本机模拟页面和指定交互；P06 策略综合副本保存重开后为 0 错误、19 条警告。
- 未执行实体 HMI/PLC 下载、通信或现场配方运行。历史验收不代表其他新工程自动通过。

原厂可能只先报告第一项缺失驱动，补齐后须重做全工程检查，见[驱动依赖](references/driver-dependencies.md)。

## 仓库与发布检查

```powershell
python scripts/check_repository.py --update-manifest
python scripts/check_repository.py
pwsh -NoProfile -File scripts/check_powershell.ps1
python scripts/build_release.py --version v2026.10.30-offline-opt --out local-artifacts/release
```

静态检查覆盖语法、JSON、链接和指纹，不证明原厂编译。打包器先验证清单，再输出单技能根目录 ZIP 和 SHA256 文件。格式与写入器改动仍须附对应回环、差异和原厂证据。

欢迎通过 [Issues](https://github.com/SuperWater925/mcgs-offline-edit-skill/issues/new/choose) 和 PR 参与；任务见 [ROADMAP](ROADMAP.md)。只提交有权公开的最小脱敏资料。

## 许可

本项目不是昆仑通态官方工具。代码按 [MIT](LICENSE) 发布；Pro 适配器原始第三方许可见 [THIRD_PARTY_LICENSE.txt](assets/pro-3.5-cli/THIRD_PARTY_LICENSE.txt)。包中不含厂商二进制、客户工程或账号。
