"""Fail-closed native UI codec additions for the frozen 2026-10-21 project.

CDraw common fields, original animation byte slices, CEventDispatch, and the
two-state native CDrawMulBtn/CDrawMulDis image/text children are preserved.
This module never opens a database or executes vendor code.
"""
from __future__ import annotations
from dataclasses import dataclass
import copy
import hashlib
import json
from pathlib import Path
import struct
import sys

HERE=Path(__file__).resolve().parent
from mcs_window_archive import Reader, ControlRecord, WindowArchive, FormatError, write_count
from mcs_button_control import CString, ByteArray, Array, _font, _picture
from mcs_input_text import LabelRecord, InputRecord

def sha(raw):return hashlib.sha256(raw).hexdigest()

def animation(r):
    start=r.pos
    if r.u16()!=0xffff:raise FormatError('Animation class reference is not in this frozen schema')
    schema=r.u16();n=r.u16();name=r.take(n).decode('ascii')
    if schema!=0:raise FormatError('Unknown animation schema')
    value=r.take(4);expression=CString.parse(r)
    detail=dict(class_name=name,expression=expression.value,initial_float_bits=value.hex())
    if name=='CAniOutput':
        detail.update(off_text=r.cstring()[0],on_text=r.cstring()[0],fields=[r.u32() for _ in range(4)])
    elif name in ('CAniBrush','CAniTextColor'):
        n=r.count()
        if n>10000:raise FormatError('Animation ranges exceed bounds')
        detail['thresholds']=[r.unpack('<f') for _ in range(n)]
        n=r.count();detail['colors']=[r.u32() for _ in range(n)]
    elif name=='CAniVisible':detail['mode']=r.u32()
    elif name=='CAniBlink':
        # Native Serialize 0x4883a0: members 0x40..0x50, five DWORDs.
        detail['blink_words']=[r.u32() for _ in range(5)]
    elif name=='CAniVMove':
        # Native CAniVMove Serialize 0x48c2b0: two ints and two floats.
        detail['movement_words']=[r.u32(),r.u32()]
        detail['movement_float_bits']=r.take(8).hex()
    elif name=='CAniSize':
        # Native 0x48b060: DWORD,float,DWORD,float,DWORD,DWORD.
        # All six source fields stay byte-exact; no scale semantics guessed.
        detail['size_fields_raw']=r.take(24).hex()
    elif name=='CAniInput':
        # Native Serialize old/new bodies 0x48dc40/0x48dde0. CString
        # members 0x34/0x3c/0x44; preserve all original animation bytes.
        begin=r.pos
        try:
            flags=r.u32()
            if flags&~7:raise FormatError('Unknown input-animation flags')
            kind=r.u32();expressions=[r.cstring()[0] for _ in range(3)]
            maximum=r.cstring()[0] if flags&4 else r.take(4).hex()
            minimum=r.cstring()[0] if flags&2 else r.take(4).hex()
            words=[r.u32() for _ in range(3)]
            detail.update(encoding='input-flags',flags=flags,input_kind=kind,expressions=expressions,maximum=maximum,minimum=minimum,input_words=words)
        except (ValueError,UnicodeError):
            r.pos=begin
            kind=r.u32();expressions=[r.cstring()[0] for _ in range(3)]
            limits=r.take(8);words=[r.u32() for _ in range(4)]
            detail.update(encoding='input-legacy',input_kind=kind,expressions=expressions,limit_bits=limits.hex(),input_words=words)
    elif name=='CAniClick':
        detail['action_texts']=[v.value for v in Array.parse(r,True).items]
        detail['action_flags']=Array.parse(r).items
        detail['action_ids']=Array.parse(r).items
        detail['tail_arrays']=[ByteArray.parse(r).value,ByteArray.parse(r).value]
        detail['reserved_word']=r.u32()
    else:raise FormatError('Unproven animation class '+name)
    return detail,r.data[start:r.pos]

