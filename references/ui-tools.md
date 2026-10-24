# 界面工具：控件工厂、样式规格、离线预览、文字检查、新建窗口

`tools/`里的工具都只读导出目录、在内存里改字节，最后写成BLOB和manifest；不打开数据库，不启动厂商程序。写进工程仍走`run.ps1 apply`（改已有行）或`tools/新增窗口事务.ps1`（含新建窗口）。

## 前提

- Python 3.11+，装有Pillow（`pip install pillow`），离线预览和文字宽度计算要用。其余只用标准库和`scripts/native`。
- 字体按`%WINDIR%\Fonts`下的微软雅黑（msyh.ttc/msyhbd.ttc）、宋体、黑体计算宽度。
- 工程图库里有SVG图片时，离线预览要用Node.js和sharp转PNG：设环境变量`MCGS_NODE`（node.exe路径）和`MCGS_SHARP`（sharp包路径，或已能`require('sharp')`）。没有也能跑，那几张图记入报告的`asset_decode_limits`，不画。

## 一次完整的改页面流程

1. 共享快照：`run.ps1 snapshot -Project <工程.MCS> -Out <快照.MCS>`。
2. 导出：`run.ps1 inspect -Project <快照.MCS> -Out <导出>`。导出里含窗口、对象、策略、图片和多语言表（MCGSLINGUIST），不含账户和连接。
3. 看现状：`python tools/离线预览.py --export-dir <导出> --output <现状预览>`；`python tools/文字容纳检查.py <导出> <现状检查.json>`。
4. 改：写脚本调用`tools/mcgs_ui.py`，或写规格文件交给`tools/样式规格应用.py`。两者都输出`<新目录>/manifest.json`和`<新目录>/候选导出`。
5. 看候选：对`候选导出`再跑离线预览和文字检查，与第3步比较。
6. 写入新文件：
   - 只改已有行：`run.ps1 apply -Project <快照.MCS> -Manifest <新目录>/manifest.json -Out <新工程.MCS>`先预检，确认后加`-Commit`。
   - 含新建窗口：`pwsh -File tools/新增窗口事务.ps1 -输入快照 <快照.MCS> -事务清单 <manifest.json> -预期清单哈希 <manifest的SHA256> -输出工程 <新工程.MCS> -报告路径 <报告.json>`先预检，确认后加`-Commit`。
7. 复读：对新工程再`inspect`，跑`scripts/native_tool.py audit --export <新导出>`，再预览一次。
8. 原厂McgsStu打开新工程、组态检查、编译；离线检查通过不等于原厂编译通过。

## tools/mcgs_ui.py（控件工厂）

| 名称 | 作用 |
| --- | --- |
| `Export(导出)` | 读导出：`window(号)`、`window_ids()`、`objects_by_name()`、`strategy_sources()`、`raw(表,键,字段)`；每个BLOB读取时核对SHA256，窗口解析后要求字节回环 |
| `Templates.pick(exp, named=None)` | 挑新建控件用的模板：文字（门控关闭）、矩形、直线、恒禁用数值框、恒禁用字符框、标准按钮。挑不到时用`named={'label': (窗口号, 控件名)}`指定 |
| `Page(tpl, objs)` | 按坐标摆控件：`text`/`text_right`/`center`/`rect`/`line`/`card`/`lamp`/`value`/`value_unit`/`prefixed`/`string`/`chip`/`segments`/`button`，都可带可见条件；`controls`的顺序就是绘制层次 |
| `edit_text`/`edit_value`/`edit_button`/`edit_multi`/`edit_nav`/`edit_shape`/`edit_line`/`edit_recipe`/`edit_xy`/`edit_alarm`/`edit_savedata` | 改已有控件的位置、颜色、字号、文案、列宽等样式字段 |
| `new_rect`/`new_text`/`new_line` | 按模板新建静态矩形、文字、直线 |
| `apply_gates(rec, bg, border)` | 开关common画刷/画笔门控：`'none'`关闭，颜色值开启并着色 |
| `bind_display`、`set_decimals` | 新建显示框并绑定数据对象；小数位两处u32一起改 |
| `new_window(模板窗口, 号, 名, 控件)` | 克隆同层窗口的设置（尺寸、背景、公共窗口槽），换ID、名称、控件和事件脚本 |
| `neutral`、`business_sources` | 去掉允许改的样式字段后比较字节，确认脚本、绑定、动作没被碰到 |
| `references_to`、`block_balance_ok` | 查“窗口名.控件名”引用；检查MCGS脚本If/EndIf块平衡 |
| `Candidate(exp, 新目录, 说明)` | `update_window`、`update`、`insert_window`收集改动，`write()`写manifest、BLOB和候选导出；两份策略容器必须一起改 |

