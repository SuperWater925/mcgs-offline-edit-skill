"""全工程文字容纳检查：静态文字与按钮文案在原厂内边距下是否放得下，以及控件框是否交叠。

依据实机截图：原厂文字左右各留约 6 像素，宽度不够时直接裁掉末字。
这里按微软雅黑实际字宽 + 左右各 8 像素判断；动态文字（CAniOutput）与多语言 token 不判。
带可见条件的控件不参与交叠判断（同位叠放的几种状态本来就互斥显示）。
只读导出目录，不打开数据库。

用法：python 文字容纳检查.py <导出或候选导出> <输出.json> [--screen 1920x1080] [--segment-ok 窗口号 ...]
  --screen      判断“画面外”的边界；默认用每个窗口自己的宽高。
  --segment-ok  这些窗口里相邻按钮按设计共用 1 像素边线，1 像素交叠不报。
改动前后各跑一次，比较两次结果，不要求绝对为 0。
"""
from pathlib import Path
import argparse, json, sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mcgs_ui as gen

PAD = 16  # 左右合计
VPAD = 4


def font_of(raw):
    f = gen.fonts(raw)[0]
    return f['height'], f['weight']


def check_record(rec, wid, path, group_rect, out, bound):
    cm = gen.CommonEnvelope.parse(rec)
    rect = list(cm.rect)
    if group_rect:
        gx, gy, gr, gb = group_rect
        rect = [round(gx + rect[0] * (gr - gx) / 10000), round(gy + rect[1] * (gb - gy) / 10000),
                round(gx + rect[2] * (gr - gx) / 10000), round(gy + rect[3] * (gb - gy) / 10000)]
    name = path + cm.name.value
    if rect[1] >= bound[1] or rect[0] >= bound[0]:
        return
    if rec.type_id == 0x503a:
        for ch in gen.GroupArchive.parse(rec).children:
            check_record(ch, wid, name + '/', rect, out, bound)
        return
    caption = None
    if rec.type_id == 0x5008:
        if any(a['class_name'] == 'CAniOutput' for a in cm.animations):
            return
        q = gen.LabelRecord.parse(cm.project_without_animations())
        caption, (h, wt) = q.caption, font_of(q.font)
    elif rec.type_id == 0x5027:
        q = gen.ButtonArchive.parse(cm.project_without_animations())
        caption, (h, wt) = q.caption.value, font_of(q.font)
    if not caption or caption.startswith('\x07'):
        return
    width = gen.text_width(caption, h, wt)
    lines = len(caption.splitlines()) or 1
    w, hh = rect[2] - rect[0], rect[3] - rect[1]
    if width + PAD > w or h * lines + VPAD > hh:
        out.append(dict(window=wid, name=name, caption=caption, rect=rect, font=h, weight=wt,
                        text_width=round(width, 1), need_width=round(width + PAD), have_width=w,
                        need_height=h * lines + VPAD, have_height=hh))


def overlaps(window, wid, bound, segment_ok):
    """同一窗口里文字/数值/按钮/多态控件之间的矩形重叠（卡片、线、图片、构件不算）。"""
    items = []
    for rec in window.controls:
        if rec.type_id not in (0x5008, 0x5025, 0x5027, 0x5028, 0x502a):
            continue
        cm = gen.CommonEnvelope.parse(rec)
        r = list(cm.rect)
        if r[1] >= bound[1] or r[0] >= bound[0]:
            continue
        hidden_when = [a['expression'] for a in cm.animations if a['class_name'] == 'CAniVisible']
        items.append((cm.name.value, r, tuple(hidden_when)))
    out = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            (na, a, va), (nb, b, vb) = items[i], items[j]
            if va or vb:  # 互斥显示（可见条件）不判
                continue
            w = min(a[2], b[2]) - max(a[0], b[0])
            h = min(a[3], b[3]) - max(a[1], b[1])
            if w > 0 and h > 0 and not (w == 1 and wid in segment_ok):
                out.append(dict(window=wid, a=na, b=nb, rect_a=a, rect_b=b, overlap=[w, h]))
    return out


def main(export_dir, out_path, screen=None, segment_ok=()):
    export = gen.Export(export_dir)
    problems, clashes = [], []
    for wid in export.window_ids():
        w = export.window(wid)
        props = w.settings().properties
        bound = screen or (props[6].value, props[7].value)
        for rec in w.controls:
            check_record(rec, wid, '', None, problems, bound)
        clashes += overlaps(w, wid, bound, set(segment_ok))
    Path(out_path).write_text(json.dumps(dict(text_fit=problems, overlaps=clashes), ensure_ascii=False, indent=1) + '\n', 'utf-8')
    for p in problems:
        print(f"{p['window']:>3} {p['name']:<24} {p['caption'][:20]!r:<24} 需{p['need_width']:>4} 有{p['have_width']:>4}  高需{p['need_height']} 有{p['have_height']}  {p['rect']}")
    print('text_fit total', len(problems))
    for c_ in clashes:
        print(f"重叠 {c_['window']:>3} {c_['a']} {c_['rect_a']} × {c_['b']} {c_['rect_b']} 交叠{c_['overlap']}")
    print('overlap total', len(clashes))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='只读导出目录，检查文字放不下和控件框交叠。')
    ap.add_argument('export')
    ap.add_argument('output')
    ap.add_argument('--screen', help='例如 1920x1080；默认用每个窗口自己的宽高')
    ap.add_argument('--segment-ok', type=int, nargs='*', default=[])
    a = ap.parse_args()
    screen = tuple(int(v) for v in a.screen.lower().split('x')) if a.screen else None
    main(a.export, a.output, screen, a.segment_ok)