@dataclass
class CommonEnvelope:
    record:ControlRecord
    prefix:bytes
    rect_offset:int
    pen_offset:int
    brush_offset:int
    animation_start:int
    animation_end:int
    animations:list
    name:CString
    metadata:ByteArray
    content:bytes
    @classmethod
    def parse(cls,record):
        r=Reader(record.payload);r.take(4);style=r.u32();r.u32()
        if style&0x100:r.take(8);r.cstring()
        ro=r.pos;r.take(16);po=r.pos;r.take(18);bo=r.pos;r.take(14)
        ast=r.pos;n=r.count();items=[]
        if n>1000:raise FormatError('Animation count too large')
        for _ in range(n):items.append(animation(r)[0])
        aend=r.pos;r.take(4)
        prefix=record.payload[:r.pos];name=CString.parse(r);meta=ByteArray.parse(r)
        return cls(copy.deepcopy(record),prefix,ro,po,bo,ast,aend,items,name,meta,record.payload[r.pos:])
    @property
    def rect(self):return tuple(struct.unpack_from('<4i',self.prefix,self.rect_offset))
    def to_record(self):
        result=copy.deepcopy(self.record)
        result.payload=self.prefix+self.name.to_bytes()+self.metadata.to_bytes()+self.content
        return result
    def set_rect(self,rect):
        if len(rect)!=4 or not all(type(v)is int for v in rect):raise ValueError('Invalid rectangle')
        # Native lines/polygons can retain reversed endpoints. Translation
        # and exact undo must preserve their direction rather than normalize it.
        prefix=bytearray(self.prefix);struct.pack_into('<4i',prefix,self.rect_offset,*rect);self.prefix=bytes(prefix)
    def set_common_colors(self,fill=None,border=None):
        prefix=bytearray(self.prefix)
        # Native LOGPEN = four DWORDs (style,width x,width y,COLORREF),
        # LOGBRUSH = three DWORDs (style,COLORREF,hatch); both have type WORD.
        if fill is not None:struct.pack_into('<I',prefix,self.brush_offset+2+4,fill)
        if border is not None:struct.pack_into('<I',prefix,self.pen_offset+2+12,border)
        self.prefix=bytes(prefix)
    def project_without_animations(self):
        result=self.to_record();a,b=self.animation_start,self.animation_end
        result.payload=result.payload[:a]+write_count(0)+result.payload[b:]
        return result
    def restore_projected(self,projected):
        # Restore the original animation array and flags byte for byte after a
        # class-specific style edit. This never synthesizes an animation graph.
        p=CommonEnvelope.parse(projected)
        if p.animations:raise FormatError('Projected archive unexpectedly contains animations')
        raw=projected.payload;a,b=p.animation_start,p.animation_end
        result=copy.deepcopy(projected)
        result.payload=raw[:a]+self.prefix[self.animation_start:self.animation_end]+raw[b:]
        return result

@dataclass
class EventDispatch:
    header:bytes
    compiled:ByteArray
    empty_arrays:bytes
    event_id:int
    event_name:CString
    kind:int
    reserved:CString
    unknown:int
    source:CString
    tail_array:ByteArray
    @classmethod
    def parse(cls,r):
        start=r.pos
        if r.u16()!=0xffff or r.u16()!=0:raise FormatError('Unproven generic event class header')
        name=r.take(r.u16()).decode('ascii')
        if name!='CEventDispatch':raise FormatError('Unproven generic event class '+name)
        header=r.data[start:r.pos];compiled=ByteArray.parse(r)
        start=r.pos
        if any(r.count() for _ in range(3)):raise FormatError('Nonempty generic-event argument arrays require separate schema')
        arrays=r.data[start:r.pos]
        return cls(header,compiled,arrays,r.u32(),CString.parse(r),r.u32(),CString.parse(r),r.u32(),CString.parse(r),ByteArray.parse(r))
    def to_bytes(self):
        return self.header+self.compiled.to_bytes()+self.empty_arrays+struct.pack('<I',self.event_id)+self.event_name.to_bytes()+struct.pack('<I',self.kind)+self.reserved.to_bytes()+struct.pack('<I',self.unknown)+self.source.to_bytes()+self.tail_array.to_bytes()
    def set_source(self,source):
        if self.source.value!=source:
            self.source.value=source;self.compiled.value=b'';self.tail_array.value=b''

@dataclass
class GenericMetadata:
    count_raw:bytes
    events:list[EventDispatch]
    tail:bytes
    @classmethod
    def parse(cls,data):
        r=Reader(data);start=r.pos;n=r.count();count=data[start:r.pos]
        if n>1:raise FormatError('Multiple generic event CArchive class maps require separate schema')
        events=[EventDispatch.parse(r) for _ in range(n)]
        return cls(count,events,data[r.pos:])
    def to_bytes(self):return self.count_raw+b''.join(v.to_bytes() for v in self.events)+self.tail

