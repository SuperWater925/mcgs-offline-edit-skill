"""McgsStu原生输入框/静态文字工厂；只处理已实证布局，不写数据库。

CDrawEdit 325.3的安全表达式是成员+0x124，+0x194为键盘窗口名。
原厂资源1939和DDX桥证明条件0=表达式为0失效、样式1=变灰。
复杂动画由主代理公共动画模块处理；本模块新建控件动画数组为空。
"""
from __future__ import annotations
from dataclasses import dataclass
import copy
import json
import math
from pathlib import Path
import re
import struct
import sys

ROOT=Path(__file__).resolve().parent
FLOAT_MAX=struct.unpack("<f",bytes.fromhex("ffff7f7f"))[0]
from mcs_window_archive import Reader,ControlRecord,WindowArchive,write_count,write_cstring,FormatError


def pack_words(values):return struct.pack("<"+"I"*len(values),*values)


@dataclass
class Common:
    before_name:bytes
    name:str
    metadata:bytes
    rect_offset:int
    name_start:int

    @classmethod
    def parse(cls,r):
        r.take(4)
        flags=r.u32();r.u32()
        if flags&0x100:
            r.u32();r.u32();r.cstring()
        rect_offset=r.pos
        r.take(16+18+14)
        animations=r.count()
        if animations:raise FormatError("输入/文字工厂暂只接无动画模板；公共动画由主模块装配")
        r.u16();r.u16()
        start=r.pos
        name,_,_=r.cstring()
        metadata,_=r.byte_array()
        return cls(r.data[:start],name,metadata,rect_offset,start)

    def to_bytes(self):
        return self.before_name+write_cstring(self.name)+write_count(len(self.metadata))+self.metadata

    def set_rect(self,rect):
        if len(rect)!=4 or rect[0]>=rect[2] or rect[1]>=rect[3]:raise ValueError("控件矩形不合法")
        p=self.rect_offset
        self.before_name=self.before_name[:p]+struct.pack("<4i",*rect)+self.before_name[p+16:]


def read_font(r):
    """CMcgsFont::Serialize @0xAE1780：BYTE、DWORD数量、逐项语言ID+LOGFONT。"""
    start=r.pos
    r.u8()
    count=r.u32()
    if count>32:raise FormatError("字体语言数量超出已验证范围")
    for _ in range(count):
        r.u32()
        r.take(28) # 5 LONG + 8 BYTE，faceName另存CString。
        r.cstring()
    return r.data[start:r.pos]


def change_font_height(raw,height):
    if not isinstance(height,int) or not 1<=height<=500:raise ValueError("字体像素高度超范围")
    result=bytearray(raw)
    r=Reader(raw);r.u8();count=r.u32()
    for _ in range(count):
        r.u32()
        struct.pack_into("<i",result,r.pos,-height)
        r.take(28);r.cstring()
    if r.pos!=len(raw):raise FormatError("字体记录尾未完整解析")
    return bytes(result)


def unit_slot(data,offset):
    r=Reader(data,offset)
    text,_,_=r.cstring()
    end=r.pos
    show=r.u32()
    if show not in (0,1):raise FormatError("单位显示开关与已验证布局不符")
    return text,end,show


def change_unit(data,offset,unit):
    _,end,_=unit_slot(data,offset)
    return data[:offset]+write_cstring(unit)+struct.pack("<I",int(bool(unit)))+data[end+4:]


