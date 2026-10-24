# 环境、安装与工具接口

## Stu前提

Windows、PowerShell7，以及与进程位数相同的Microsoft ACE OLEDB 16.0或12.0。入口优先16.0，失败才试12.0；这两个是数据库提供程序版本，不表示工程有16张/12张表。项目实际为12张业务表，必须动态枚举，不能据此只比较某几张表。

Python3.11+用于纯字节归档解码、候选准备和Pro CLI；Stu数据库命令本身只依赖PowerShell/.NET和ACE。优先显式传入本机已有Python路径；找不到时可在Codex中调用`mcp__codex_app__load_workspace_dependencies`定位已捆绑运行时。不要把某台机器的Python绝对路径写成迁移前提。核心脚本无pip依赖；`tools/`的离线预览和文字宽度计算需要Pillow，SVG图片另需Node.js和sharp（可选），见[界面工具](ui-tools.md#前提)。

原厂McgsStu及相匹配的控件、驱动、字体用于最终检查与模拟，由接收者安装；本技能不分发它们。不要下载未知DLL补齐依赖。

将整个`mcgs-offline-edit`文件夹放到目标电脑的`%USERPROFILE%\.codex\skills\`（Codex，调用`$mcgs-offline-edit`）或`%USERPROFILE%\.claude\skills\`（Claude Code），也可用PowerShell7直接运行该文件夹内的`run.ps1`。保留`assets/`、`scripts/`、`references/`的相对结构。若同名技能已有本地改动，先比较再合并，不盲目覆盖。

同一台电脑同时给Codex和Claude Code用时两处各放一份；改技能时两份一起改，改完用`diff -r`确认一致，并重算`references/package-files.sha256.json`：
- 按路径不区分大小写排序，列出除它自身外的全部文件，记字节数和SHA256；
- `descriptor_sha256`是各行`路径\0sha256\n`拼接后的SHA256。

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

## Pro路线

`assets/pro-3.5-cli`保留McgsPro 3.5.1.6963原包CLI、通用空白模板和基础控件资源。其原始说明见该子目录`SKILL.md`与`references/runtime.md`。空白模板中的权限/用户表属于通用新建模板，密码字段已经布尔核验为全空；未复制当前Stu项目账号。

Pro CLI使用Python3.11+、Windows32位PowerShell5.1、ADOX及Jet4.0；Python本身可为64位。Stu的ACE入口与它分开。调用可用显式解释器，无需依赖PATH：

```powershell
& 'C:\本机Python\python.exe' -X utf8 .\assets\pro-3.5-cli\scripts\mcgs_file.py doctor
& 'C:\本机Python\python.exe' -X utf8 .\assets\pro-3.5-cli\scripts\mcgs_file.py inspect 'D:\工程\原生.mcp'
```

原包具有create/edit等有限能力，但本新技能没有重新验证其全部创建/修改能力。请求Pro任务时先读原包版本与支持范围，另做实际验收；不要把Stu验收证据当成Pro通过证据。
