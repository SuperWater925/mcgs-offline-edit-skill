"""按规格文件批量改窗口样式：位置、尺寸、颜色、字号、文案，加静态底板/文字/线，删无引用的装饰件。

所有脚本、使能条件、绑定、动作、权限和编译缓存必须逐字节保持：每改一个控件都比较
neutral(改前) == neutral(改后)，最后再比较每个窗口的全部业务源码。只出候选，不写 MCS。

用法：python 样式规格应用.py --export <导出> --spec <规格.py> --output <新目录> [--tag 名称]
然后用 离线预览.py、文字容纳检查.py 看 <新目录>/候选导出，确认后 run.ps1 apply -Manifest <新目录>/manifest.json。

规格文件是 Python（可 `from mcgs_ui import *` 用色板和 B/T/V/M/MOVE/SHAPE/GROUP/NEW_RECT/NEW_TEXT/NEW_LINE）：
  SPEC = {窗口号: {
      'controls': {控件名: 操作, ...},          # 改已有控件
      'delete': [控件名, ...],                  # 只许删无动画、无任何引用的 0x5004 矩形
      'below': [NEW_RECT(...), ...],             # 依次插到窗口最底层
      'above': [NEW_TEXT(...) / NEW_LINE(...)],  # 追加到最上层
      'replace_background': 控件名,             # 删掉第 0 层的全屏背景图（须无引用）
      'window_background': '#RRGGBB'}}
  操作：B(rect, kind, caption)、T(rect, kind, caption, align=, bg=, border=)、V(rect, kind, align=)、
        M(rect, fills=, ink=, border=)、MOVE(rect)、SHAPE(rect, fill, border, width)、GROUP(rect, {子控件名: 操作})，
        或 dict(op='nav', **NAV)、dict(op='fills', fill=, border=)、dict(op='line', color=, rect=)、
        dict(op='recipe', rect=, widths={列标题: 宽}, row_height=)、dict(op='xy', rect=, border=)、
        dict(op='alarm')、dict(op='alarm_page', rect=)、dict(op='savedata', rect=)。
  可选 TEMPLATES = {'rect': (窗口号, 控件名), 'label': (...), 'line': (...)}，不给时自动挑。
  可选 def text_align(wid, name, kind) / def value_align(wid, name)：操作没写 align 时的默认对齐。
"""
from pathlib import Path
import argparse, collections, copy, importlib.util, json, re, sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mcgs_ui as u