@dataclass
class InputRecord:
    common:Common
    expression_cache:bytes
    properties:list[int]
    variable:str
    max_raw:bytes
    min_raw:bytes
    position_fields:list[int]
    enabled_expression:str
    disabled_when_nonzero:int
    disabled_style:int
    font:bytes
    keyboard_fields:list[int]
    keyboard_window:str
    keyboard_position:list[int]
    appearance:bytes

    @classmethod
    def parse(cls,control):
        if control.type_id!=0x5025:raise FormatError("不是原生输入框5025")
        r=Reader(control.payload)
        common=Common.parse(r)
        if control.payload[:4]!=struct.pack("<f",325.3):raise FormatError("仅验证输入框325.3")
        cache,_=r.byte_array()
        props=[r.u32() for _ in range(7)]
        variable,_,_=r.cstring()
        if props[4]&6:
            raise FormatError("输入极限表达式分支未实现，拒绝模板")
        maximum,minimum=r.take(4),r.take(4)
        position=[r.u32(),r.u32()]
        enabled,_,_=r.cstring()
        condition,style=r.u32(),r.u32()
        font=read_font(r)
        keyboard=[r.u32() for _ in range(3)]
        keyboard_window,_,_=r.cstring()
        keyboard_position=[r.u32(),r.u32()]
        appearance=r.data[r.pos:]
        # 两个单位槽由同一原厂属性持久化；原39的MPa/mm/秒样本交叉核。
        primary=unit_slot(common.metadata,34)
        secondary=unit_slot(appearance,20)
        if primary[0]!=secondary[0] or primary[2]!=secondary[2]:
            raise FormatError("重复单位属性不一致")
        return cls(common,cache,props,variable,maximum,minimum,position,enabled,condition,
                   style,font,keyboard,keyboard_window,keyboard_position,appearance)

    def to_bytes(self):
        return b"".join([self.common.to_bytes(),write_count(len(self.expression_cache)),
                         self.expression_cache,pack_words(self.properties),write_cstring(self.variable),
                         self.max_raw,self.min_raw,pack_words(self.position_fields),
                         write_cstring(self.enabled_expression),
                         pack_words([self.disabled_when_nonzero,self.disabled_style]),self.font,
                         pack_words(self.keyboard_fields),write_cstring(self.keyboard_window),
                         pack_words(self.keyboard_position),self.appearance])

    @property
    def variable_id(self):return self.properties[5]

    @property
    def variable_type(self):return self.properties[6]

    @property
    def unit(self):return unit_slot(self.common.metadata,34)[0]

    def set_unit(self,unit):
        self.common.metadata=change_unit(self.common.metadata,34,unit)
        self.appearance=change_unit(self.appearance,20,unit)

    def set_decimal_format(self):
        # 原G5十进制/十六进制/二进制三样本证明该项分别0/1/2；
        # 浮点和字符串为FFFFFFFF，由原生类型自动选择自然数字/字符模式。
        mode=0 if self.variable_type==1 else 0xffffffff
        a=bytearray(self.common.metadata);b=bytearray(self.appearance)
        struct.pack_into("<I",a,26,mode)
        struct.pack_into("<I",b,12,mode)
        # 两处密码格式均关闭，保留自然小数位和最小整数位的原厂设置。
        struct.pack_into("<I",a,30,0)
        struct.pack_into("<I",b,16,0)
        self.common.metadata,self.appearance=bytes(a),bytes(b)


@dataclass
class LabelRecord:
    common:Common
    caption:str
    appearance_prefix:list[int]
    unit:str
    appearance_suffix:list[int]
    property_count:bytes
    colour:int
    style:int
    font:bytes
    flags:bytes
    properties:list[int]
    extra_string:str
    tail:list[int]

    @classmethod
    def parse(cls,control):
        if control.type_id!=0x5008:raise FormatError("不是原生文字5008")
        r=Reader(control.payload)
        common=Common.parse(r)
        if control.payload[:4]!=struct.pack("<f",352.1):raise FormatError("仅验证文字352.1")
        caption,_,_=r.cstring()
        prefix=[r.u32() for _ in range(7)]
        unit,_,_=r.cstring()
        suffix=[r.u32() for _ in range(4)]
        if suffix[3]:raise FormatError("文字图片背景分支未验证")
        prop_start=r.pos
        if r.count():raise FormatError("文字额外属性袋非空，暂拒绝")
        prop_count=r.data[prop_start:r.pos]
        colour,style=r.u32(),r.u16()
        font=read_font(r)
        flags=r.take(2)
        properties=[r.u32() for _ in range(6)]
        extra,_,_=r.cstring()
        tail=[r.u32() for _ in range(3)]
        if r.pos!=len(r.data):raise FormatError("文字记录有未解析尾部")
        return cls(common,caption,prefix,unit,suffix,prop_count,colour,style,font,flags,properties,extra,tail)

    def to_bytes(self):
        return b"".join([self.common.to_bytes(),write_cstring(self.caption),
                         pack_words(self.appearance_prefix),write_cstring(self.unit),
                         pack_words(self.appearance_suffix),self.property_count,
                         struct.pack("<IH",self.colour,self.style),self.font,self.flags,
                         pack_words(self.properties),write_cstring(self.extra_string),pack_words(self.tail)])






def validate_expression(expression):
    names=json.loads((ROOT/"对象名ID映射.json").read_text("utf-8"))
    keywords={"AND","OR","NOT","TRUE","FALSE"}
    for token in re.findall(r"[A-Za-z_\u3400-\u9fff][A-Za-z0-9_\u3400-\u9fff]*",expression):
        if token.upper() not in keywords and token not in names:
            raise FormatError("使能表达式引用未交付的对象："+token)
