"""已实证的ObjData 16.0无报警扩展字段归档。

记录的未知数值属性保持原值；报警扩展等未解结构立即拒绝。
此模块不读写MCS数据库，也不扫描字符串候选猜测记录边界。
"""
from dataclasses import dataclass
import struct


class 结构未支持(ValueError):
    pass


class 游标:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def read(self, n):
        if n < 0 or self.pos + n > len(self.data):
            raise 结构未支持(f"归档越界：offset={self.pos}, size={n}")
        out = self.data[self.pos:self.pos+n]
        self.pos += n
        return out

    def u32(self):
        return struct.unpack("<I", self.read(4))[0]

    def string(self):
        start = self.pos
        first = self.read(1)[0]
        unicode_flag = False
        if first == 255:
            word = struct.unpack("<H", self.read(2))[0]
            if word == 65534:
                unicode_flag = True
                first = self.read(1)[0]
                word = struct.unpack("<H", self.read(2))[0] if first == 255 else first
            length = self.u32() if word == 65535 else word
        else:
            length = first
        if length > 2_000_000:
            raise 结构未支持(f"字符串长度不可信：offset={start}, length={length}")
        raw = self.read(length * (2 if unicode_flag else 1))
        text = raw.decode("utf-16le", errors="surrogatepass") if unicode_flag else raw.decode("cp936")
        return 字串(text, self.data[start:self.pos], unicode_flag)


@dataclass
class 字串:
    value: str
    original: bytes
    unicode: bool

    def encode(self):
        # 未修改字符串保留其原厂编码长度形式；新增/修改统一使用原厂样例Unicode形式。
        probe = 游标(self.original)
        if probe.string().value == self.value:
            return self.original
        return encode_string(self.value)


def encode_string(text):
    raw = text.encode("utf-16le", errors="surrogatepass")
    n = len(raw) // 2
    length = bytes([n]) if n < 255 else b"\xff" + (struct.pack("<H", n) if n < 65535 else b"\xff\xff" + struct.pack("<I", n))
    return b"\xff\xfe\xff" + length + raw


@dataclass
class 对象:
    start: int
    name: 字串
    comment: 字串
    unit: 字串
    prefix: list
    extra_before_init: 字串
    middle: list
    initial: 字串
    suffix: list
    members: list
    extra_after_init: 字串
    tail: list
    end: int

    @property
    def kind(self):
        return self.prefix[0]

    @property
    def id(self):
        return self.suffix[3]

    def encode(self):
        pack = lambda xs: struct.pack("<" + "I"*len(xs), *xs)
        return b"".join([self.name.encode(), self.comment.encode(), self.unit.encode(), pack(self.prefix), self.extra_before_init.encode(), pack(self.middle), self.initial.encode(), pack(self.suffix[:7]), b"".join(x.encode() for x in self.members), pack(self.suffix[7:]), self.extra_after_init.encode(), pack(self.tail)])


def parse_scalar(reader):
    start = reader.pos
    name, comment, unit = reader.string(), reader.string(), reader.string()
    prefix = [reader.u32() for _ in range(9)]
    if prefix[0] not in (1, 2, 3, 0xffffffff):
        raise 结构未支持(f"未验证对象类型：offset={start}, type={prefix[0]}")
    before = reader.string()
    middle = [reader.u32() for _ in range(7)]
    initial = reader.string()
    suffix = [reader.u32() for _ in range(7)]
    if suffix[6] > 10000:
        raise 结构未支持("组成员数量超出研究边界")
    members = [reader.string() for _ in range(suffix[6])]
    suffix += [reader.u32() for _ in range(2)]
    if suffix[7:] != [0, 0]:
        raise 结构未支持(f"未实现的报警/附加扩展：offset={start}, object_id={suffix[3]}")
    if prefix[0] != 0xffffffff and members:
        raise 结构未支持(f"标量出现组成员：offset={start}")
    after = reader.string()
    tail = [reader.u32() for _ in range(3)]
    if tail != [0, 2, 0]:
        raise 结构未支持(f"未验证记录尾：offset={start}")
    return 对象(start, name, comment, unit, prefix, before, middle, initial, suffix, members, after, tail, reader.pos)


def parse(data):
    reader = 游标(data)
    version = reader.read(4)
    if version != struct.pack("<f",16.0):
        raise 结构未支持("仅验证16.0格式；拒绝未知版本。")
    length, count = reader.u32(), reader.u32()
    if length != len(data)-8:
        raise 结构未支持("归档长度字段与实际块长度不符。")
    objects=[]
    for index in range(count):
        start=reader.pos
        try:
            obj=parse_scalar(reader)
        except Exception as exc:
            raise 结构未支持(f"对象#{index}始于{start}，尚未完整支持；已完成{len(objects)}条：{exc}") from exc
        objects.append(obj)
    if reader.pos != len(data):
        raise 结构未支持(f"记录后有未解析数据：offset={reader.pos}, total={len(data)}")
    return version, objects


def serialize(version, objects):
    body=struct.pack("<I",len(objects))+b"".join(obj.encode() for obj in objects)
    return version+struct.pack("<I",len(body))+body


def new_string(value):
    """新建原厂Unicode CString；不复用任何来源文本的编码缓存。"""
    return 字串(value, encode_string(value), True)


def validate_objects(objects):
    """验证ID/名称唯一及组成员可解析；不改变原记录顺序。"""
    ids={}
    names={}
    for obj in objects:
        if obj.id in ids:
            raise 结构未支持(f"对象ID重复：{obj.id}")
        key=obj.name.value.casefold()
        if not key or key in names:
            raise 结构未支持(f"对象名称为空或不区分大小写重名：id={obj.id}")
        if obj.suffix[6] != len(obj.members):
            raise 结构未支持(f"组成员计数字段不一致：id={obj.id}")
        ids[obj.id]=obj
        names[key]=obj
    for obj in objects:
        for member in obj.members:
            if member.value.casefold() not in names:
                raise 结构未支持(f"组成员找不到：group_id={obj.id}")
    return ids, names