@dataclass
class MultiChild:
    name:CString
    header:bytes
    picture:bytes|None
    caption:CString|None
    font:bytes|None
    tail:bytes
    @classmethod
    def parse(cls,r,kind,image_tail=12):
        name=CString.parse(r);header=r.take(72)
        if kind=='image':return cls(name,header,_picture(r),None,None,r.take(image_tail))
        if kind=='text':return cls(name,header,None,CString.parse(r),_font(r),r.take(28))
        raise FormatError('Unknown multi child kind')
    def to_bytes(self):
        return self.name.to_bytes()+self.header+(self.picture if self.picture is not None else self.caption.to_bytes()+self.font)+self.tail
    @property
    def rect(self):return tuple(struct.unpack_from('<4i',self.header,8))
    @property
    def parent_rect(self):return tuple(struct.unpack_from('<4i',self.header,24))
    @property
    def double_rect(self):return tuple(struct.unpack_from('<4d',self.header,40))
    def resize(self,old_size,new_size):
        ow,oh=old_size;nw,nh=new_size
        if min(ow,oh,nw,nh)<=0:raise ValueError('Invalid multi-state control size')
        sx,sy=nw/ow,nh/oh;h=bytearray(self.header)
        for offset in (8,24):
            vals=struct.unpack_from('<4i',h,offset)
            struct.pack_into('<4i',h,offset,*(round(v*(sx if i%2==0 else sy)) for i,v in enumerate(vals)))
        vals=struct.unpack_from('<4d',h,40)
        struct.pack_into('<4d',h,40,*(v*(sx if i%2==0 else sy) for i,v in enumerate(vals)))
        self.header=bytes(h)
    def set_text_color(self,color):
        if self.caption is None:raise ValueError('Not a multi-state text child')
        # CTextInObj new-version Serialize e8c490 and property ID4 bridge
        # e8c960 map primary text COLORREF member+0x88 to tail DWORD 0.
        # DWORD 2 is member+0x8c, an auxiliary colour, not the primary ink.
        tail=bytearray(self.tail);struct.pack_into('<I',tail,0,color);self.tail=bytes(tail)

@dataclass
class MultiState:
    common:CommonEnvelope
    levels:list[float]
    fills:list[list[int]]
    images:list[list[MultiChild]]
    texts:list[list[MultiChild]]
    tail:bytes
    @classmethod
    def parse(cls,record):
        if record.type_id not in (0x5028,0x502a):raise FormatError('Not CDrawMulBtn/CDrawMulDis')
        # Two measured native child layouts differ by eight trailing image
        # bytes. Select a complete, unique structural parse, never a software
        # release whitelist; retain each child's original tail verbatim.
        candidates=[];failures=[]
        for image_tail in (12,4):
            try:
                common=CommonEnvelope.parse(record);r=Reader(common.content)
                n=r.u32()
                if n>1000:raise FormatError('Invalid multi-state count')
                levels=[r.unpack('<f') for _ in range(n)]
                n=r.u32()
                if n>1000:raise FormatError('Invalid multi-state fill count')
                fills=[[r.u32(),r.u32()] for _ in range(n)]
                collections=[]
                for kind in ('image','text'):
                    n=r.u32();groups=[]
                    if n>1000:raise FormatError('Invalid multi-state collection count')
                    for _ in range(n):
                        m=r.u32()
                        if m>1000:raise FormatError('Invalid multi-state child count')
                        groups.append([MultiChild.parse(r,kind,image_tail) for _ in range(m)])
                    collections.append(groups)
                if any(len(groups)!=len(levels) for groups in collections):
                    raise FormatError('Multi-state image/text state counts differ from thresholds')
                candidate=cls(common,levels,fills,*collections,common.content[r.pos:])
                if candidate.to_record().payload!=record.payload:raise FormatError('Multi-state byte roundtrip differs')
                if not candidates or candidate!=candidates[0]:candidates.append(candidate)
            except (ValueError,UnicodeError) as exc:failures.append(str(exc))
        if len(candidates)!=1:
            raise FormatError('Ambiguous multi-state child layout' if candidates else 'Unsupported multi-state child layout: '+'; '.join(failures))
        return candidates[0]
    def to_record(self):
        out=struct.pack('<I',len(self.levels))+struct.pack('<'+'f'*len(self.levels),*self.levels)
        out+=struct.pack('<I',len(self.fills))+b''.join(struct.pack('<2I',*v) for v in self.fills)
        for groups in (self.images,self.texts):
            out+=struct.pack('<I',len(groups))
            for children in groups:out+=struct.pack('<I',len(children))+b''.join(c.to_bytes() for c in children)
        self.common.content=out+self.tail
        return self.common.to_record()
    def resize(self,rect):
        old=self.common.rect;size=(old[2]-old[0],old[3]-old[1]);new=(rect[2]-rect[0],rect[3]-rect[1])
        for groups in (self.images,self.texts):
            for children in groups:
                for child in children:child.resize(size,new)
        self.common.set_rect(rect)