def load_spec(path):
    spec = importlib.util.spec_from_file_location('mcgs_style_spec', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert isinstance(getattr(mod, 'SPEC', None), dict), '规格文件要定义 SPEC'
    return mod


def edit_control(before, s, wid, name, mod):
    op = s['op']
    if op == 'button':
        return u.edit_button(before, s['rect'], s['kind'], s.get('caption'))
    if op == 'text':
        align = s.get('align') or (mod.text_align(wid, name, s['kind']) if hasattr(mod, 'text_align') else None)
        return u.apply_gates(u.edit_text(before, s['rect'], s['kind'], s.get('caption'), align), s.get('bg'), s.get('border'))
    if op == 'value':
        align = s.get('align') or (mod.value_align(wid, name) if hasattr(mod, 'value_align') else None)
        return u.edit_value(before, s['rect'], s['kind'], align)
    if op in ('multi', 'move', 'group'):
        return u.edit_any(before, s)
    if op == 'nav':
        return u.edit_nav(before, s)
    if op == 'fills':
        return u.edit_fills(before, s['fill'], s['border'])
    if op == 'line':
        return u.edit_line(before, s['color'], s.get('rect'))
    if op == 'shape':
        return u.edit_shape(before, s['rect'], s['fill'], s['border'], s.get('width'))
    if op == 'recipe':
        return u.edit_recipe(before, s['rect'], s['widths'], s['row_height'])
    if op == 'xy':
        return u.edit_xy(before, s['rect'], s['border'])
    if op == 'alarm':
        return u.edit_alarm(before)
    if op == 'alarm_page':
        return u.edit_alarm(u.common_style(before, rect=s['rect']))
    if op == 'savedata':
        return u.edit_savedata(before, s['rect'])
    raise ValueError(op)


def main(export_dir, spec_path, output, tag):
    export = u.Export(export_dir)
    mod = load_spec(spec_path)
    windows = {wid: export.window(wid) for wid in export.window_ids()}
    originals = copy.deepcopy(windows)
    tpl = u.Templates.pick(export, getattr(mod, 'TEMPLATES', None), kinds=('rect', 'label', 'line'))
    all_sources = '\n'.join(v for w in windows.values() for _, v in u.business_sources(w)) + '\n' + u.strategy_text(export.path)
    report = dict(input_sha256=export.sha256, spec=str(spec_path), spec_sha256=u.sha(Path(spec_path).read_bytes()),
                  templates=tpl['_source'], windows={}, deleted=[], added=[], gui=False, vendor_code_executed=False,
                  database_opened=False, native_compile_verified=False, native_runtime_verified=False)

    for wid, spec in mod.SPEC.items():
        w = windows[wid]
        win_name = w.settings().properties[1].value
        changes = []
        for name, s in spec.get('controls', {}).items():
            i = u.find(w, name)
            before = w.controls[i]
            after = edit_control(before, s, wid, name, mod)
            renamed = s.get('caption') is not None
            assert u.neutral(before, renamed) == u.neutral(after, renamed), ('业务字节变了', wid, name)
            assert u.control_name(after) == name
            w.controls[i] = after
            changes.append(dict(name=name, op=s['op'], kind=s.get('kind'), rect=list(u.CommonEnvelope.parse(after).rect),
                                caption=s.get('caption'), before_sha256=u.sha(before.payload), after_sha256=u.sha(after.payload)))
        for name in spec.get('delete', []):
            pattern = re.escape(win_name) + r'\.' + re.escape(name) + r'(?![\w㐀-鿿])'
            assert not re.search(pattern, all_sources), ('要删的控件有引用', wid, name)
            rec = w.controls.pop(u.find(w, name))
            assert rec.type_id == 0x5004 and not u.CommonEnvelope.parse(rec).animations, ('只许删无动画的矩形', wid, name)
            report['deleted'].append(dict(window_id=wid, name=name, type='0x5004', sha256=u.sha(rec.payload), references=0))
        below = [u.new_rect(tpl['rect'], s['name'], s['rect'], s['fill'], s['border'], s.get('width', 1)) for s in spec.get('below', [])]
        if 'replace_background' in spec:
            name = spec['replace_background']
            i = u.find(w, name)
            assert i == 0 and w.controls[0].type_id == 0x5009, ('背景图必须是第 0 层图片', wid, name)
            pattern = re.escape(win_name) + r'\.' + re.escape(name) + r'(?![\w㐀-鿿\d])'
            assert not re.search(pattern, all_sources), ('背景图有引用', name)
            rec = w.controls.pop(0)
            report['deleted'].append(dict(window_id=wid, name=name, type='0x5009', sha256=u.sha(rec.payload), references=0))
        w.controls[0:0] = below
        for s in spec.get('above', []):
            if s['op'] == 'new_text':
                align = s.get('align') or (mod.text_align(wid, s['name'], s['kind']) if hasattr(mod, 'text_align') else None)
                rec = u.new_text(tpl['label'], s['name'], s['rect'], s['kind'], s['caption'], align)
            else:
                rec = u.new_line(tpl['line'], s['name'], s['rect'], s['color'])
            w.controls.append(rec)
        for s in spec.get('below', []) + spec.get('above', []):
            report['added'].append(dict(window_id=wid, **{k: v for k, v in s.items() if k != 'op'}, op=s['op']))
        if 'window_background' in spec:
            settings = w.settings()
            assert settings.properties[15].vt == 3
            settings.properties[15].value = u.c(spec['window_background'])
            w.trailer = settings.to_bytes()
        names = [u.control_name(r) for r in w.controls]
        assert len(names) == len(set(names)), ('控件重名', wid)
        report['windows'][wid] = dict(name=win_name, changed_controls=changes,
                                      controls_before=len(originals[wid].controls), controls_after=len(w.controls))

    # 全部窗口：脚本、表达式、绑定、动作、事件和窗口事件逐项不变（删掉的、新加的静态件除外）
    for wid in windows:
        a = collections.Counter(u.business_sources(originals[wid]))
        b = collections.Counter(u.business_sources(windows[wid]))
        gone = tuple(d['name'] + ':' for d in report['deleted'] if d['window_id'] == wid)
        mine = tuple(d['name'] + ':' for d in report['added'] if d['window_id'] == wid)
        a = collections.Counter({k: v for k, v in a.items() if not (gone and k[0].startswith(gone))})
        b = collections.Counter({k: v for k, v in b.items() if not (mine and k[0].startswith(mine))})
        assert a == b, ('业务源码不同', wid, list((a - b).items())[:3], list((b - a).items())[:3])

    cand = u.Candidate(export, output, getattr(mod, 'DESCRIPTION', f'样式规格 {Path(spec_path).name}'))
    for wid, w in windows.items():
        if w.to_bytes() != originals[wid].to_bytes():
            cand.update_window(wid, w, f'WndUser_{wid}_{tag}.bin')
    info = cand.write()
    report.update(operations=len(info['operations']), changed_windows=[k for _, _, k in info['operations']],
                  manifest_sha256=info['manifest_sha256'], business_sources_unchanged=True, deleted_controls_unreferenced=True)
    (Path(output) / '候选生成报告.json').write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', 'utf-8')
    print(json.dumps(dict(operations=report['operations'], windows=report['changed_windows'], deleted=len(report['deleted']),
                          added=len(report['added']), changed_controls=sum(len(v['changed_controls']) for v in report['windows'].values()),
                          candidate_export=info['candidate_export']), ensure_ascii=False))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='按规格文件批量改窗口样式，业务字节保持，只出候选。')
    ap.add_argument('--export', required=True)
    ap.add_argument('--spec', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--tag', default='样式')
    a = ap.parse_args()
    main(a.export, a.spec, a.output, a.tag)
