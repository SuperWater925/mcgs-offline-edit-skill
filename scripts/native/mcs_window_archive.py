"""Native McgsStu WndUser envelope and fail-closed control cloning.

No vendor code is loaded or executed. Unchanged data is preserved exactly.
Known layout comes from native MCS samples plus static serialization code.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import copy
import hashlib
import json
import struct
import sys

ROOT = Path(__file__).resolve().parent

class FormatError(ValueError): pass

class Reader:
    def __init__(self, data: bytes, pos=0): self.data, self.pos = data, pos
    def take(self, n):
        if n < 0 or self.pos + n > len(self.data): raise FormatError(f"Truncated stream at {self.pos} needs {n}")
        value=self.data[self.pos:self.pos+n]; self.pos+=n; return value
    def unpack(self, fmt): return struct.unpack(fmt,self.take(struct.calcsize(fmt)))[0]
    def u8(self): return self.unpack("<B")
    def u16(self): return self.unpack("<H")
    def u32(self): return self.unpack("<I")
    def count(self):
        n=self.u16()
        return self.u32() if n==0xffff else n
    def byte_array(self):
        start=self.pos; size=self.count(); value=self.take(size)
        return value, self.data[start:self.pos-size]
    def cstring(self):
        start=self.pos; wide=False; n=self.u8()
        if n==0xff:
            n=self.u16()
            if n==0xfffe:
                wide=True; n=self.u8()
                if n==0xff:
                    n=self.u16()
                    if n==0xffff: n=self.u32()
            elif n==0xffff: n=self.u32()
        raw=self.take(n*(2 if wide else 1))
        value=raw.decode("utf-16le" if wide else "cp936",errors="strict")
        return value, self.data[start:self.pos], wide

def write_count(n):
    return struct.pack("<H",n) if n<0xffff else b"\xff\xff"+struct.pack("<I",n)

def write_cstring(value, wide=True):
    raw=value.encode("utf-16le" if wide else "cp936")
    n=len(raw)//(2 if wide else 1)
    prefix=(b"\xff\xfe\xff" if wide else b"")
    if n<0xff: prefix+=struct.pack("<B",n)
    elif n<0xfffe: prefix+=b"\xff"+struct.pack("<H",n)
    else: prefix+=b"\xff\xff\xff"+struct.pack("<I",n)
    return prefix+raw

@dataclass
class OleVariant:
    vt: int
    value: object
    raw: bytes
    @classmethod
    def parse(cls,r):
        start=r.pos; vt=r.u16()
        fmts={2:"<h",3:"<i",4:"<f",5:"<d",6:"<q",7:"<d",10:"<i",11:"<h",16:"<b",17:"<B",18:"<H",19:"<I",20:"<q",21:"<Q"}
        if vt in (0,1): value=None
        elif vt in fmts: value=r.unpack(fmts[vt])
        elif vt==8:
            size=r.u32()
            if size%2: raise FormatError("Odd BSTR byte count")
            value=r.take(size).decode("utf-16le")
        else: raise FormatError(f"Unsupported OLE variant {vt:#x} at {start}")
        return cls(vt,value,r.data[start:r.pos])
    def to_bytes(self):
        r=Reader(self.raw); original=OleVariant.parse(r)
        if self.vt==original.vt and self.value==original.value: return self.raw
        header=struct.pack("<H",self.vt)
        if self.vt==3: return header+struct.pack("<i",self.value)
        if self.vt==8:
            raw=str(self.value).encode("utf-16le"); return header+struct.pack("<I",len(raw))+raw
        raise FormatError("Only proven int32 and BSTR edits currently supported")

@dataclass
class WindowSettings:
    password_data: bytes  # Opaque, never decoded or reported.
    properties: list[OleVariant]
    event_tail: bytes
    @classmethod
    def parse(cls,trailer):
        r=Reader(trailer); size=r.u32(); pwd_size=r.u32(); pwd=r.take(pwd_size); core=r.take(size)
        if r.pos!=len(trailer): raise FormatError("Unexpected bytes after window settings")
        p=Reader(core)
        n=p.count(); props=[OleVariant.parse(p) for _ in range(n)]
        return cls(pwd,props,core[p.pos:])
    def to_bytes(self):
        core=write_count(len(self.properties))+b"".join(v.to_bytes() for v in self.properties)+self.event_tail
        return struct.pack("<2I",len(core),len(self.password_data))+self.password_data+core
    def clone(self,window_id,name):
        result=copy.deepcopy(self)
        if len(result.properties)!=21 or result.properties[0].vt!=3 or result.properties[1].vt!=8: raise FormatError("Unsupported window schema")
        result.properties[0].value=window_id; result.properties[1].value=name
        return result

@dataclass
class ControlRecord:
    type_id: int
    payload: bytes
    length_prefix: bytes
    source_offset: int
    def to_bytes(self):
        prefix=self.length_prefix if Reader(self.length_prefix).count()==len(self.payload) else write_count(len(self.payload))
        return struct.pack("<I",self.type_id)+prefix+self.payload
    def common(self):
        """Read fields proven by CDrawObj serialization; reject nonempty animation list for now."""
        if self.type_id not in (0x5004,0x5008,0x503d): raise FormatError("Control-specific prefix not verified for this type")
        r=Reader(self.payload)
        version=r.unpack("<f")
        style=(r.u32(),r.u32())
        link_header=None
        if style[0]&0x100:
            link_header=(r.u32(),r.u32(),r.cstring()[0])
        rect_offset=r.pos
        rect=struct.unpack("<4i",r.take(16))
        pen_style=r.u16(); pen=r.take(16)
        brush_style=r.u16(); brush=r.take(12)
        animation_count=r.count()
        if animation_count: raise FormatError(f"Nonempty animation list ({animation_count}) needs class-aware parser")
        base_word=r.u16(); base_flags=r.u16()
        name_start=r.pos; name,name_raw,wide=r.cstring(); name_end=r.pos
        metadata,prefix=r.byte_array()
        return dict(version=version,style=style,link_header=link_header,rect=rect,rect_offset=rect_offset,pen_style=pen_style,pen=pen.hex(),brush_style=brush_style,brush=brush.hex(),animation_count=animation_count,base_word=base_word,base_flags=base_flags,name=name,name_start=name_start,name_end=name_end,name_wide=wide,common_end=name_end,metadata_bytes=len(metadata),content_offset=r.pos)
    def clone(self, name=None, rect=None):
        result=copy.deepcopy(self); fields=self.common(); data=self.payload
        if rect is not None:
            if len(rect)!=4 or rect[0]>=rect[2] or rect[1]>=rect[3]: raise ValueError("Invalid rectangle")
            pos=fields["rect_offset"]
            data=data[:pos]+struct.pack("<4i",*rect)+data[pos+16:]
        if name is not None:
            data=data[:fields["name_start"]]+write_cstring(name,fields["name_wide"])+data[fields["name_end"]:]
        result.payload=data
        return result

@dataclass
class WindowArchive:
    prefix: bytes
    controls: list[ControlRecord]
    trailer: bytes
    source: bytes
    @classmethod
    def parse(cls,data):
        r=Reader(data); r.take(12)
        marker,_,_=r.cstring()
        if marker!="MCGS-SET DOCUMENT;VERSION 01.00": raise FormatError("Unexpected document marker")
        prefix=data[:r.pos]; count=r.u32()
        if count>100000: raise FormatError("Unreasonable object count")
        controls=[]
        for _ in range(count):
            offset=r.pos; kind=r.u32(); payload,prefix_len=r.byte_array()
            controls.append(ControlRecord(kind,payload,prefix_len,offset))
        return cls(prefix,controls,data[r.pos:],data)
    def to_bytes(self):
        return self.prefix+struct.pack("<I",len(self.controls))+b"".join(c.to_bytes() for c in self.controls)+self.trailer
    def settings(self): return WindowSettings.parse(self.trailer)
