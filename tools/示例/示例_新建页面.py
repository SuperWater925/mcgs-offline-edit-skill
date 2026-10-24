"""示例：克隆一个同层窗口，摆一张卡片、文字、数值、灯和按钮，作为新窗口写进候选。

用法：python 示例_新建页面.py <导出> <新输出目录> <模板窗口号> <新窗口号> <新窗口名> <数值对象名>
- 模板窗口：选一个已经带好底板/侧栏（公共窗口）的同层窗口，新窗口照搬它的尺寸、背景和公共层；
- 数值对象名：工程里已有的数值型数据对象（类型 1 或 2）。
写入用 tools/新增窗口事务.ps1（含新建窗口，不能用 run.ps1 apply）。新窗口还要在切换窗口的脚本或按钮里接上，
原厂编译后才进入采集表。
"""
from pathlib import Path
import json, sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mcgs_ui as u


def main(export_dir, out_dir, template_wid, new_wid, new_name, number_object):
    exp = u.Export(export_dir)
    objs = exp.objects_by_name()
    assert number_object in objs and objs[number_object].kind in (1, 2), ('不是数值型对象', number_object)
    tpl = u.Templates.pick(exp)
    pg = u.Page(tpl, objs)
    x0, y0, x1, y1 = 300, 200, 900, 520
    pg.card('新增_示例', (x0, y0, x1, y1), '示例卡片')                         # 白底卡片 + 标题
    pg.text('新增_示例说明', x0 + 16, y0 + 80, '当前值', 't_label')              # 左对齐文字，框宽自动取字宽 + 24
    pg.value_unit('新增_示例数值', (x0 + 16, y0 + 100, x0 + 200, y0 + 144), number_object, 'v_mid', 1, '℃')
    pg.lamp('新增_示例灯', x0 + 300, y0 + 122, f'{number_object} > 0')           # 灭灯 + 条件成立时显示的亮灯
    pg.button('新增_示例按钮', (x0 + 16, y1 - 64, x0 + 176, y1 - 20), '返回', '')  # 松开脚本留空，按需填写
    new = u.new_window(exp.window(template_wid), new_wid, new_name, pg.controls)
    c = u.Candidate(exp, out_dir, f'新建窗口 {new_wid} {new_name}')
    c.insert_window(new)
    info = c.write()
    print(json.dumps(info, ensure_ascii=False, indent=1))
    print('\n预览：python 离线预览.py --export-dir "%s" --output <新目录> --windows %d' % (info['candidate_export'], new_wid))
    print('写入：pwsh -File 新增窗口事务.ps1 -输入快照 <快照.MCS> -事务清单 "%s" -预期清单哈希 %s -输出工程 <新.MCS> -报告路径 <报告.json> -Commit'
          % (info['manifest'], info['manifest_sha256']))


if __name__ == '__main__':
    a = sys.argv[1:]
    main(a[0], a[1], int(a[2]), int(a[3]), a[4], a[5])
