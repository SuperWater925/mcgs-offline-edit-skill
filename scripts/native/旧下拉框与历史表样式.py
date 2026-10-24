"""Precisely bounded appearance spans for the two legacy native widgets.

Static evidence: McgsSetStu.exe CDrawComboBox serializer 8b45e0 and
CDrawSaveData serializer 9c88a0, style dialog 9d6190/RT_DIALOG1739,
and RT_DIALOG439. This module handles bytes only and never opens an MCS.
"""
from dataclasses import dataclass, field
from pathlib import Path
import copy
import struct
import sys

from mcs_window_archive import Reader, FormatError
from mcs_input_text import read_font
from 原生界面样式 import CommonEnvelope

COMBO_ROLES = {'mf0': 'odd_row_and_display_fill', 'mf4': 'even_row_fill', 'mf8': 'text_color',
               'mfc_font': 'text_font', 'm12c': 'row_height'}
SAVE_ROLES = {'m240': 'header_fill', 'm248': 'header_text', 'm25c': 'odd_row_fill',
              'm260': 'body_text', 'm268': 'grid', 'm278': 'even_row_fill',
              'm280': 'focus_row_fill', 'm288': 'focus_cell_fill', 'm290': 'focus_text',
              'm210_font': 'header_font', 'm228_font': 'body_font',
              'm204': 'row_height', 'm2a8': 'inner_rect'}

@dataclass
class NativeStyle:
    original: bytes
    spans: dict = field(default_factory=dict)
    values: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    def _add(self, key, offset, size, kind='color'):
        if offset < 0 or offset+size > len(self.original): raise FormatError('Style span out of bounds')
        self.spans[key] = (offset, offset+size, kind)
        data = self.original[offset:offset+size]
        self.values[key] = data if kind=='font' else (struct.unpack('<4i', data) if kind=='rect' else struct.unpack('<I', data)[0])

    def set(self, **values):
        for key, value in values.items():
            if key not in self.spans: raise ValueError('Unapproved visual member '+key)
            kind = self.spans[key][2]
            if kind == 'font':
                if not isinstance(value, bytes): raise TypeError('Font must be native CMcgsFont bytes')
                r=Reader(value); read_font(r)
                if r.pos != len(value): raise FormatError('Font record not completely parsed')
            elif kind == 'rect':
                value=tuple(value)
                if len(value)!=4 or not all(type(v)is int for v in value) or value[2]<value[0] or value[3]<value[1]:
                    raise ValueError('Invalid inner rectangle')
            elif type(value)is not int or not 0<=value<=0xffffffff:
                raise ValueError('Native DWORD outside bounds')
            if kind=='color_with_flag':
                value=(self.values[key]&0xff000000)|(value&0xffffff)
            if kind=='dimension' and not 1<=value<=1000:
                raise ValueError('Native row height outside bounds')
            self.values[key]=value
        return self

    def to_bytes(self):
        chunks=[]; cursor=0
        for key, (start, end, kind) in sorted(self.spans.items(), key=lambda item:item[1][0]):
            if start < cursor: raise FormatError('Overlapping style spans')
            chunks.append(self.original[cursor:start]); value=self.values[key]
            chunks.append(value if kind=='font' else struct.pack('<4i',*value) if kind=='rect' else struct.pack('<I',value))
            cursor=end
        chunks.append(self.original[cursor:]); return b''.join(chunks)

    def protected(self):
        """Byte comparison that removes only the proven appearance fields."""
        chunks=[]; cursor=0
        for key,(start,end,kind) in sorted(self.spans.items(), key=lambda item:item[1][0]):
            chunks.extend((self.original[cursor:start], ('<STYLE:'+key+'>').encode('ascii')))
            if kind=='color_with_flag':chunks.append(self.original[end-1:end])
            cursor=end
        chunks.append(self.original[cursor:]); return b''.join(chunks)

    def apply_to_record(self, record):
        result=CommonEnvelope.parse(record)
        if result.content != self.original: raise FormatError('Record differs from parsed original')
        result.content=self.to_bytes(); return result.to_record()

    def affine_inner_rect(self, old_outer, new_outer):
        old=tuple(old_outer); new=tuple(new_outer)
        if old[2]<=old[0] or old[3]<=old[1]: raise ValueError('Outer rectangle has zero size')
        inner=self.values['m2a8']
        def x(v):return round(new[0]+(v-old[0])*(new[2]-new[0])/(old[2]-old[0]))
        def y(v):return round(new[1]+(v-old[1])*(new[3]-new[1])/(old[3]-old[1]))
        return self.set(m2a8=(x(inner[0]),y(inner[1]),x(inner[2]),y(inner[3])))


