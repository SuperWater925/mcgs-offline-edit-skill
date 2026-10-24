"""McgsStu 原生界面控件工厂：读导出、改控件、建页面、出候选清单。

纯字节操作：不打开数据库、不启动厂商程序。每处改动都在内存里先做字节回环，
再写成 BLOB 和 manifest；写入工程交给 run.ps1 apply（改已有行）或
tools/新增窗口事务.ps1（新建窗口）。

主要入口：
- Export：读 run.ps1 inspect 导出（或候选导出）里的窗口、数据对象和策略；
- Templates：从导出里挑新建控件用的模板（文字、矩形、直线、数值框、字符框、按钮）；
- Page：在一个窗口里按坐标摆文字、矩形、灯、数值、按钮等；
- edit_* / new_* / apply_gates：单个控件的样式编辑；
- neutral / business_sources：确认改样式没有碰到脚本、绑定、动作；
- new_window：按同层模板窗口克隆一个新窗口；
- Candidate：把改好的 BLOB 写成 manifest 和候选导出，供预览、文字检查和写入。
颜色一律写 '#RRGGBB'，内部转成 COLORREF（BGR）。用法见 references/ui-tools.md。
"""
from pathlib import Path
import collections, copy, hashlib, json, os, re, shutil, struct, sys

sys.dont_write_bytecode = True
NATIVE = Path(__file__).resolve().parents[1] / 'scripts' / 'native'
sys.path.insert(0, str(NATIVE))
from mcs_window_archive import WindowArchive, Reader
from 原生界面样式 import CommonEnvelope, MultiState, GenericMetadata, GroupArchive, set_font, fonts
from mcs_button_control import ButtonArchive, bind_click
from mcs_input_text import LabelRecord, InputRecord
from mcs_plugin_controls import PluginControl, RecipeCore, XYCore
from 报警表原生样式 import AlarmStyle
from 窗口事件归档 import 窗口事件, 设置窗口事件
from 当前存盘浏览样式 import parse_record as parse_savedata
from 可见动画归档 import 添加可见条件, 读取可见条件
import mcgs_native_zip as nz
import mcgs_recipe_strategy as st
import 对象归档 as om


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def c(hexstr):
    r, g, b = bytes.fromhex(hexstr.lstrip('#'))
    return r | (g << 8) | (b << 16)


# ---- 设计规范色板 -------------------------------------------------------
INK, LABEL, MUTED = '#1E2B37', '#4A5A6A', '#64748B'
BRAND, BRAND_DARK, BRAND_SOFT = '#1F6FB2', '#185C94', '#E8F1FA'
PAGE_BG, CARD, LINE, LINE_SOFT, RO = '#EDF1F5', '#FFFFFF', '#D5DDE5', '#E3E8EE', '#F2F5F8'
TOOL, BTN_LINE = '#F4F6F9', '#B8C4D0'
DANGER, DANGER_LINE = '#B42318', '#E0A39C'
APPBAR, APPBAR_LINE, APPBAR_INK = '#17324D', '#24466A', '#C8D4E0'

BUTTON_KINDS = {
    'primary': dict(fill=BRAND, border=BRAND_DARK, ink='#FFFFFF', font=22),
    'secondary': dict(fill=CARD, border=BTN_LINE, ink=INK, font=22),
    'tool': dict(fill=TOOL, border=BTN_LINE, ink=INK, font=20),
    'danger': dict(fill=CARD, border=DANGER_LINE, ink=DANGER, font=22),
    'danger_tool': dict(fill=CARD, border=DANGER_LINE, ink=DANGER, font=20),
}
TEXT_KINDS = {
    'page_title': dict(ink=INK, font=30, weight=700),
    'card_title': dict(ink=INK, font=22, weight=700),
    'sub_title': dict(ink='#33475B', font=20, weight=700),
    'field': dict(ink=LABEL, font=20, weight=400),
    'muted': dict(ink=MUTED, font=18, weight=400),
    'header_label': dict(ink=MUTED, font=20, weight=400),
    'header_value': dict(ink=INK, font=22, weight=400),
    'badge': dict(ink=BRAND, font=20, weight=700),
    'kpi_label': dict(ink=LABEL, font=20, weight=400),
    'kpi_label_accent': dict(ink=BRAND_DARK, font=20, weight=400),
    'empty_state': dict(ink=MUTED, font=24, weight=400),
}
VALUE_KINDS = {
    'edit': dict(ink=INK, bg=CARD, frame=1, font=22),
    'ro': dict(ink=INK, bg=RO, frame=0, font=22),
    'ro_small': dict(ink=INK, bg=RO, frame=0, font=20),
    'ro_white': dict(ink=INK, bg=CARD, frame=0, font=20),
    'ro_header': dict(ink=INK, bg=CARD, frame=0, font=22),
    'kpi': dict(ink=INK, bg=RO, frame=0, font=36, weight=700),
    'kpi_white': dict(ink=INK, bg=CARD, frame=0, font=36, weight=700),
    'kpi_accent': dict(ink=BRAND, bg=BRAND_SOFT, frame=0, font=36, weight=700),
}


def B(rect, kind, caption=None):
    return dict(op='button', rect=rect, kind=kind, caption=caption)


def T(rect, kind, caption=None, **kw):
    # kw: align='left'|'center'；bg/border='none' 关闭原生画刷/画笔门控，或颜色值开启并着色。
    return dict(op='text', rect=rect, kind=kind, caption=caption, **kw)


def V(rect, kind, **kw):
    return dict(op='value', rect=rect, kind=kind, **kw)


def NEW_RECT(name, rect, fill, border=None, width=1):
    return dict(op='new_rect', name=name, rect=rect, fill=fill, border=border, width=width)


def NEW_TEXT(name, rect, kind, caption, **kw):
    return dict(op='new_text', name=name, rect=rect, kind=kind, caption=caption, **kw)


def NEW_LINE(name, rect, color=LINE_SOFT):
    return dict(op='new_line', name=name, rect=rect, color=color)


