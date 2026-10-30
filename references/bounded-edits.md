# Stu / Pro 已有内容的有界修改

以下命令只准备候选 BLOB 和 `manifest.json`，不直接写工程；再交主入口 `apply` 预检及提交。输入均来自本次安全导出，输出必须是新目录。

```powershell
pwsh -NoProfile -File .\run.ps1 audit --export 'D:\验收\导出'
pwsh -NoProfile -File .\run.ps1 controls --export 'D:\验收\导出' --spec 'D:\修改\控件.json' --out 'D:\验收\控件补丁'
pwsh -NoProfile -File .\run.ps1 strategy-source --export 'D:\验收\导出' --strategy-name '循环策略' --source 'D:\修改\源码.txt' --action-path '0,0,0' --out 'D:\验收\策略补丁'
pwsh -NoProfile -File .\run.ps1 recipe-cell --export 'D:\验收\导出' --group '配方组' --row 0 --column 0 --value '12.5' --out 'D:\验收\配方补丁'
pwsh -NoProfile -File .\run.ps1 apply -Project 'D:\验收\当前.MCP' -Manifest 'D:\验收\控件补丁\manifest.json' -Out 'D:\验收\修改.MCP' -Commit
```

`--action-path` 是策略中已有行、列、动作的零基索引，只在多动作策略明确选中一个 `CStgyFuncProg` 时使用；省略时要求唯一单程序。实际参数以 `run.ps1 <命令> --help` 为准。源码变化只清该程序缓存，两份策略容器同步，保留原始压缩或明文封套。语法和运行语义由原厂检查。

控件规格：

```json
{
  "input_sha256": "当前工程SHA256",
  "controls": [{
    "window": "1", "path": [3, 0], "sha256": "目标原控件payload的SHA256",
    "edits": {"text": "新文字", "font": {"height": 24, "weight": 500, "family": "微软雅黑"}}
  }]
}
```

`path` 是顶层控件索引、组内子索引，均从0起。每条要求现有目标及控件前指纹；重叠父子路径、重复目标、未知字段、无实际变化拒绝。补丁验证目标外字节保持原样，整体替换原记录可精确逆向恢复。

| 字段 | 适用 |
| --- | --- |
| `text` | 文字、标准按钮；按钮主副标题同步 |
| `font` | 文字、标准输入框、标准按钮；高度/字重/字体名 |
| `bounds` | 文字、输入框、标准按钮、多态按钮/显示；正向矩形 |
| `fill`, `border` | 公共封套，整数 COLORREF 0..0xffffff；实际门控和原厂绘制语义仍保留 |
| `unit`, `binding`, `minimum`, `maximum` | 输入框；绑定必须是本工程既有标量并匹配数值/字符类别 |
| `press_source`, `release_source` | 标准按钮；仅变化的对应脚本缓存清零 |
| `repair_input_metadata: true` | 输入框已测历史嵌套长度异常 |

字符输入框不能设置数值上下限；改范围时验证有限 float32 与上下限关系。未知动画、图片、权限与非目标业务字段原样保存，不靠删除未知数据通过校验。

## 输入框历史长度异常

旧编辑曾只改外层 ByteArray 长度，漏改输入框属性的两层嵌套长度。`audit` 将这类记录单列为 `known_input_metadata_length_defects`，不默默修复。只在独立主副外观完整相同、固定前后结构可完整回环时承认该已测异常；任意截断和主副本不一致均拒绝。

```powershell
pwsh -NoProfile -File .\run.ps1 normalize-inputs --export 'D:\验收\导出' --out 'D:\验收\长度修复'
```

命令输出明确控件清单和修复证明。正常工程没有需要修改的记录时报告无候选，不创建空补丁。单位及图片修改会同时更新两层嵌套计数；只读导出始终保留原始异常字节。原工程仍应先备份，修复副本须原厂打开检查。