def parse_combo(data):
    """325.3 CDrawComboBox content, preserving list/data/selection/images."""
    result=NativeStyle(data); r=Reader(data)
    count=r.count()
    if count>10000: raise FormatError('Unproven ComboBox item count')
    result.metadata['items']=[r.cstring()[0] for _ in range(count)]
    result.metadata['content_expression']=r.cstring()[0]
    result.metadata['content_cache']=r.cstring()[0]
    result.metadata['content_id']=r.u32(); result.metadata['content_type']=r.u32()
    result.metadata['index_expression']=r.cstring()[0]
    result.metadata['index_id']=r.u32(); result.metadata['index_type']=r.u32()
    result._add('mf0',r.pos,4,'color_with_flag');r.u32()
    result._add('mf8',r.pos,4,'color_with_flag');r.u32()
    r.u32() # this+13c drop-down component type
    start=r.pos;read_font(r);result._add('mfc_font',start,r.pos-start,'font')
    r.u8() # original native switch this+130
    result._add('mf4',r.pos,4,'color_with_flag');r.u32()
    result._add('m12c',r.pos,4,'dimension');r.u32()
    result.metadata['opaque_tail_offset']=r.pos
    if result.to_bytes()!=data:raise FormatError('ComboBox roundtrip failed')
    return result


def parse_save_data(data):
    """352.1 CDrawSaveData content from the one original native data table."""
    result=NativeStyle(data);r=Reader(data)
    if r.take(10)!=bytes(10):raise FormatError('Unproven SaveData extension/list header')
    n=r.u32()
    if not 0<n<=1000:raise FormatError('Unproven SaveData column count')
    columns=[]
    for _ in range(n):
        columns.append(dict(width=r.u32(),alignment=r.u32(),texts=[r.cstring()[0] for _ in range(5)],words=[r.u32(),r.u32()]))
    result.metadata['columns']=columns
    if r.u32()!=0:raise FormatError('Unproven SaveData temporary array')
    result.metadata['native_name']=r.cstring()[0]
    r.take(4+11*4) # member100,104..118,198,120,two reserved,140
    for _ in range(9):r.cstring() # 144 and148..164
    r.take(7*4) # 17c..194
    for _ in range(3):r.cstring() # 19c,1b4,1cc
    r.take(4);r.cstring() # 1d0,1d4
    r.take(7*4) # 1d8,1dc,1e0,1e4,1fc,200,20c
    result.metadata['unmodified_m208_color_offset']=r.pos;r.u32()
    for key in ('m210_font','m228_font'):
        start=r.pos;read_font(r);result._add(key,start,r.pos-start,'font')
    post=r.pos
    for key,delta in {'m240':0,'m248':8,'m25c':28,'m260':36,'m268':40,
                      'm278':104,'m280':112,'m288':120,'m290':128}.items():
        result._add(key,post+delta,4)
    result._add('m2a8',post+64,16,'rect')
    result._add('m204',post+100,4,'dimension')
    # Ensure the entire fixed tail and final empty array/data binding are valid.
    r.take(136)
    if r.u32()!=0:raise FormatError('Unproven SaveData trailing row array')
    result.metadata['trailing_object_id']=r.u32()
    result.metadata['trailing_object_name']=r.cstring()[0]
    if r.pos!=len(data):raise FormatError('SaveData tail not fully parsed')
    result.metadata['post_font_offset']=post
    if result.to_bytes()!=data:raise FormatError('SaveData roundtrip failed')
    return result

def parse_record(record):
    c=CommonEnvelope.parse(record)
    if record.type_id==0x503c:return parse_combo(c.content)
    if record.type_id==0x5033:return parse_save_data(c.content)
    raise FormatError('Unsupported legacy native type')
