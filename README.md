# 昆仑通态 MCGS 离线工程编辑技能（Stu / Pro）

给 Claude Code / Codex 用的技能包：离线读取、检查、修改昆仑通态触摸屏工程，分 McgsStu 和 McgsPro 两条路线。

**本仓库只维护触摸屏离线编辑的方法、脚本、工具和文档，不包含 PLC 程序开发、整机控制逻辑或客户生产工程。** 触摸屏工程中的设备变量、绑定和驱动配置可以在格式已验证的范围内处理。

| 版本 | 工程 | 目前支持 |
| --- | --- | --- |
| McgsStu 3.5 | `.MCS` | 策略、配方、数据对象、界面控件的复读与修改；控件生成、样式批量修改、离线预览、文字检查、新建窗口 |
| McgsPro 3.5.1.6963 | `.mcp` | 新建工程和页面；标签、线、矩形、数值输入和变量的生成与修改。其余功能陆续补充 |

文件读写阶段不启动厂商软件、不连设备。写入默认只预检；实际写入按授权输出新文件，或在独立备份后就地修改，并做全表比对。原厂软件用于后续验证。

## 一起参与

欢迎帮忙补控件、验证版本、复现问题、完善离线预览和使用说明。可以先做一个小任务，无须一次掌握整个工程格式。

- [贡献指南](CONTRIBUTING.md)：环境、提交流程与验收要求。
- [首批可认领任务](ROADMAP.md)：每项包含输入、工作范围和完成条件。
- [报告问题或认领任务](https://github.com/SuperWater925/mcgs-offline-edit-skill/issues/new/choose)：请注明 Stu / Pro 和完整软件版本。

基本流程：选一个任务 → 在 Issue 中认领 → Fork 并建立分支 → 修改与验证 → 提交 PR → 维护者审核合并。文档贡献不要求拥有厂商软件；涉及工程格式的改动请附脱敏样例和验证记录，未完成原厂验证时明确标为待验证。

## 安装

文件夹名要和技能名一致，即 `mcgs-offline-edit`：

Claude Code，在 PowerShell 中执行：

```powershell
git clone https://github.com/SuperWater925/mcgs-offline-edit-skill.git "$env:USERPROFILE\.claude\skills\mcgs-offline-edit"
```

Codex，在 PowerShell 中执行：

```powershell
git clone https://github.com/SuperWater925/mcgs-offline-edit-skill.git "$env:USERPROFILE\.codex\skills\mcgs-offline-edit"
```

目标文件夹已存在时先比较本地改动，不直接覆盖。装好后在 Claude Code 里描述要做的事即可，Codex 里用 `$mcgs-offline-edit` 调用；也可以在技能目录运行 `pwsh -File run.ps1 doctor` 检查环境。参与开发时建议另行克隆到开发目录，避免影响正在使用的技能。

## 需要

- Windows，Python 3.11 以上。
- Stu 路线：PowerShell 7，Microsoft ACE OLEDB 16.0 或 12.0（位数与 PowerShell 一致）；界面工具还要 Pillow（`pip install pillow`）。
- Pro 路线：32 位 Windows PowerShell 5.1、ADOX 和 Jet 4.0，详见 `assets/pro-3.5-cli/references/runtime.md`。
- 原厂 McgsStu / McgsPro，用于最终的组态检查、编译和运行，不随包提供。

## 内容

| 位置 | 作用 |
| --- | --- |
| `SKILL.md` | 技能入口：路线选择、实施步骤、能力边界 |
| `run.ps1`、`scripts/stu_project.ps1` | 共享快照、安全导出、全表指纹与比对、带校验的写入（默认只预检） |
| `scripts/native/`、`scripts/native_tool.py` | 原生窗口、控件、策略、配方、数据对象的字节级解析与回环；结构检查与策略源码替换 |
| `tools/` | 控件工厂、样式批量修改、离线预览、文字容纳检查、新建窗口写入，附示例 |
| `references/` | 数据库与事务、原生界面实测规律、配方、统计导出、设备变量与绑定、已知坑、项目约定模板 |
| `assets/pro-3.5-cli/` | Pro 路线：McgsPro 3.5 `.mcp` 工程的命令行工具（第三方，MIT 许可，见其中的许可文件） |
| `CONTRIBUTING.md`、`ROADMAP.md` | 贡献方法与可认领任务 |
| `.github/` | 问题与 PR 模板、仓库自动检查工作流 |

## 提交前检查

```powershell
python scripts/check_repository.py --update-manifest
python scripts/check_repository.py
pwsh -NoProfile -File scripts/check_powershell.ps1
```

仓库检查覆盖 Python 语法、JSON、文档本地链接、技能入口及文件指纹；PowerShell 检查只解析语法。它们不打开客户工程、不调用厂商程序，也不证明 MCGS 编译或运行通过。格式与写入器改动还需按[贡献指南](CONTRIBUTING.md#验证要求)完成对应测试。

## 说明

- 这不是昆仑通态官方工具。格式结论来自实际工程的逆向验证；只改已验证的结构，未知内容原样保留。
- 离线检查通过不等于原厂编译或运行通过。写入后请用对应的 McgsStu 或 McgsPro 打开、组态检查、编译，再做运行验证。
- 包里不含厂商程序、任何具体工程或账号。

## 许可

MIT，见 [LICENSE](LICENSE)。`assets/pro-3.5-cli/` 是第三方代码，按其自带的 MIT 许可文件发布。
