# 昆仑通态 MCGS 离线工程编辑技能（Stu / Pro）

给 Claude Code / Codex 用的技能包：离线读取、检查、修改昆仑通态 MCGS 工程，分 McgsStu 和 McgsPro 两条路线。

| 版本 | 工程 | 目前支持 |
| --- | --- | --- |
| McgsStu 3.5 | `.MCS` | 策略、配方、数据对象、界面控件的复读与修改；控件生成、样式批量修改、离线预览、文字检查、新建窗口 |
| McgsPro 3.5.1.6963 | `.mcp` | 新建工程和页面；标签、线、矩形、数值输入和变量的生成与修改。其余功能陆续补充 |

全程不启动厂商软件、不连设备。所有写入都输出到新文件，并做全表比对。

## 安装

文件夹名要和技能名一致，即 `mcgs-offline-edit`：

```bash
git clone <本仓库地址> "%USERPROFILE%\.claude\skills\mcgs-offline-edit"
```

Codex 放到 `%USERPROFILE%\.codex\skills\mcgs-offline-edit`。装好后在 Claude Code 里描述要做的事即可，Codex 里用 `$mcgs-offline-edit` 调用；也可以直接运行 `pwsh -File run.ps1 doctor` 检查环境。

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
| `references/` | 数据库与事务、原生界面实测规律、配方、统计导出、PLC 对接、已知坑、项目约定模板 |
| `assets/pro-3.5-cli/` | Pro 路线：McgsPro 3.5 `.mcp` 工程的命令行工具（第三方，MIT 许可，见其中的许可文件） |

## 说明

- 这不是昆仑通态官方工具。格式结论来自实际工程的逆向验证；只改已验证的结构，未知内容原样保留。
- 离线检查通过不等于原厂编译或运行通过。写入后请用对应的 McgsStu 或 McgsPro 打开、组态检查、编译，再做运行验证。
- 包里不含厂商程序、任何具体工程或账号。

## 许可

MIT，见 [LICENSE](LICENSE)。`assets/pro-3.5-cli/` 是第三方代码，按其自带的 MIT 许可文件发布。
