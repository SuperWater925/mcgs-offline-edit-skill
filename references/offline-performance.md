# 离线流程提速

Stu / Pro 继续共用 PowerShell 7、ACE 和 Python。这里合并重复读取和重复提交，不设软件版本门槛，不增加后台服务或监听端口。

## 优先使用的流程

```powershell
# 一次生成稳定原生快照、安全导出和完整字段指纹
pwsh -NoProfile -File .\run.ps1 baseline -Project 'D:\工程\当前.MCP' -Out 'D:\验收\本次基线'
pwsh -NoProfile -File .\run.ps1 audit --export 'D:\验收\本次基线\export'

# 同一基线上的控件、策略、配方修改合并准备
pwsh -NoProfile -File .\run.ps1 batch-edit --export 'D:\验收\本次基线\export' --plan 'D:\修改\批量计划.json' --out 'D:\验收\合并补丁'

# 默认预检；已有写入授权时加 -Commit，并复用提交后回读生成新导出
pwsh -NoProfile -File .\run.ps1 apply -Project 'D:\验收\本次基线\project.MCP' -Manifest 'D:\验收\合并补丁\manifest.json' -Out 'D:\验收\修改.MCP'
pwsh -NoProfile -File .\run.ps1 apply -Project 'D:\验收\本次基线\project.MCP' -Manifest 'D:\验收\合并补丁\manifest.json' -Out 'D:\验收\修改.MCP' -Commit -ExportAfter 'D:\验收\修改后导出'
pwsh -NoProfile -File .\run.ps1 audit --export 'D:\验收\修改后导出'
```

`baseline` 的输出目录必须不存在；内含 `project.MCP` / `project.MCS`、快照记录及 `export/`。可加 `-RecipeRoot <配方目录>`，沿用逐文件稳定复制和成员集合检查；不声称跨文件原子快照。原工程被重新保存时重建基线。

`inspect -Out` 和 `baseline` 都已生成 `fingerprints.json`，通常直接使用它，不必再执行一次 `fingerprints`。独立指纹命令仍可用于只读核验和两个时点比较。

`-ExportAfter` 只用于 `apply -Commit`，且必须是新目录。事务内保留完整全表核对；提交后关闭写连接，再以新只读连接完整回读，同时生成导出。回读前后核文件 SHA，再对照原基线、允许字段与预期值；导出完成前再次检查 SHA。导出是实际工程回读，可供下一轮修改使用。遇锁、工程变化或核对失败时不宣称成功，也不强关编辑器。

## 批量计划

```json
{
  "input_sha256": "当前基线工程的64位SHA256",
  "steps": [
    {"command": "controls", "spec": "控件.json"},
    {"command": "strategy-source", "strategy_name": "已有策略", "source": "源码.txt", "action_path": [0, 0, 0]},
    {"command": "recipe-cell", "group": "已有配方组", "row": 0, "column": 0, "value": "新值"}
  ]
}
```

- 只组合已有 `controls`、`strategy-source`、`recipe-cell` 能力，不执行任意代码或 SQL，不新增控件、行或配方。
- `spec` / `source` 相对批量计划目录解析，也接受明确的绝对路径。控件规格仍使用[有界修改](bounded-edits.md)的格式及原始基线 SHA。
- 同一个控件的多项属性合进一次 `edits`；同页多个控件优先合进同一份 `controls` 规格。重复或父子重叠路径仍拒绝。
- 步骤依次使用内存中的最新 BLOB，可修改同页的不同控件、多个策略，或同一配方组的多个单元格。后续步骤的控件前指纹须与当时内容一致。
- 每一步保留原有解析、回环、逆向和双策略容器检查；最终清单每个字段只写一次，前指纹始终来自最初基线。任一步失败不输出最终补丁目录；实际写库仍由 `apply` 单事务完成。
- `preparation.json` 记录各步证明和耗时；只准备候选不等于写库、语法检查或原厂编译通过。

## 同页控件与局部预览

`controls` 按窗口统一验证：先核每个控件的前指纹和自身归档，再做整窗回环、整体逆向恢复及重放一致性核对。避免每改一个控件都重复解析整个窗口，未知记录、事件和动画仍保留。

Stu 预览时使用 `--windows <本次改动窗口号>`；解析范围为这些窗口及递归公共层，其余页面不解析。报告记录请求、已解析和全工程窗口数量，不能将局部预览当作全工程检查。SVG 在一次 Node.js / sharp 进程中批量转换；单张失败单独记录，不影响其他图片。首次检查 `asset_decode_limits`，缺依赖时优先配置已有的 Node.js / sharp；不要将漏图的预览作为完整效果。

图库仍完整解码，尚未按图片引用延迟加载。此项可作为资源很多时的后续优化；先看报告中的加载与绘图耗时，再决定是否增加缓存。

## 耗时与验证边界

数据库命令输出 `timings_ms`；提交还分列预检读取、稳定复制、排他基线、事务写入核对及提交后回读。批量准备和预览分别记录步骤及加载/绘图耗时。进程外墙钟时间还包含 PowerShell / Python 启动。

2026-10-30 本机墙钟测量如下，不代表其他电脑或工程的固定耗时：

| 场景 | 原流程 | 优化后 | 减少 |
| --- | ---: | ---: | ---: |
| 三份工程的基线准备，每份各测三次，汇总中位数 | 2.68 s | 1.26 s | 53.2% |
| Pro 六步混合修改，单次完整流程 | 16.15 s | 1.85 s | 88.5% |
| Stu 六步混合修改，单次完整流程 | 20.72 s | 2.39 s | 88.5% |
| 100 个控件准备，三次中位数 | 0.58 s | 0.51 s | 13.2% |
| 单页预览，SVG 依赖齐全，三次中位数 | 0.97 s | 0.56 s | 42.3% |

混合流程从六轮各自准备/提交/导出，共 18 次主入口调用，合成两次主入口调用；比较最终完整字段指纹一致。共完成 211 项回归、守卫、既有工具集成及预览检查；六份 Pro 和一份 Stu 控件 BLOB 与旧实现一致，39 页新旧离线预览逐像素一致。本轮没有重做原厂打开、编译或模拟，这些离线结果不扩展既有原厂验收范围。

具体测量见[本轮性能验证](performance-validation.json)。没有以减少备份、源 SHA、字段前指纹、固定白名单、事务或全表检查换速度。原厂检查、保存重开和交互验证应在阶段性成果上集中执行；出现异常或新结构时针对性验证，离线预览与结构回环不代替这些验收。
