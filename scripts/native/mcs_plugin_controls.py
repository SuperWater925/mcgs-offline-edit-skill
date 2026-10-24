"""Static, byte-exact native external-control envelope and Recipe/XY settings."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import struct
import copy
import json
import sys
from mcs_window_archive import Reader, ControlRecord, WindowArchive, FormatError

ROOT=Path(__file__).resolve().parent

def utf8_read(r): return r.take(r.u32()).decode("utf-8")
def utf8_write(value):
    raw=value.encode("utf-8"); return struct.pack("<I",len(raw))+raw
def buffer_read(r): return r.take(r.u32())
def buffer_write(raw): return struct.pack("<I",len(raw))+raw

@dataclass
class PluginControl:
    record: ControlRecord
    path: str
    core: bytes
    prefix: bytes
    @classmethod
    def parse(cls,record):
        if record.type_id!=0x503d: raise FormatError("Not native external control")
        fields=record.common(); r=Reader(record.payload,fields["content_offset"])
        path,_,_=r.cstring(); prefix=record.payload[:r.pos]
        core=r.take(r.u32())
        if r.pos!=len(record.payload): raise FormatError("Unexpected external control suffix")
        return cls(copy.deepcopy(record),path,core,prefix)
    def to_record(self):
        result=copy.deepcopy(self.record)
        result.payload=self.prefix+buffer_write(self.core)
        return result

@dataclass
class RecipeColumn:
    binding: str
    title: str
    values: list[int]
    @classmethod
    def parse(cls,r): return cls(utf8_read(r),utf8_read(r),[r.unpack("<i") for _ in range(8)])
    def to_bytes(self): return utf8_write(self.binding)+utf8_write(self.title)+struct.pack("<8i",*self.values)

@dataclass
class RecipeCore:
    header: bytes
    group: str
    columns: list[RecipeColumn]
    fields: dict
    # Sequence proven by DrawRecipe.ui DrawRecipe::SerializeNew, 0x10002cd0.
    SPEC=(('m40','i'),('m44','i'),('m48','i'),('m4c_font','bytes'),('m50','i'),('m54_font','bytes'),('m60','i'),('m64','i'),('m68','i'),('m6c','i'),('m58','i'),('m5c','i'),('m70','i'),('flags','i'),('m78','i'),('m7c','i'),('m80','i'),('m84','i'),('m88','i'),('m90','i'),('visible_expression','str'),('m94_cache','bytes'))
    @classmethod
    def parse(cls,data):
        r=Reader(data); header=r.take(20)
        if struct.unpack_from("<I",header,16)[0]!=22: raise FormatError("Unsupported Recipe schema")
        group=utf8_read(r); n=r.u32()
        if n>1000: raise FormatError("Invalid recipe column count")
        columns=[RecipeColumn.parse(r) for _ in range(n)]
        fields={}
        for key,kind in cls.SPEC:
            fields[key]=r.unpack("<i") if kind=='i' else utf8_read(r) if kind=='str' else buffer_read(r)
        if r.pos!=len(data): raise FormatError(f"Recipe core unparsed tail at {r.pos}/{len(data)}")
        return cls(header,group,columns,fields)
    def to_bytes(self):
        out=self.header+utf8_write(self.group)+struct.pack("<I",len(self.columns))+b''.join(c.to_bytes() for c in self.columns)
        for key,kind in self.SPEC:
            value=self.fields[key]
            out+=struct.pack("<i",value) if kind=='i' else utf8_write(value) if kind=='str' else buffer_write(value)
        return out

def read_spec(r,spec):
    result={}
    for key,kind in spec:
        result[key]=r.unpack('<i') if kind=='i' else r.unpack('<f') if kind=='f' else utf8_read(r) if kind=='str' else buffer_read(r) if kind=='bytes' else r.take(int(kind))
    return result

def write_spec(fields,spec):
    out=b''
    for key,kind in spec:
        value=fields[key]
        out+=struct.pack('<i',value) if kind=='i' else struct.pack('<f',value) if kind=='f' else utf8_write(value) if kind=='str' else buffer_write(value) if kind=='bytes' else value
    return out

@dataclass
class XYCore:
    header: bytes
    fields: dict
    curves: list[dict]
    tail: dict
    SPEC=(('mdc','i'),('mb4','i'),('m108','str'),('me8','i'),('md0','f'),('mcc','f'),('mf0','f'),('m88','i'),('m8c','16'),('m9c','i'),('ma0','16'),('m60','i'),('m64','16'),('m74','i'),('m78','16'),('mb0','i'),('mc4','i'),('mbc','i'),('mc0','i'),('md4_font','bytes'),('mc8','i'),('md8','i'),('mec','f'),('mf0_second','f'),('mdc_second','i'),('me8_second','i'),('me0','i'),('me4','i'),('mf4_font','bytes'),('mf8','i'),('mfc','i'),('m168','i'),('m16c','i'))
    CURVE_SPEC=(('m17c','str'),('m180','i'),('m184','i'),('m188','i'),('m1a8','str'),('m1ac','str'),('m198','str'),('m19c','str'),('m1a0','str'),('m1a4','str'),('m1bc','str'),('m1c0','str'),('m1c4','str'),('m1c8','str'),('m1cc','str'),('m1dc','i'),('m1e0','str'),('m1e4','str'),('m1e8','str'),('m1ec','str'),('m1f0','str'),('m200','i'),('m208','str'),('m204','str'),('m210','str'),('m20c','str'),('m214','16'),('m224','str'),('m228','str'),('m22c','i'),('m230','i'))
    TAIL_SPEC=(('m120','i'),('mb8','i'),('visible_cache','bytes'),('m5c','i'),('m4c','16'),('m100','i'),('m104','i'))
    @classmethod
    def parse(cls,data):
        r=Reader(data); header=r.take(20)
        if struct.unpack_from('<I',header,16)[0]!=0x50911: raise FormatError('Unsupported XY schema')
        fields=read_spec(r,cls.SPEC)
        curves=[read_spec(r,cls.CURVE_SPEC) for _ in range(8)]
        tail=read_spec(r,cls.TAIL_SPEC)
        if r.pos!=len(data): raise FormatError(f'XY unparsed tail {r.pos}/{len(data)}')
        return cls(header,fields,curves,tail)
    def to_bytes(self):
        return self.header+write_spec(self.fields,self.SPEC)+b''.join(write_spec(c,self.CURVE_SPEC) for c in self.curves)+write_spec(self.tail,self.TAIL_SPEC)