NAV = dict(normal_fill=TOOL, normal_border=LINE_SOFT, normal_ink='#33475B',
           active_fill=BRAND, active_border=BRAND, active_ink='#FFFFFF')
TOPNAV = dict(normal_fill=APPBAR, normal_border=APPBAR_LINE, normal_ink=APPBAR_INK,
              active_fill=BRAND, active_border=APPBAR_LINE, active_ink='#FFFFFF')

TABLE_STYLE = dict(m40=c('#E9EEF3'), m48=c('#33475B'), m50=c(INK), m58=c(LINE), m60=c(CARD), m68=c('#F8FAFC'))


# ---- 记录级编辑（全部为定长字段或经回环证明的序列化） --------------------
def common_style(record, *, rect=None, fill=None, border=None, brush_en=None, pen_en=None, pen_style=None, pen_width=None):
    cm = CommonEnvelope.parse(record)
    if rect is not None:
        cm.set_rect(list(rect))
    p = bytearray(cm.prefix)
    if fill is not None:
        struct.pack_into('<I', p, cm.brush_offset + 2 + 4, c(fill))
    if border is not None:
        struct.pack_into('<I', p, cm.pen_offset + 2 + 12, c(border))
    if brush_en is not None:
        struct.pack_into('<H', p, cm.brush_offset, int(brush_en))
    if pen_en is not None:
        struct.pack_into('<H', p, cm.pen_offset, int(pen_en))
    if pen_style is not None:
        struct.pack_into('<I', p, cm.pen_offset + 2, pen_style)
    if pen_width is not None:
        # LOGPEN：style DWORD、width POINT(x,y)、COLORREF；线宽取 x。
        struct.pack_into('<I', p, cm.pen_offset + 2 + 4, pen_width)
    cm.prefix = bytes(p)
    return cm.to_record()


def edit_button(record, rect, kind, caption=None):
    k = BUTTON_KINDS[kind]
    cm = CommonEnvelope.parse(record)
    assert not cm.animations
    record = common_style(record, fill=k['fill'], border=k['border'])
    b = ButtonArchive.parse(record)
    assert b.to_bytes() == record.payload
    w = b.metadata.properties.words
    assert w[8:12] == [1, 1, 1, 1], 'native two-state gates must already be on'
    w[1] = w[6] = c(k['fill'])
    w[2] = w[7] = c(k['border'])
    w[5] = c(k['ink'])
    b.caption_words[1] = c(k['ink'])
    b.font = set_font(b.font, height=k['font'], family='微软雅黑')
    b.metadata.properties.font = set_font(b.metadata.properties.font, height=k['font'], family='微软雅黑')
    if caption is not None:
        assert b.caption.value == b.metadata.properties.caption.value
        b.caption.value = b.metadata.properties.caption.value = caption
    if rect is not None:
        b.rect = tuple(rect)
    return b.to_record()


# 原厂实机：文字 style 与 appearance_prefix[1] 同为对齐值，0 左、1 居中、2 右（实机截图证实）。输入框 properties[3] 为水平对齐，按同一 0/1/2 取值。
ALIGN = dict(left=0, center=1)
FONT_DIR = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts'
FONT_FILES = {400: str(FONT_DIR / 'msyh.ttc'), 700: str(FONT_DIR / 'msyhbd.ttc')}


def text_width(text, height, weight):
    from PIL import ImageFont
    font = ImageFont.truetype(FONT_FILES[700 if weight >= 600 else 400], height)
    return max(font.getlength(line) for line in (text.splitlines() or ['']))


def edit_text(record, rect, kind, caption=None, align=None):
    k = TEXT_KINDS[kind]
    cm = CommonEnvelope.parse(record)
    projected = cm.project_without_animations()
    q = LabelRecord.parse(projected)
    assert q.to_bytes() == projected.payload
    if caption is not None:
        q.caption = caption
    if align is not None:
        assert q.style == q.appearance_prefix[1] and q.style in (0, 1, 2)
        q.style = q.appearance_prefix[1] = ALIGN[align]
    if rect is not None:
        rect = list(rect)
        dynamic = any(a['class_name'] == 'CAniOutput' for a in cm.animations)
        if align == 'left' and not dynamic:
            # 原厂文字左右各留约 6 像素，宽度不足直接裁掉末字（实机截图证实）。
            # 静态左对齐文字的框统一取 字宽 + 24；动态文字（PLC 名称等）长度未知，保持设计宽度。
            rect[2] = rect[0] + int(text_width(q.caption, k['font'], k['weight'])) + 24
        q.common.set_rect(rect)
    q.colour = c(k['ink'])
    q.font = set_font(q.font, height=k['font'], weight=k['weight'], family='微软雅黑')
    projected.payload = q.to_bytes()
    return cm.restore_projected(projected)


def edit_value(record, rect, kind, align=None):
    k = VALUE_KINDS[kind]
    cm = CommonEnvelope.parse(record)
    projected = cm.project_without_animations()
    q = InputRecord.parse(projected)
    assert q.to_bytes() == projected.payload
    if rect is not None:
        q.common.set_rect(list(rect))
    if align is not None:
        assert q.properties[3] in (0, 1, 2)
        q.properties[3] = ALIGN[align]
    q.properties[0], q.properties[1], q.properties[2] = c(k['ink']), c(k['bg']), k['frame']
    q.font = set_font(q.font, height=k['font'], weight=k.get('weight', 400), family='微软雅黑')
    projected.payload = q.to_bytes()
    result = cm.restore_projected(projected)
    # 原厂frame0/1/2均按common刷门控填底；门控必须已开启。
    after = CommonEnvelope.parse(result)
    assert struct.unpack_from('<H', after.prefix, after.brush_offset)[0] == 1
    return result


def edit_nav(record, s):
    m = MultiState.parse(record)
    assert m.to_record().payload == record.payload and len(m.fills) == 2 and len(m.texts) == 2
    for state, key in ((0, 'normal'), (1, 'active')):
        assert m.fills[state][0] == 0x10002
        m.fills[state][1] = c(s[key + '_fill'])
        for child in m.texts[state]:
            child.set_text_color(c(s[key + '_ink']))
    record = m.to_record()
    return common_style(record, border=s['normal_border'])


