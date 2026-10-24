"""示例：在某个窗口的最上层叠几条细矩形。

典型用途：给多态按钮（0x5028）补边线。原厂运行时不画多态按钮的 common 画笔，
离线预览也已按此不画；要边线就叠 2–4 像素宽的填充矩形。
用法：python 示例_在窗口上叠矩形.py <导出> <新输出目录> <窗口号>
先改 RECTS 的名称、坐标和 EDGE 颜色。输出目录里的 manifest.json 交给 run.ps1 apply。
"""
from pathlib import Path
import json, sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mcgs_ui as u

EDGE = '#4A7499'
RECTS = [('新增_边线_上', [0, 0, 1920, 2]), ('新增_边线_下', [0, 70, 1920, 72]),
         ('新增_分隔_1', [478, 0, 482, 72])]


def main(export_dir, out_dir, wid):
    exp = u.Export(export_dir)
    w = exp.window(wid)
    tpl = u.Templates.pick(exp, kinds=('rect',))
    clash = {u.control_name(r) for r in w.controls} & {n for n, _ in RECTS}
    assert not clash, ('控件名已存在', clash)
    w.controls += [u.new_rect(tpl['rect'], n, r, EDGE, None, 1) for n, r in RECTS]
    c = u.Candidate(exp, out_dir, f'窗口 {wid} 叠加 {len(RECTS)} 个矩形')
    c.update_window(wid, w)
    print(json.dumps(c.write(), ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]))
