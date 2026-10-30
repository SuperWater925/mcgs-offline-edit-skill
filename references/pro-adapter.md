# Pro 格式适配（共用 Stu 环境）

仅此主技能注册入口。原`mcgs-offline-engineering`不再作为第二个技能/环境。Pro脚本暂保留在`assets/pro-3.5-cli`兼容路径；数据库连接来自主包`scripts/ace-runtime.ps1`。

软件大版本和小版本只记录。`MCGSVER`用于区分Stu/Pro家族；现有工程不用匹配模板的发行版本。解析、长度、ID、引用、完整字节回环和写入清单决定实际支持面。当前变量布局已在12.0和13.0头的样本完整验证，序列化保留原头；不能用改版本字段的办法适配未知布局。

```powershell
pwsh -NoProfile -File .\run.ps1 inspect -Project 'D:\工程\当前.mcp' -Out 'D:\验收\导出'
& 'C:\Python\python.exe' -X utf8 .\scripts\native_tool.py audit --export 'D:\验收\导出'
pwsh -NoProfile -File .\run.ps1 create --spec 'D:\规格\create.json' --output 'D:\工程\新建.mcp'
pwsh -NoProfile -File .\run.ps1 edit --source 'D:\工程\当前.mcp' --spec 'D:\规格\edit.json' --output 'D:\工程\修改.mcp'
```

基础JSON支持变量新增/初值/注释/单位，以及标签、线、矩形、数值输入的新增和受支持字段编辑。只校验本次新增或显式修改的初值，不以现有其他变量的历史取值拒绝整项无关修改。具体字段见[JSON规格](../assets/pro-3.5-cli/references/editing.md)。

新建数据库必须保留原生自增身份列、主键和唯一索引；只复制字段类型与行数据不够。旧新建器漏掉COUNTER后，原厂无法新增`VARCOLLECTTABLE`，模拟器报窗口系统初始化`-95`。当前模板附带原生结构元数据，创建后比较各表行、字段类型、自增属性和索引。已有工程的`edit`保持其原结构，不暗中迁移数据库。

数值输入绑定同步名称、真实ID与布尔/数值类型，只清变化绑定的表达式缓存；范围修改和未变绑定保留缓存。范围须为有限float32且下限不大于上限。窗口设置按实际属性和变长不透明密码区解析，不假设固定尾部长度。

JSON `create`基于通用800×480模板；`edit`保留原工程和未知控件。未知字段、实际结构不符、源SHA/控件SHA变动即拒绝相关改动，不能吞掉不支持项后称完成。主入口`apply`采用两种工程共用的已有行白名单，默认只预检，已有授权下`-Commit`；就地模式仍须新备份。

标准按钮317.1和317.2的元数据尾、输入框325.1/325.3、文字321.1/352.1是当前实测结构分支。带已证动画的文字等先使用`CommonEnvelope.project_without_animations()`，完成类别解析/修改后`restore_projected()`恢复原动画；无动画解析器不能直接用于带动画原记录。未知动画保持不动。

六样本及38份厂商示例的实际覆盖见[统一验证](unified-validation.md)。已有策略双容器、配方单元格、标准控件批量修改已使用共享入口实际提交复读；命令与范围见[有界修改](bounded-edits.md)。图片模式2、事件触发器和已测配方尾部已按实际结构适配，未知分支仍保留。原厂验收见[验收步骤](../assets/pro-3.5-cli/references/acceptance.md)。

发行版本和控件/变量头部的数值仅记录并保留，不单凭数值拒绝。已测数值标记用于来源说明；读写仍须满足实际字段布局、长度、完整回环和有限变更边界。