def edit_fills(record, fill, border):
    m = MultiState.parse(record)
    assert m.to_record().payload == record.payload
    for f in m.fills:
        assert f[0] == 0x10002
        f[1] = c(fill)
    return common_style(m.to_record(), border=border)


def edit_line(record, color, rect=None):
    return common_style(record, border=color, rect=rect)


def edit_shape(record, rect, fill, border, width=None):
    return common_style(record, rect=rect, fill=fill, brush_en=1, pen_en=1 if border else 0,
                        border=border, pen_width=width)


def edit_recipe(record, rect, widths, row_height):
    record = common_style(record, rect=rect)
    p = PluginControl.parse(record)
    assert p.to_record().payload == record.payload
    q = RecipeCore.parse(p.core)
    assert q.to_bytes() == p.core
    visible = {col.title: col for col in q.columns if col.values[1] == 1}
    assert set(widths) == set(visible), (sorted(widths), sorted(visible))
    for title, width in widths.items():
        visible[title].values[2] = width
    # 原厂把隐藏列宽也计入横向滚动范围（实机出现横向滚动条），隐藏列宽归零。
    for col in q.columns:
        if col.values[1] == 0:
            col.values[2] = 0
    q.fields.update(TABLE_STYLE)
    if row_height:
        q.fields['m70'] = row_height
    p.core = q.to_bytes()
    return p.to_record()


def edit_xy(record, rect, border):
    record = common_style(record, rect=rect)
    p = PluginControl.parse(record)
    assert p.to_record().payload == record.payload
    q = XYCore.parse(p.core)
    assert q.to_bytes() == p.core
    m4c = bytearray(q.tail['m4c'])
    struct.pack_into('<I', m4c, 12, c(border))
    q.tail['m4c'] = bytes(m4c)
    p.core = q.to_bytes()
    return p.to_record()


def edit_alarm(record):
    """只改 8 个已证配色字段；字体、行高、状态色和过滤/列定义保持原字节。"""
    p = PluginControl.parse(record)
    assert p.to_record().payload == record.payload
    style = AlarmStyle(p.core)
    raw = bytearray(p.core)
    colors = dict(title_background=TOOL, title_text=INK, odd_background=CARD, even_background='#F8FAFC',
                  focus_background=BRAND, focus_text='#FFFFFF', focus_border=LINE_SOFT, grid_color=LINE_SOFT)
    for name, value in colors.items():
        pos, n = style.fields[name]
        assert n == 4
        struct.pack_into('<I', raw, pos, c(value))
    p.core = bytes(raw)
    return p.to_record()


SAVEDATA_STYLE = dict(m240=c('#E9EEF3'), m268=c(LINE), m278=c('#F8FAFC'))


def edit_savedata(record, rect):
    # 原生存盘浏览另存一份内部表格矩形 m2a8，必须随外框同比例变换。
    old = CommonEnvelope.parse(record).rect
    q = parse_savedata(record)
    q.affine_inner_rect(old, rect)
    q.set(**SAVEDATA_STYLE)
    record = q.apply_to_record(record)
    return common_style(record, rect=rect)


def new_rect(template, name, rect, fill, border, width=1):
    cm = CommonEnvelope.parse(copy.deepcopy(template))
    assert not cm.animations and cm.record.type_id == 0x5004 and not cm.content
    cm.name.value = name
    record = cm.to_record()
    return edit_shape(record, rect, fill, border, width)


def new_text(template, name, rect, kind, caption, align=None):
    cm = CommonEnvelope.parse(copy.deepcopy(template))
    assert not cm.animations
    q = LabelRecord.parse(cm.record)
    assert q.to_bytes() == cm.record.payload
    q.common.name = name
    record = copy.deepcopy(cm.record)
    record.payload = q.to_bytes()
    return edit_text(record, rect, kind, caption, align)


def new_line(template, name, rect, color):
    cm = CommonEnvelope.parse(copy.deepcopy(template))
    assert not cm.animations and cm.record.type_id == 0x5002
    cm.name.value = name
    return common_style(cm.to_record(), rect=rect, border=color)



def apply_gates(record, bg=None, border=None):
    """原生 common 画刷/画笔门控：'none' 关闭；颜色值开启并着色；None 保持。"""
    kw = {}
    if bg == 'none':
        kw['brush_en'] = 0
    elif bg:
        kw.update(brush_en=1, fill=bg)
    if border == 'none':
        kw['pen_en'] = 0
    elif border:
        kw.update(pen_en=1, border=border, pen_width=1)
    return common_style(record, **kw) if kw else record


def edit_multi(record, rect=None, fills=None, ink=None, border=None):
    m = MultiState.parse(record)
    assert m.to_record().payload == record.payload
    if rect is not None:
        m.resize(list(rect))
    if fills is not None:
        for f in m.fills:
            assert f[0] == 0x10002
        for state, f in enumerate(m.fills):
            f[1] = c(fills[min(state, len(fills) - 1)])
    if ink is not None:
        for children in m.texts:
            for child in children:
                child.set_text_color(c(ink))
    record = m.to_record()
    return common_style(record, border=border) if border else record


