"""Proven AlarmTableView 0x55b36 style-only editor.

No database/vendor-code/UI access. Native filter/source/column data remain opaque
and byte-identical. Color roles proved by Serialize 10011dc0 -> grid1004ed00,
10051930/10051a50/10051af0/10051c60/10051cf0/10051d80/100520c0,
property dialog10010d20, native RT_DIALOG115 and setters10017cc0.
"""
from pathlib import Path
import hashlib,json,struct,sys
HERE=Path(__file__).resolve().parent
from 原生界面样式 import set_plugin_font

def rgb(s):
    r,g,b=bytes.fromhex(s.removeprefix('#'));return r+(g<<8)+(b<<16)

class AlarmStyle:
    def __init__(self,data):
        self.data=bytes(data);self.fields={};self.fonts=[]
        if len(data)<400 or data[8:16]!=struct.pack('<d',-1):
            raise ValueError('Unproven AlarmTableView core')
        p=28
        for _ in range(6):
            n=struct.unpack_from('<I',data,p)[0]
            if n>len(data)-p-4:raise ValueError('Alarm source string exceeds buffer')
            p+=4+n
        # Six source/filter strings and six integer source IDs are not styles.
        p+=24+1
        def field(name,size=4):
            nonlocal p
            self.fields[name]=(p,size);p+=size
        for mem in range(0x2c,0x54,4):field(f'g{mem:x}')
        for name,size in [('rows',4),('row_height',4),('g164',4),('g168',4),('g6c',4),('g70',1),('g74',4),('g78',4),
                          ('new_text',4),('ended_unanswered_text',4),('answered_active_text',4),('odd_background',4),
                          ('title_background',4),('title_text',4),('focus_border',4),('ge8',4)]:field(name,size)
        for role in ('title_font','body_font'):
            n=struct.unpack_from('<I',data,p)[0];p+=4
            if n<5 or n>4101 or p+n>len(data):raise ValueError('Invalid AlarmTableView font extent')
            # Native font map has a flags byte, DWORD language count and
            # 64-byte language+LOGFONTA records. One/two language maps occur
            # in both families; preserve source header and opaque newer tail.
            if set_plugin_font(data[p:p+n])!=data[p:p+n]:raise ValueError('Alarm font map roundtrip differs')
            self.fonts.append((role,p,n));p+=n
        for name in ('gbc','gc0','gc4','gc8','gd0','gd4','ge4','g28','gec','gf4','gf0',
                     'even_background','focus_background','focus_text','grid_color','gcc','gd8','gdc','ge0'):
            field(name)
        field('gf8',1);field('g16c',1)
        for name in ('g1a8','category_new_background','category_answered_background','category_ended_background',
                     'category_complete_background','g1c0','g1c4','g1c8','g1cc','ended_text','complete_text',
                     'g54','g58','g5c'):field(name)
        # Variable strings and cached filter IDs must be skipped, never rewritten.
        for _ in range(3):
            n=struct.unpack_from('<I',data,p)[0];p+=4+n
        for _ in range(3):p+=4
        field('category_prior_background');field('g1d0');field('prior_text')
        self.opaque_tail=p
        if p>len(data):raise ValueError('Alarm fields exceed core buffer')
    def to_bytes(self):return self.data
    def value(self,name):
        p,n=self.fields[name];return int.from_bytes(self.data[p:p+n],'little')
    def style(self,*,font_height=22,row_height=44,colors=None):
        theme=dict(ink='#24384B',header='#DCEAF4',white='#FFFFFF',pale='#F3F7FA',
                   accent='#256FAE',line='#A7BDCD',red='#C33B3B',green='#198578',muted='#718799')
        if colors:theme.update(colors)
        out=bytearray(self.data);allowed=set();changes=[]
        def change(name,value):
            p,n=self.fields[name];before=bytes(out[p:p+n]);after=int(value).to_bytes(n,'little')
            out[p:p+n]=after;allowed.update(range(p,p+n))
            if before!=after:changes.append(dict(field=name,offset=p,bytes=n,before=int.from_bytes(before,'little'),after=value))
        fixed={'title_background':'header','title_text':'ink','odd_background':'white','even_background':'pale',
               'focus_background':'accent','focus_text':'white','focus_border':'line','grid_color':'line'}
        for key,value in fixed.items():change(key,rgb(theme[value]))
        # Preserve each original alarm-state color family; do not invent new
        # state classifications or modify state/filter/flash/answer conditions.
        palette={0x0000ff:'red',0x00ff00:'green',0xff0000:'accent',0:'ink',0x828282:'muted',0xffffff:'white'}
        for key in ('new_text','ended_unanswered_text','answered_active_text','complete_text','ended_text','prior_text'):
            old=self.value(key)
            if old in palette:change(key,rgb(theme[palette[old]]))
        for key in ('category_new_background','category_answered_background','category_ended_background','category_complete_background','category_prior_background'):
            old=self.value(key)
            if old in (0xc0c0c0,0xffffff):change(key,rgb(theme['white']))
        change('row_height',row_height)
        for role,p,n in self.fonts:
            before=bytes(out[p:p+n]);after=set_plugin_font(before,height=font_height,family='微软雅黑',weight=400)
            if len(after)!=n:raise ValueError('Font length changed')
            out[p:p+n]=after;allowed.update(range(p,p+n))
            if before!=after:changes.append(dict(field=role,offset=p,bytes=n,before_sha256=hashlib.sha256(before).hexdigest(),after_sha256=hashlib.sha256(after).hexdigest()))
        actual={i for i,(a,b) in enumerate(zip(self.data,out)) if a!=b}
        assert actual<=allowed and bytes(out[self.opaque_tail:])==self.data[self.opaque_tail:]
        return bytes(out),dict(fields=changes,allowed_offsets=sorted(allowed),changed_offsets=sorted(actual),
                               business_tail_unchanged=True,scrollbar_visibility_unchanged=True,
                               scrollbar_color='not exposed by native dialog; checkbox controls visibility only')