@dataclass
class MultiButtonTail:
    input_expression:CString
    input_words:list
    output_expression:CString
    output_words:list
    rest:bytes
    @classmethod
    def parse(cls,data):
        r=Reader(data);a=CString.parse(r);aw=[r.u32() for _ in range(4)]
        b=CString.parse(r);bw=[r.u32() for _ in range(4)]
        return cls(a,aw,b,bw,data[r.pos:])
    def to_bytes(self):return self.input_expression.to_bytes()+struct.pack('<4I',*self.input_words)+self.output_expression.to_bytes()+struct.pack('<4I',*self.output_words)+self.rest
    def bind_ui_input(self,name,ident):
        # CDrawMulBtn::Serialize 0x91cd61 writes input source followed by
        # native resolved object ID, reserved DWORD, data type, reserved DWORD.
        # Current index29 resolves 配方程序画面变色; new IDs are obtained from
        # the fully parsed appended ObjData, never guessed or offset.
        self.input_expression.value=name;self.input_words[0]=ident

@dataclass
class GroupArchive:
    common:CommonEnvelope
    children:list
    tail:bytes
    @classmethod
    def parse(cls,record):
        if record.type_id!=0x503a:raise FormatError('Not native CDrawUnit group')
        common=CommonEnvelope.parse(record);r=Reader(common.content);n=r.u32();children=[]
        if n>10000:raise FormatError('Group child count invalid')
        for _ in range(n):
            start=r.pos;kind=r.u32();payload,prefix=r.byte_array()
            children.append(ControlRecord(kind,payload,prefix,start))
        return cls(common,children,common.content[r.pos:])
    def to_record(self):
        self.common.content=struct.pack('<I',len(self.children))+b''.join(c.to_bytes() for c in self.children)+self.tail
        return self.common.to_record()

def set_plugin_font(raw,height=None,family=None,weight=None):
    r=Reader(raw);flag=r.u8();n=r.u32();out=bytes([flag])+struct.pack('<I',n)
    if n>64:raise FormatError('Plugin font language count invalid')
    for _ in range(n):
        lang=r.take(4);b=bytearray(r.take(60))
        if height is not None:struct.pack_into('<i',b,0,-height)
        if weight is not None:struct.pack_into('<i',b,16,weight)
        if family is not None:
            value=family.encode('cp936')
            if len(value)>=32:raise ValueError('Plugin LOGFONTA face too long')
            b[28:60]=value+b'\0'*(32-len(value))
        out+=lang+bytes(b)
    if r.pos!=len(raw):raise FormatError('Plugin font tail not parsed')
    return out

def fonts(raw):
    r=Reader(raw);flags=r.u8();n=r.u32();items=[]
    if n>64:raise FormatError('Font language count invalid')
    for _ in range(n):
        lang=r.u32();b=r.take(28);face=r.cstring()[0]
        v=struct.unpack('<5i8B',b)
        items.append(dict(language=lang,height=abs(v[0]),height_raw=v[0],weight=v[4],family=face,flags=flags))
    if r.pos!=len(raw):raise FormatError('Unexpected font suffix')
    return items

def set_font(raw,height=None,family=None,weight=None):
    r=Reader(raw);flag=r.u8();n=r.u32();out=bytes([flag])+struct.pack('<I',n)
    if n>64:raise FormatError('Font language count invalid')
    for _ in range(n):
        lang=r.take(4);b=bytearray(r.take(28));face=CString.parse(r)
        if height is not None:
            if type(height)is not int or not 8<=height<=128:raise ValueError('Font height invalid')
            struct.pack_into('<i',b,0,-height)
        if weight is not None:struct.pack_into('<i',b,16,weight)
        if family is not None:face.value=family
        out+=lang+bytes(b)+face.to_bytes()
    if r.pos!=len(raw):raise FormatError('Unexpected font suffix')
    return out