def edit_any(record, s):
    """按 op 编辑单个控件（顶层或组内子件）。"""
    op = s['op']
    if op == 'text':
        out = edit_text(record, s.get('rect'), s['kind'], s.get('caption'), s.get('align'))
        return apply_gates(out, s.get('bg'), s.get('border'))
    if op == 'value':
        return edit_value(record, s.get('rect'), s['kind'], s.get('align'))
    if op == 'button':
        return edit_button(record, s.get('rect'), s['kind'], s.get('caption'))
    if op == 'shape':
        return edit_shape(record, s.get('rect'), s['fill'], s['border'], s.get('width'))
    if op == 'multi':
        return edit_multi(record, s.get('rect'), s.get('fills'), s.get('ink'), s.get('border'))
    if op == 'move':
        return common_style(record, rect=s['rect'])
    if op == 'group':
        g = GroupArchive.parse(record)
        assert g.to_record().payload == record.payload
        seen = set()
        for i, ch in enumerate(g.children):
            name = CommonEnvelope.parse(ch).name.value
            if name in s['children']:
                g.children[i] = edit_any(ch, s['children'][name])
                seen.add(name)
        assert seen == set(s['children']), ('group child missing', set(s['children']) - seen)
        if s.get('rect'):
            g.common.set_rect(list(s['rect']))
        return g.to_record()
    raise ValueError(op)


# ---- 业务不变量：去掉允许改的样式字段后，其余字节必须完全相同 -------------
def anim_bytes(cm):
    return cm.prefix[cm.animation_start:cm.animation_end]


def neutral(record, renamed=False):
    t = record.type_id
    cm = CommonEnvelope.parse(record)
    p = bytearray(cm.prefix)
    struct.pack_into('<4i', p, cm.rect_offset, 0, 0, 0, 0)
    struct.pack_into('<H4I', p, cm.pen_offset, 0, 0, 0, 0, 0)
    struct.pack_into('<H3I', p, cm.brush_offset, 0, 0, 0, 0)
    cm.prefix = bytes(p)
    record = cm.to_record()
    if t == 0x5027:
        b = ButtonArchive.parse(record)
        for i in (1, 2, 5, 6, 7):
            b.metadata.properties.words[i] = 0
        b.caption_words[1] = 0
        b.font = b.metadata.properties.font = b''
        if renamed:
            b.caption.value = b.metadata.properties.caption.value = ''
        return b.to_bytes()
    if t == 0x5025:
        pr = cm.project_without_animations()
        q = InputRecord.parse(pr)
        q.properties[0] = q.properties[1] = q.properties[2] = q.properties[3] = 0
        q.font = b''
        return q.to_bytes() + anim_bytes(cm)
    if t == 0x5008:
        pr = cm.project_without_animations()
        q = LabelRecord.parse(pr)
        q.colour = 0
        q.style = q.appearance_prefix[1] = 0
        q.font = b''
        if renamed:
            q.caption = ''
        return q.to_bytes() + anim_bytes(cm)
    if t == 0x5033:
        q = parse_savedata(record)
        q.set(m2a8=(0, 0, 0, 0), **{k: 0 for k in SAVEDATA_STYLE})
        return q.apply_to_record(record).payload
    if t == 0x503a:
        g = GroupArchive.parse(record)
        parts = [neutral(ch) for ch in g.children]
        g.children = []
        return g.to_record().payload + b'|'.join(parts)
    if t in (0x5028, 0x502a):
        m = MultiState.parse(record)
        for f in m.fills:
            f[1] = 0
        for st_ in m.texts:
            for ch in st_:
                ch.set_text_color(0)
        return m.to_record().payload
    if t == 0x503d:
        pc = PluginControl.parse(record)
        if 'DrawRecipe' in pc.path:
            q = RecipeCore.parse(pc.core)
            for col in q.columns:
                col.values[2] = 0
            for k in list(TABLE_STYLE) + ['m70']:
                q.fields[k] = 0
            pc.core = q.to_bytes()
        elif 'XYPicture' in pc.path:
            q = XYCore.parse(pc.core)
            q.tail['m4c'] = q.tail['m4c'][:12] + bytes(4)
            pc.core = q.to_bytes()
        elif 'AlarmTableView' in pc.path:
            st_ = AlarmStyle(pc.core)
            raw = bytearray(pc.core)
            for name in ('title_background', 'title_text', 'odd_background', 'even_background',
                         'focus_background', 'focus_text', 'focus_border', 'grid_color'):
                pos, n = st_.fields[name]
                raw[pos:pos + n] = bytes(n)
            pc.core = bytes(raw)
        return pc.to_record().payload
    return record.payload


def business_sources(window):
    """All source text / expressions reachable in a window archive."""
    out = []
    ev = 窗口事件.解析(window.settings().event_tail)
    out += [('window_event', ev.打开), ('window_event', ev.循环), ('window_event', ev.退出)]
    for rec in window.controls:
        out += control_sources(rec)
    return out


def control_sources(rec, prefix=''):
    out = []
    if True:
        cm = CommonEnvelope.parse(rec)
        name = prefix + cm.name.value
        out.append((name + ':anim', anim_bytes(cm).hex()))
        if rec.type_id == 0x503a:
            for ch in GroupArchive.parse(rec).children:
                out += control_sources(ch, name + '/')
        try:
            for e in GenericMetadata.parse(cm.metadata.value).events:
                out.append((name + ':event', e.source.value))
        except Exception:
            pass
        if rec.type_id == 0x5027:
            b = ButtonArchive.parse(cm.project_without_animations())
            out += [(name + ':release', b.release_script.value), (name + ':enabled', b.enabled_expression.value),
                    (name + ':press', b.metadata.properties.press_script.value)]
        elif rec.type_id == 0x5025:
            q = InputRecord.parse(cm.project_without_animations())
            out += [(name + ':var', q.variable), (name + ':enabled', q.enabled_expression)]
        elif rec.type_id in (0x5028, 0x502a):
            out.append((name + ':tail', MultiState.parse(rec).tail.hex()))
        elif rec.type_id == 0x503d:
            pc = PluginControl.parse(rec if not cm.animations else cm.project_without_animations())
            if 'DrawRecipe' in pc.path:
                q = RecipeCore.parse(pc.core)
                out += [(name + ':group', q.group), (name + ':visible', q.fields['visible_expression'])]
                out += [(name + ':col', f'{col.binding}|{col.title}|{col.values[0]}|{col.values[1]}|{col.values[3:]}') for col in q.columns]
    return out


