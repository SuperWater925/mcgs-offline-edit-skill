"""McgsStu 窗口打开/循环/退出脚本归档；只读写独立内存字节。"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sys
import struct

from mcs_window_archive import Reader, WindowArchive, write_cstring, write_count, FormatError

目录 = Path(__file__).resolve().parent


@dataclass
class 窗口事件:
    打开: str
    循环: str
    周期毫秒: int
    退出: str
    保留整数: bytes
    保留字符串: list[str]
    编译缓存: list[bytes]
    扩展: bytes
    原始字符串编码: list[bytes]
    原始计数编码: list[bytes]

    @classmethod
    def 解析(cls, 数据: bytes):
        读 = Reader(数据)
        开, 开码, _ = 读.cstring()
        循, 循码, _ = 读.cstring()
        周期 = 读.u32()
        退, 退码, _ = 读.cstring()
        保留整数 = 读.take(12)
        保留文本 = [读.cstring() for _ in range(3)]
        缓存 = [读.byte_array() for _ in range(3)]
        扩展 = 数据[读.pos:]
        if len(扩展) < 6:
            raise FormatError('窗口扩展被截断')
        return cls(开, 循, 周期, 退, 保留整数, [项[0] for 项 in 保留文本],
                   [项[0] for 项 in 缓存], 扩展,
                   [开码, 循码, 退码] + [项[1] for 项 in 保留文本], [项[1] for 项 in 缓存])

    def 序列化(self):
        def 字符串(值, 原码):
            return 原码 if Reader(原码).cstring()[0] == 值 else write_cstring(值)
        字符序列 = [self.打开, self.循环, self.退出] + self.保留字符串
        编码 = [字符串(值, 原码) for 值, 原码 in zip(字符序列, self.原始字符串编码)]
        缓存编码 = []
        for 内容, 原计数 in zip(self.编译缓存, self.原始计数编码):
            计数 = 原计数 if Reader(原计数).count() == len(内容) else write_count(len(内容))
            缓存编码.append(计数 + 内容)
        return (编码[0] + 编码[1] + struct.pack('<I', self.周期毫秒) + 编码[2]
                + self.保留整数 + b''.join(编码[3:]) + b''.join(缓存编码) + self.扩展)


def 设置窗口事件(原事件尾: bytes, 打开脚本='', 循环脚本='', 退出脚本='', 周期毫秒=100):
    """以原厂空窗口的事件尾为模板，保留扩展和未改事件，清除改动事件缓存。"""
    事件 = 窗口事件.解析(原事件尾)
    if 事件.序列化() != 原事件尾:
        raise FormatError('事件模板无法原样回环')
    if 事件.保留整数 != bytes(12) or 事件.保留字符串 != ['', '', '']:
        raise FormatError('尚未验证的旧格式事件扩展，拒绝改写')
    if not 1 <= 周期毫秒 <= 2147483647:
        raise ValueError('窗口循环周期超出有效整数范围')
    for 索引, 属性, 内容 in [(0, '打开', 打开脚本), (1, '循环', 循环脚本), (2, '退出', 退出脚本)]:
        if not isinstance(内容, str) or '\x00' in 内容:
            raise ValueError('脚本须为不含NUL的文本')
        if getattr(事件, 属性) != 内容:
            setattr(事件, 属性, 内容)
            # 原厂以CByteArray保存事件编译码。源码变化不得保留旧缓存。
            # 新建空数组Serialize写count0，需由原厂编译生成实际运行字节码。
            事件.编译缓存[索引] = b''
    事件.周期毫秒 = 周期毫秒
    结果 = 事件.序列化()
    复读 = 窗口事件.解析(结果)
    assert 复读.序列化() == 结果
    assert [复读.打开, 复读.循环, 复读.退出, 复读.周期毫秒] == [打开脚本, 循环脚本, 退出脚本, 周期毫秒]
    assert 复读.扩展 == 事件.扩展
    return 结果
