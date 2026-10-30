# 环境、安装与工具接口

## Stu / Pro 共用前提

Windows、PowerShell7，以及与进程位数相同的Microsoft ACE OLEDB 16.0或12.0。入口优先16.0，失败才试12.0；这两个是数据库提供程序版本，不表示工程有16张/12张表。项目实际为12张业务表，必须动态枚举，不能据此只比较某几张表。

Python3.11+用于纯字节归档解码、候选准备和Pro CLI；Stu/Pro数据库命令本身只依赖PowerShell/.NET和ACE。优先显式传入本机已有Python路径；找不到时可在Codex中调用`mcp__codex_app__load_workspace_dependencies`定位已捆绑运行时。不要把某台机器的Python绝对路径写成迁移前提。核心脚本无pip依赖；`tools/`的离线预览和文字宽度计算需要Pillow，SVG图片另需Node.js和sharp（可选），见[界面工具](ui-tools.md#前提)。

原厂McgsStu / McgsPro及相匹配的控件、驱动、字体用于最终检查与模拟，由接收者安装；本技能不分发它们。不要下载未知DLL补齐依赖。

将整个`mcgs-offline-edit`文件夹放到目标电脑的`%USERPROFILE%\.codex\skills\`（Codex，调用`$mcgs-offline-edit`）或`%USERPROFILE%\.claude\skills\`（Claude Code），也可用PowerShell7直接运行该文件夹内的`run.ps1`。保留`assets/`、`scripts/`、`references/`的相对结构。若同名技能已有本地改动，先比较再合并，不盲目覆盖。

参与开发时以独立仓库为准，不自动覆盖Codex和Claude Code已经安装的技能副本。审核后的版本再按需安装；安装目录有本地修改时先比较保全。

修改后运行`python scripts/check_repository.py --update-manifest`重算`references/package-files.sha256.json`，再运行不带参数的检查确认一致。清单按路径不区分大小写排序，记录文件字节数和SHA256；排除清单自身、Git元数据、Python缓存、本地虚拟环境和`local-artifacts/`。`descriptor_sha256`是各行`路径\0sha256\n`拼接后的SHA256。详细提交流程见[贡献指南](../CONTRIBUTING.md)。

```powershell
pwsh -NoProfile -File .\run.ps1 doctor
pwsh -NoProfile -File .\run.ps1 doctor -Project 'D:\工程\当前.MCS'
```

`doctor`枚举ACE并只读打开指定工程；不创建写测试数据库，因此`database_write_tested=false`。其通过不证明原厂软件能编译工程。

## 用过的工具接口与替代

| 工具/API | 用处 | 无此接口时 |
| --- | --- | --- |
| `exec_command`、Claude Code的`Bash/PowerShell`或本地shell | 启动PowerShell/Python，读文件、计算SHA、执行离线脚本 | Windows终端运行本包命令 |
| `apply_patch`、Claude Code的`Edit/Write`或本地文件编辑 | 精确修改脚本与清单 | 编辑器保存UTF-8源码与JSON |
| `view_image`、Claude Code的`Read` | 查看已在磁盘上的原厂截图/离线预览 | 本地图片查看器；应区分两类证据 |
| `mcp__codex_app__load_workspace_dependencies` | 定位Codex已有Python等运行时 | 手工指定已安装解释器 |
| `mcp__codex_app__open_in_codex` | 打开交接文档/预览，便于审阅 | 资源管理器或本地查看器 |
| `mcp__node_repl__js` | 历史会话中的持久JavaScript检查、纯字节分析与工具编排 | 本包PowerShell/Python或本机Node；不要求新建MCP服务 |
| 浏览/搜索工具 | 官方帮助或版本资料；离线源码处理不依赖网络 | 接收方安装目录中的官方帮助及现成证据 |
| computer-use技能/获准UI接口 | 必要时执行原厂检查、保存重开、本机模拟 | 用户在原厂编辑器操作并保存实际日志 |

表中是实际用过的接口，不是声称目标电脑必然具有这些工具。每次会话应发现实际可用工具。MCP是工具调用协议；`mcp__...`工具名只是某些能力由MCP公开。项目文件`.mcp`与此协议没有关系；本包没有新建MCP服务、监听端口或伪造厂商MCP API，也不要求Codex专用联网服务才能离线处理。

## 统一入口与格式适配

两种工程使用 PowerShell 7 / ACE。`scripts/ace-runtime.ps1` 是共享连接层，优先 ACE16，再试 ACE12；不另启 32 位 Windows PowerShell 或 Jet OLEDB 宿主。

Pro 新建另需同位数 ADOX.Catalog 创建 Jet 4 兼容数据库格式，这不等于使用 Jet OLEDB 提供程序。原始通用模板来自 McgsPro 3.5.1.6963、800×480，描述来源，不限制现有工程版本；目标屏或分辨率变更仍须真实模板依据。

`MCGS_PYTHON` 可指定现有 Python，`MCGS_PWSH` 可指定 PowerShell 7。旧入口 `assets/pro-3.5-cli/run.cmd` 同样使用共用连接层；历史目录名不表示另一个环境，不再注册子技能。

```powershell
pwsh -NoProfile -File .\run.ps1 inspect -Project 'D:\工程\当前.MCP' -Out 'D:\验收\导出'
pwsh -NoProfile -File .\run.ps1 audit --export 'D:\验收\导出'
pwsh -NoProfile -File .\run.ps1 create --spec 'D:\规格\create.json' --output 'D:\工程\新建.MCP'
pwsh -NoProfile -File .\run.ps1 edit --source 'D:\工程\当前.MCP' --spec 'D:\规格\edit.json' --output 'D:\工程\修改.MCP'
```

`doctor` 默认只读；Pro 兼容 CLI 的 `doctor --workdir <目录>` 可单独验证临时数据库创建与二进制复读。原厂软件、控件、驱动和字体由使用者安装，缺失时见[驱动依赖](driver-dependencies.md)。

软件大小版本只记录，实际结构、长度和完整回环决定能力。已测范围见[统一验证](unified-validation.md)，有限字段见[有界修改](bounded-edits.md)。

## 打包

`python scripts/build_release.py --version v2026.10.30 --out local-artifacts/release` 先验证清单，再输出 `mcgs-offline-edit/` 为唯一顶层目录的 ZIP 及独立 `SHA256SUMS.txt`。发布号与 MCGS 软件版本无关。输出必须是新目录。