def strategy_text(export):
    """All strategy source text (for reference checks before deletion)."""
    ix = json.loads((export / 'index.json').read_text('utf-8-sig'))
    row = next(r for r in ix['rows'] if r['table'] == 'Stgy' and str(r['row_key']) == '0')
    raw = (export / row['lbObjects']['file']).read_bytes()
    nodes = st.parse_strategy_array(nz.unpack(raw))
    texts = []
    for node in nodes:
        try:
            texts.append(st.single_program_action(node).fields['source'])
        except Exception:
            texts.append(repr(node.fields))
    return '\n'.join(texts)


TEXT_KINDS.update(
    dialog_title=dict(ink='#FFFFFF', font=28, weight=700),
    device_label=dict(ink=LABEL, font=20, weight=400),
    device_value=dict(ink=INK, font=22, weight=400),
    device_title=dict(ink=INK, font=24, weight=700),
    indicator=dict(ink='#33475B', font=20, weight=400),
    status_cell=dict(ink=INK, font=20, weight=400),
)
NAVY = APPBAR
NO = dict(bg='none', border='none')


def SH(rect, dx, dy):
    return [rect[0] + dx, rect[1] + dy, rect[2] + dx, rect[3] + dy]


def M(rect=None, **kw):
    return dict(op='multi', rect=rect, **kw)


def MOVE(rect):
    return dict(op='move', rect=rect)


def SHAPE(rect, fill=CARD, border=LINE, width=1):
    return dict(op='shape', rect=rect, fill=fill, border=border, width=width)


def GROUP(rect, children):
    return dict(op='group', rect=rect, children=children)



# ---- 页面构建（Page）用到的补充配色与样式种类 ------------------------------
FAINT, BRAND_LINE = '#94A3B8', '#B9D3EC'
OK_INK, OK_BG, OK_LINE, ON, OFF, SEG_OFF = '#15803D', '#DCFCE7', '#86EFAC', '#16A34A', '#CBD5E1', '#DCE4EC'
AMBER = '#B45309'

TEXT_KINDS.update(
    t_title=dict(ink=INK, font=22, weight=700), t_label=dict(ink=MUTED, font=18, weight=400),
    t_label_brand=dict(ink=BRAND_DARK, font=18, weight=400), t_label16=dict(ink=MUTED, font=16, weight=400),
    t_label16_brand=dict(ink=BRAND_DARK, font=16, weight=400), t_field=dict(ink=LABEL, font=20, weight=400),
    t_field_brand=dict(ink=BRAND_DARK, font=20, weight=400), t_unit=dict(ink=MUTED, font=18, weight=400),
    t_unit20=dict(ink=MUTED, font=20, weight=400), t_arrow=dict(ink=FAINT, font=28, weight=400),
    t_name=dict(ink=INK, font=20, weight=400), t_head=dict(ink=MUTED, font=18, weight=400),
    t_temp=dict(ink=FAINT, font=14, weight=700), t_foot=dict(ink=FAINT, font=15, weight=400),
    t_empty=dict(ink=MUTED, font=20, weight=400),
    s_idle=dict(ink=MUTED, font=24, weight=700), s_wait=dict(ink=AMBER, font=24, weight=700),
    s_run=dict(ink=OK_INK, font=24, weight=700), s_done=dict(ink=BRAND, font=24, weight=700),
    s_bad=dict(ink=DANGER, font=24, weight=700),
    chip_on=dict(ink=OK_INK, font=18, weight=400), chip_off=dict(ink=MUTED, font=18, weight=400),
    lamp_on=dict(ink=ON, font=28, weight=400), lamp_off=dict(ink=OFF, font=28, weight=400),
)
VALUE_KINDS.update(
    v_pos=dict(ink=BRAND, bg=BRAND_SOFT, frame=0, font=40, weight=700),
    v_big=dict(ink=INK, bg=RO, frame=0, font=36, weight=700),
    v_mid=dict(ink=INK, bg=RO, frame=0, font=32, weight=700),
    v_mid_brand=dict(ink=BRAND, bg=BRAND_SOFT, frame=0, font=32, weight=700),
    v_seg=dict(ink=BRAND, bg=BRAND_SOFT, frame=0, font=36, weight=700),
    v_kpi=dict(ink=INK, bg=CARD, frame=0, font=26, weight=700),
    v_vac=dict(ink=INK, bg=RO, frame=0, font=30, weight=700),
    v_freq=dict(ink=INK, bg=RO, frame=0, font=24, weight=700),
    v_temp=dict(ink=INK, bg=RO, frame=0, font=16, weight=700),
    v_step=dict(ink=INK, bg=CARD, frame=0, font=32, weight=700),
    v_next=dict(ink=LABEL, bg=CARD, frame=0, font=26, weight=400),
    v_title=dict(ink=INK, bg=CARD, frame=0, font=22, weight=700),
    n_soft=dict(ink=MUTED, bg=BRAND_SOFT, frame=0, font=18, weight=400),
    n_soft16=dict(ink=MUTED, bg=BRAND_SOFT, frame=0, font=16, weight=400),
    n_ro=dict(ink=MUTED, bg=RO, frame=0, font=16, weight=400),
)
BUTTON_KINDS.update(link=dict(fill=CARD, border=LINE, ink=BRAND_DARK, font=18))

def set_decimals(record, places):
    """小数位：common 元数据 +50 与外观 +36 两处 u32，原厂成对保存。"""
    cm = CommonEnvelope.parse(record)
    projected = cm.project_without_animations()
    q = InputRecord.parse(projected)
    a, b = bytearray(q.common.metadata), bytearray(q.appearance)
    assert struct.unpack_from('<I', a, 50)[0] == struct.unpack_from('<I', b, 36)[0]
    struct.pack_into('<I', a, 50, places)
    struct.pack_into('<I', b, 36, places)
    q.common.metadata, q.appearance = bytes(a), bytes(b)
    projected.payload = q.to_bytes()
    return cm.restore_projected(projected)