色板和样式种类（`TEXT_KINDS`、`VALUE_KINDS`、`BUTTON_KINDS`）在文件开头，可以在自己的脚本里`update`覆盖。颜色写`'#RRGGBB'`。

`tools/示例/`有三个可运行的例子：在窗口上叠矩形、新建页面、样式规格。

## tools/样式规格应用.py

把一份规格文件（Python，定义`SPEC`）批量应用到多个窗口：改已有控件样式，插底板，加标题和线，删无引用的装饰矩形，换窗口背景色。每改一个控件都核对业务字节不变，最后核对每个窗口全部业务源码不变。规格写法见文件开头说明和`tools/示例/示例_样式规格.py`。

## tools/离线预览.py

```text
python tools/离线预览.py --export-dir <导出或候选导出> --output <新目录> [--windows 1 2] [--active-map 规则.json] [--full-dir <另一份导出>]
```

按原生字段画每个窗口，递归合成公共窗口（底板、侧栏），输出每窗PNG、缩略总览、`离线渲染报告.json`和`全工程预览索引.html`。动态值画成“—”占位。

- `--active-map`：导航按钮激活态的模拟规则，格式见`tools/示例/导航激活规则示例.json`。`caption`是按钮文字，`windows`是哪些画面下画成激活态，`layer`（可选）限定只对属于该公共窗口的按钮生效。不给时全部画常态。
- `--full-dir`：旧导出不含多语言表时，指向一份含MCGSLINGUIST的导出。报告里`language_table_loaded`为false时，用多语言token的文字会画成“资源 N”。

与原厂运行时已知不一致：
- 不认可见条件：同位叠放的几种状态全部叠出来，运行时只显示条件成立的那一个。
- 0x5028多态按钮的common画笔（边线）不画，与原厂运行时一致；0x502a未经实机确认，照旧画。
- 字形、行距、系统3D边框和滚动条是近似；报告`opaque_internals`列出近似之处。
- 预览图不是原厂截图，不能当运行验收。

## tools/文字容纳检查.py

```text
python tools/文字容纳检查.py <导出> <输出.json> [--screen 1920x1080] [--segment-ok 41 42]
```

按微软雅黑实际字宽加左右各8像素，检查静态文字和按钮文案放不放得下；检查同窗口文字、数值、按钮、多态控件框的交叠（带可见条件的不判）。动态文字和多语言token不判。改动前后各跑一次比较，不要求结果为0。

## tools/新增窗口事务.ps1

在`run.ps1 apply`的更新白名单之外，只多允许新增WndUser行：
- 六列`iID/strName/strNote/lbObjects/iDeleteFlag=0/iCompileFlag=0`齐全；
- 窗口号、窗口名都不能与已有窗口重复。

其余规则与`apply`相同：
- 校验输入SHA、清单哈希、字段前指纹和BLOB哈希；
- 两份策略容器成对；
- 只写到新文件；
- 排他事务内和提交后都做全表比对，出现清单外的变化就回滚。

不带`-Commit`只做预检。它从`scripts/stu_project.ps1`按函数名取`FullPath/Sha/SharedHash/ValueFingerprint/…`，改那些函数的名称或参数要同步改这里。

新窗口写入后还要：
- 在切换窗口的策略或按钮里接上；
- 原厂编译一次，新页面的绑定才进入采集表（`VARCOLLECTTABLE*`由编译重生成）。
