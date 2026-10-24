"""示例规格：给 样式规格应用.py 用。窗口号和控件名都是占位，改成你工程里的再跑。

python 样式规格应用.py --export <导出> --spec 示例/示例_样式规格.py --output <新目录> --tag 样式
控件名用 run.ps1 inspect 导出后，可在 Python 里 `[u.control_name(r) for r in u.Export(导出).window(N).controls]` 查。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mcgs_ui import *  # 色板（INK、BRAND、CARD、LINE…）、样式种类和 B/T/V/M/MOVE/SHAPE/GROUP/NEW_* 写法

DESCRIPTION = '示例：页面底板、标题、按钮和数值框统一样式'

# 可选：指定新建底板/文字/线用的模板；不写就自动挑
# TEMPLATES = {'rect': (2, '某个矩形'), 'label': (2, '某个文字'), 'line': (2, '某条线')}

SPEC = {
    2: {
        'below': [NEW_RECT('新增_页面底色', [0, 160, 1920, 1080], PAGE_BG),               # 插到最底层
                  NEW_RECT('新增_参数卡片', [16, 192, 600, 520], CARD, LINE)],
        'controls': {
            '页面标题': T([32, 200, 400, 240], 'card_title', '运行参数', align='left', **NO),  # **NO：关掉底色和边框
            '启动按钮': B([32, 460, 192, 504], 'primary'),
            '停止按钮': B([208, 460, 368, 504], 'danger'),
            '温度显示': V([200, 260, 360, 300], 'ro', align='left'),
            '分隔线': dict(op='line', color=LINE_SOFT, rect=[16, 540, 600, 540]),
        },
        'above': [NEW_TEXT('新增_温度说明', [32, 264, 180, 296], 'field', '当前温度', align='left')],
        # 'delete': ['旧装饰框'],              # 只许删没有任何引用、没有动画的矩形
        # 'replace_background': '控件0',       # 删掉第 0 层的全屏背景图（须无引用）
        # 'window_background': '#EDF1F5',
    },
}


# 可选：操作里没写 align 时的默认对齐
def text_align(wid, name, kind):
    return 'left' if kind in ('page_title', 'card_title', 'field') else None