def bind_display(template, name, rect, obj, align):
    """按恒禁用显示框模板（使能 '0'、变灰样式 1、无缓存）新建一个显示框并绑定数据对象 obj。"""
    cm = CommonEnvelope.parse(copy.deepcopy(template))
    assert not cm.animations
    q = InputRecord.parse(cm.record)
    assert q.to_bytes() == cm.record.payload
    assert q.expression_cache == b'' and q.enabled_expression == '0' and q.disabled_style == 1
    q.common.name = name
    q.variable = obj.name.value
    q.properties[5] = obj.id
    q.properties[6] = {1: 1, 2: 2, 3: 3}[obj.kind]
    q.set_decimal_format()
    record = copy.deepcopy(cm.record)
    record.payload = q.to_bytes()
    out = edit_value(record, rect, 'ro_small', align)
    back = InputRecord.parse(CommonEnvelope.parse(out).project_without_animations())
    assert (back.variable, back.variable_id, back.variable_type) == (obj.name.value, obj.id, obj.kind)
    return out


def badge(template, name, rect, kind, caption, fill, line, expression):
    record = new_text(template, name, rect, kind, caption, 'center')
    record = apply_gates(record, fill, line)
    record = 添加可见条件(record, expression)
    v = 读取可见条件(record)
    assert v['expression'] == expression and v['nonzero_visible']
    return record


class Page:
    """在一个窗口里按坐标摆控件。tpl 是 Templates.pick() 的结果，objs 是 {对象名: 数据对象}。
    self.controls 按添加顺序就是绘制顺序（后加的在上层）；self.bound 记录绑定过的变量。"""
    def __init__(self, tpl, objs):
        self.tpl, self.objs, self.controls, self.bound = tpl, objs, [], set()

    def add(self, rec, visible=None):
        if visible:
            rec = 添加可见条件(rec, visible)
            v = 读取可见条件(rec)
            assert v['expression'] == visible and v['nonzero_visible']
        self.controls.append(rec)

    def text(self, name, x, cy, caption, kind, h=32, visible=None):
        """左对齐文字，文字从 x 开始（原厂左右各留约 6 像素，框宽 = 字宽 + 24）。"""
        self.add(new_text(self.tpl['label'], name, [x - 6, cy - h // 2, x + 200, cy + h // 2], kind, caption, 'left'), visible)

    def text_right(self, name, right, cy, caption, kind, h=32, visible=None):
        k = TEXT_KINDS[kind]
        tw = int(text_width(caption, k['font'], k['weight']))
        self.text(name, right - tw - 4, cy, caption, kind, h, visible)

    def center(self, name, rect, caption, kind, visible=None):
        self.add(new_text(self.tpl['label'], name, list(rect), kind, caption, 'center'), visible)

    def rect(self, name, rect, fill, border=None, visible=None):
        self.add(new_rect(self.tpl['rect'], name, list(rect), fill, border, 1), visible)

    def line(self, name, x1, y1, x2, y2):
        self.add(new_line(self.tpl['line'], name, [x1, y1, x2, y2], LINE_SOFT))

    def card(self, name, rect, title=None):
        self.rect(f'{name}卡片', rect, CARD, LINE)
        if title:
            self.text(f'{name}标题', rect[0] + 16, rect[1] + 28, title, 't_title')

    def lamp(self, name, cx, cy, expression):
        box = [cx - 18, cy - 18, cx + 18, cy + 18]
        self.center(name + '_灭', box, '●', 'lamp_off')
        self.center(name + '_亮', box, '●', 'lamp_on', expression)

    def value(self, name, rect, var, kind, decimals, align='left', visible=None):
        obj = self.objs[var]
        assert obj.kind in (1, 2), var
        tpl = self.tpl['num']
        rec = bind_display(tpl, name, list(rect), obj, align)
        rec = edit_value(rec, list(rect), kind, align)
        self.add(set_decimals(rec, decimals), visible)
        self.bound.add(var)

    def value_unit(self, name, rect, var, kind, decimals, unit, unit_kind='t_unit', cy=None):
        """数值框 + 紧随的单位：单位文字框从数值框右边 +2 开始，不相交。"""
        self.value(name, rect, var, kind, decimals)
        self.text(name + '单位', rect[2] + 8, cy if cy is not None else (rect[1] + rect[3]) // 2 + 4, unit, unit_kind)

    def prefixed(self, name, x, cy, caption, kind, rect_w, h, var, vkind, decimals):
        """前缀文字 + 数值：数值框从前缀文字框右边 +2 开始。返回数值框右边。"""
        k = TEXT_KINDS[kind]
        tw = int(text_width(caption, k['font'], k['weight']))
        self.text(name + '说明', x, cy, caption, kind, h)
        vx = x - 6 + tw + 24 + 2
        self.value(name, (vx, cy - h // 2 + 2, vx + rect_w, cy + h // 2 - 2), var, vkind, decimals)
        return vx + rect_w

    def string(self, name, rect, var, kind):
        obj = self.objs[var]
        assert obj.kind == 3, var
        rec = bind_display(self.tpl['str'], name, list(rect), obj, 'left')
        self.add(edit_value(rec, list(rect), kind, 'left'))
        self.bound.add(var)

    def chip(self, name, rect, caption, var):
        """开关小标签：变量为 1 时显示绿底一枚、为 0 时显示白底一枚，两枚同位叠放。"""
        for state, (kind, fill, line) in ((1, ('chip_on', OK_BG, OK_LINE)), (0, ('chip_off', CARD, LINE))):
            rec = new_text(self.tpl['label'], f'{name}_{"选" if state else "未选"}', list(rect), kind, '● ' + caption, 'center')
            self.add(apply_gates(rec, fill, line), f'{var} = {state}')
        self.bound.add(var)

    def segments(self, name, rect, n, fill, condition):
        x0, y0, x1, y1 = rect
        w = (x1 - x0 - (n - 1) * 3) / n
        for k in range(n):
            xa = round(x0 + k * (w + 3))
            box = [xa, y0, round(xa + w), y1]
            self.rect(f'{name}_底{k + 1}', box, SEG_OFF)
            self.rect(f'{name}_亮{k + 1}', box, fill, None, condition(k + 1))

    def button(self, name, rect, caption, script):
        b = ButtonArchive.parse(copy.deepcopy(self.tpl['button']))
        b.name.value = name
        rec = edit_button(b.to_record(), list(rect), 'link', caption)
        self.add(bind_click(rec, script))


# ---- 导出读取、模板、新窗口与候选清单 -------------------------------------------
KEY_COLUMNS = {'System': 'strName', 'Stgy': 'iStgyID', 'Trigger': 'iID', 'WndUser': 'iID', 'WndControl': 'iID'}


def control_name(record):
    return CommonEnvelope.parse(record).name.value


class Export:
    """run.ps1 inspect 导出或候选导出的只读视图；每个 BLOB 读取时都核对 SHA256。"""

    def __init__(self, path):
        self.path = Path(path)
        index = next((self.path / n for n in ('index.json', '完整结构索引.json') if (self.path / n).is_file()), None)
        if index is None:
            raise FileNotFoundError(f'{self.path} 里没有 index.json')
        self.index = json.loads(index.read_text('utf-8-sig'))
        fp = self.path / 'fingerprints.json'
        self.fingerprints = json.loads(fp.read_text('utf-8-sig')) if fp.is_file() else None
        self.sha256 = self.index['sha256']
        self.rows = {(r['table'], str(r['row_key'])): r for r in self.index['rows']}

    def raw(self, table, key, field):
        info = self.rows[table, str(key)][field]
        data = (self.path / info['file']).read_bytes()
        assert sha(data) == info['sha256'], (table, key, field)
        return data

    def before(self, table, key, field):
        """写入清单要的字段前指纹（取自 fingerprints.json）。"""
        if self.fingerprints is None:
            raise FileNotFoundError('导出里没有 fingerprints.json，不能生成写入清单')
        return self.fingerprints['fingerprints'][table][str(key)][field]

    def window_ids(self):
        return sorted(int(k) for t, k in self.rows if t == 'WndUser')

    def window(self, wid):
        raw = self.raw('WndUser', wid, 'lbObjects')
        w = WindowArchive.parse(raw)
        assert w.to_bytes() == raw, ('window roundtrip', wid)
        return w

    def window_by_name(self, name):
        hits = [wid for wid in self.window_ids() if self.window(wid).settings().properties[1].value == name]
        assert len(hits) == 1, (name, hits)
        return hits[0]

    def objects(self):
        """返回 (version, 对象列表, 是否 MCGSZIPE 压缩)。"""
        raw = self.raw('System', 'ObjData', 'lbContext')
        zipped = raw.startswith(nz.MARKER)
        version, objs = om.parse(nz.unpack(raw) if zipped else raw)
        om.validate_objects(objs)
        return version, objs, zipped

    def objects_by_name(self):
        return {o.name.value: o for o in self.objects()[1]}

    def strategy_sources(self):
        """{策略名: 源码}，只含单脚本策略。"""
        nodes = st.parse_strategy_array(nz.unpack(self.raw('Stgy', '0', 'lbObjects')))
        out = {}
        for n in nodes:
            try:
                out[n.fields['name']] = st.single_program_action(n).fields['source']
            except Exception:
                pass
        return out


def find(window, name):
    hits = [i for i, r in enumerate(window.controls) if control_name(r) == name]
    assert len(hits) == 1, (name, hits)
    return hits[0]


class Templates:
    """新建控件要用工程里已有的同类控件做模板（保证原生字段齐全）。

    pick() 自动挑：没有动画的文字（画刷/画笔门控关闭）、矩形、直线；恒禁用显示框（数值、字符各一个）；
    没有动画的标准按钮。挑不到或想指定时，用 named={'label': (窗口号, 控件名), ...} 指定。
    """
    KINDS = ('label', 'rect', 'line', 'num', 'str', 'button')

    @staticmethod
    def _ok(kind, rec, objs_by_id):
        cm = CommonEnvelope.parse(rec)
        if cm.animations:
            return False
        gate = lambda off: struct.unpack_from('<H', cm.prefix, off)[0]
        if kind == 'label':
            return rec.type_id == 0x5008 and gate(cm.brush_offset) == 0 and gate(cm.pen_offset) == 0
        if kind == 'rect':
            return rec.type_id == 0x5004 and not cm.content
        if kind == 'line':
            return rec.type_id == 0x5002
        if kind in ('num', 'str'):
            if rec.type_id != 0x5025:
                return False
            q = InputRecord.parse(cm.record)
            if not (q.expression_cache == b'' and q.enabled_expression == '0' and q.disabled_style == 1):
                return False
            return q.properties[6] in ((1, 2) if kind == 'num' else (3,))
        if kind == 'button':
            if rec.type_id != 0x5027:
                return False
            w = ButtonArchive.parse(rec).metadata.properties.words
            return w[8:12] == [1, 1, 1, 1]
        return False

    @classmethod
    def pick(cls, export, named=None, kinds=KINDS):
        named = dict(named or {})
        out, source = {}, {}
        for kind in kinds:
            if kind in named:
                wid, name = named[kind]
                w = export.window(wid)
                out[kind] = copy.deepcopy(w.controls[find(w, name)])
                source[kind] = (wid, name)
        for wid in export.window_ids():
            if all(k in out for k in kinds):
                break
            w = export.window(wid)
            for rec in w.controls:
                for kind in kinds:
                    if kind not in out:
                        try:
                            ok = cls._ok(kind, rec, None)
                        except Exception:
                            ok = False
                        if ok:
                            out[kind] = copy.deepcopy(rec)
                            source[kind] = (wid, control_name(rec))
        missing = [k for k in kinds if k not in out]
        if missing:
            raise LookupError(f'工程里找不到可用的模板：{missing}；请用 named 指定')
        out['_source'] = source
        return out


def new_window(template_window, window_id, name, controls, opening=None, loop=None, leaving=None, period_ms=None):
    """克隆同层模板窗口的设置（尺寸、背景、公共窗口槽都照搬），换 ID、名称、控件和事件脚本。

    事件参数为 None 时沿用模板的脚本和周期。公共窗口槽（底板/侧栏）不在这里改：
    要别的公共层就换一个已经带那些公共层的模板窗口。
    """
    s = template_window.settings()
    ev = 窗口事件.解析(s.event_tail)
    ns = s.clone(window_id, name)
    ns.event_tail = 设置窗口事件(s.event_tail,
                              ev.打开 if opening is None else opening,
                              ev.循环 if loop is None else loop,
                              ev.退出 if leaving is None else leaving,
                              ev.周期毫秒 if period_ms is None else period_ms)
    names = [control_name(r) for r in controls]
    dup = sorted({n for n in names if names.count(n) > 1})
    assert not dup, ('重复控件名', dup)
    w = WindowArchive(template_window.prefix, list(controls), ns.to_bytes(), b'')
    data = w.to_bytes()
    back = WindowArchive.parse(data)
    assert back.to_bytes() == data
    props = back.settings().properties
    assert (props[0].value, props[1].value) == (window_id, name)
    assert 窗口事件.解析(back.settings().event_tail).扩展 == ev.扩展
    return back


def references_to(window_name, control, sources):
    """在若干源码文本里找“窗口名.控件名”引用（前后加字界，不把说明文字当引用）。"""
    pattern = r'(?<![\w\u3400-\u9fff])' + re.escape(window_name) + r'\.' + re.escape(control) + r'(?![\w\u3400-\u9fff])'
    return [s for s in sources if re.search(pattern, s)]


def block_balance_ok(source):
    """MCGS 脚本块平衡：只数以 Then 结尾的 If 行（单行 If … Then 语句不需要 EndIf）。"""
    lines = [l.strip() for l in source.replace('\r\n', '\n').split('\n')]
    opened = sum(1 for l in lines if l.startswith('If ') and l.endswith('Then'))
    return opened == lines.count('EndIf')


class Candidate:
    """收集改动，写出 manifest.json、各 BLOB 和“候选导出”（可直接给离线预览、文字检查用）。

    只有 update 时，manifest 交给 run.ps1 apply；含新建窗口（insert）时交给 tools/新增窗口事务.ps1。
    """

    def __init__(self, export, out_dir, description):
        self.export, self.out, self.description = export, Path(out_dir), description
        self.out.mkdir(parents=True, exist_ok=False)
        self.ops = []

    def update(self, table, key, field, data, blob_name):
        assert (table, str(key)) in self.export.rows, ('行不存在', table, key)
        assert not any(o['table'] == table and str(o['key']) == str(key) for o in self.ops), ('同一行重复', table, key)
        (self.out / blob_name).write_bytes(data)
        self.ops.append(dict(action='update', table=table, key_column=KEY_COLUMNS[table],
                             key=int(key) if str(key).lstrip('-').isdigit() and table != 'System' else str(key),
                             before={field: self.export.before(table, key, field)},
                             values={field: dict(blob=blob_name, sha256=sha(data))}))

    def update_window(self, wid, window, blob_name=None):
        data = window.to_bytes()
        assert WindowArchive.parse(data).to_bytes() == data
        self.update('WndUser', wid, 'lbObjects', data, blob_name or f'WndUser_{wid}.bin')

    def insert_window(self, window, note='自定义窗口，运行时可见', blob_name=None):
        props = window.settings().properties
        wid, name = props[0].value, props[1].value
        assert ('WndUser', str(wid)) not in self.export.rows, ('窗口号已存在', wid)
        names = {self.export.window(i).settings().properties[1].value for i in self.export.window_ids()}
        assert name not in names, ('窗口名已存在', name)
        data = window.to_bytes()
        blob_name = blob_name or f'WndUser_{wid}_新增.bin'
        (self.out / blob_name).write_bytes(data)
        self.ops.append(dict(action='insert', table='WndUser', key_column='iID', key=wid,
                             values=dict(iID=wid, strName=name, strNote=note, lbObjects=dict(blob=blob_name, sha256=sha(data)),
                                         iDeleteFlag=0, iCompileFlag=0)))

    def write(self):
        assert self.ops, '没有改动'
        tables = {(o['table'], str(o['key'])) for o in self.ops if o['action'] == 'update'}
        assert (('Stgy', '0') in tables) == (('System', 'StgyAndTrigger') in tables), '两份策略容器必须一起改'
        manifest = dict(input_sha256=self.export.sha256, description=self.description, operations=self.ops)
        mp = self.out / 'manifest.json'
        mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', 'utf-8')
        cand = self.out / '候选导出'
        shutil.copytree(self.export.path, cand)
        cix = copy.deepcopy(self.export.index)
        for op in self.ops:
            field = next(iter(op['values'])) if op['action'] == 'update' else 'lbObjects'
            info = op['values'][field]
            shutil.copyfile(self.out / info['blob'], cand / info['blob'])
            entry = dict(file=info['blob'], bytes=(self.out / info['blob']).stat().st_size, sha256=info['sha256'])
            if op['action'] == 'update':
                row = next(r for r in cix['rows'] if r['table'] == op['table'] and str(r['row_key']) == str(op['key']))
                row[field] = entry
            else:
                v = op['values']
                cix['rows'].append(dict(table='WndUser', row_key=str(v['iID']), iID=v['iID'], strName=v['strName'],
                                        strNote=v['strNote'], lbObjects=entry, iDeleteFlag=0, iCompileFlag=0))
        cix.update(input='候选（内存生成，不是 MCS 实际复读）', candidate_not_database_reread=True)
        for name in ('index.json', '完整结构索引.json'):
            (cand / name).write_text(json.dumps(cix, ensure_ascii=False, indent=1) + '\n', 'utf-8')
        return dict(manifest=str(mp), manifest_sha256=sha(mp.read_bytes()), candidate_export=str(cand),
                    operations=[(o['action'], o['table'], o['key']) for o in self.ops])
