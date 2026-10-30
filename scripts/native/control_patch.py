"""Bounded existing-control edits shared by Stu and Pro. No database access."""
from __future__ import annotations
import copy
import math
import struct
from 原生界面样式 import CommonEnvelope, GroupArchive, MultiState, set_font
from mcs_input_text import InputRecord, LabelRecord, InputMetadata
from mcs_button_control import ButtonArchive

def text(value):
    if not isinstance(value,str) or '\0' in value:raise ValueError('Expected text without NUL')
    return value

def edit(record,changes,variables=None):
    allowed={'bounds','fill','border','text','font','unit','binding','minimum','maximum','press_source','release_source','repair_input_metadata'}
    if not changes or set(changes)-allowed:raise ValueError('Unknown or empty control edit')
    original=copy.deepcopy(record)
    cm=CommonEnvelope.parse(record)
    if cm.to_record().payload!=record.payload:raise ValueError('Control original roundtrip differs')
    if 'bounds' in changes:
        rect=changes['bounds']
        if not isinstance(rect,list) or len(rect)!=4 or any(type(x)is not int or abs(x)>32768 for x in rect) or rect[0]>=rect[2] or rect[1]>=rect[3]:raise ValueError('Invalid positive control bounds')
        if record.type_id in (0x5028,0x502a):
            m=MultiState.parse(record);m.resize(rect);record=m.to_record()
        elif record.type_id in (0x5008,0x5025,0x5027):cm.set_rect(rect);record=cm.to_record()
        else:raise ValueError('Bounds editing requires text/input/button/multi-state; use verified class geometry for other types')
    cm=CommonEnvelope.parse(record)
    for key in ('fill','border'):
        if key in changes and (type(changes[key])is not int or not 0<=changes[key]<=0xffffff):raise ValueError('Colors use integer COLORREF 0..0xffffff')
    cm.set_common_colors(**{k:changes[k] for k in ('fill','border') if k in changes})
    record=cm.to_record()
    special=set(changes)-{'bounds','fill','border'}
    if not special:return record
    projected=cm.project_without_animations()
    kind=record.type_id
    parsers={0x5008:LabelRecord,0x5025:InputRecord,0x5027:ButtonArchive}
    if kind not in parsers:raise ValueError('Class-specific edit requires label/input/standard button')
    q=parsers[kind].parse(projected)
    if q.to_bytes()!=projected.payload:raise ValueError('Class original roundtrip differs')
    if 'repair_input_metadata' in changes:
        if kind!=0x5025 or changes['repair_input_metadata'] is not True:raise ValueError('Metadata length repair requires an input and true')
        metadata=InputMetadata.parse(q.common.metadata,q.appearance);metadata.normalize_counts()
        q.common.metadata=metadata.to_bytes();InputMetadata.parse(q.common.metadata)
    if 'text' in changes:
        value=text(changes['text'])
        if kind==0x5008:q.caption=value
        elif kind==0x5027:q.caption.value=q.metadata.properties.caption.value=value
        else:raise ValueError('Caption requires label or button')
    if 'font' in changes:
        font=changes['font']
        if not isinstance(font,dict) or not font or set(font)-{'height','weight','family'}:raise ValueError('Unknown font property')
        if 'weight' in font and (type(font['weight'])is not int or not 0<=font['weight']<=1000):raise ValueError('Invalid font weight')
        if 'family' in font:text(font['family'])
        q.font=set_font(q.font,**font)
        if kind==0x5027:q.metadata.properties.font=set_font(q.metadata.properties.font,**font)
    if special & {'unit','binding','minimum','maximum'}:
        if kind!=0x5025:raise ValueError('Input properties require an input control')
        if 'unit' in changes:q.set_unit(text(changes['unit']))
        if 'binding' in changes:
            name=text(changes['binding']);target=(variables or {}).get(name)
            if target is None or target['kind'] not in (1,2,3):raise ValueError('Binding must resolve to an existing scalar object')
            # Preserve numeric versus character editor semantics.
            if (q.variable_type==3)!=(target['kind']==3):raise ValueError('Numeric/character binding kind differs')
            if (q.variable,q.variable_id,q.variable_type)!=(name,target['id'],target['kind']):
                q.variable=name;q.properties[5]=target['id'];q.properties[6]=target['kind'];q.expression_cache=b''
        if special & {'minimum','maximum'}:
            if q.variable_type==3:raise ValueError('Numeric range cannot be applied to a character input')
            low=changes.get('minimum',struct.unpack('<f',q.min_raw)[0]);high=changes.get('maximum',struct.unpack('<f',q.max_raw)[0])
            largest=struct.unpack('<f',bytes.fromhex('ffff7f7f'))[0]
            if not all(type(v)in (int,float) and math.isfinite(v) and abs(v)<=largest for v in (low,high)) or low>high:raise ValueError('Invalid finite input range')
            if 'minimum' in changes:q.min_raw=struct.pack('<f',low)
            if 'maximum' in changes:q.max_raw=struct.pack('<f',high)
    for key in ('press_source','release_source'):
        if key in changes:
            if kind!=0x5027:raise ValueError('Native press/release source requires a standard button')
            value=text(changes[key]);owner=q.metadata.properties if key=='press_source' else q
            attr='press_script' if key=='press_source' else 'release_script'
            cache='press_compiled' if key=='press_source' else 'release_compiled'
            if getattr(owner,attr).value!=value:
                getattr(owner,attr).value=value;getattr(owner,cache).value=b''
    projected.payload=q.to_bytes()
    # Reparse both the class body and the animation-bearing native result.
    if parsers[kind].parse(projected).to_bytes()!=projected.payload:raise ValueError('Changed class roundtrip differs')
    out=cm.restore_projected(projected)
    if CommonEnvelope.parse(out).to_record().payload!=out.payload:raise ValueError('Changed common roundtrip differs')
    if CommonEnvelope.parse(out).prefix[cm.animation_start:cm.animation_end]!=cm.prefix[cm.animation_start:cm.animation_end]:raise ValueError('Animation bytes changed')
    return out

def at_path(controls,path):
    if not isinstance(path,list) or not path or any(type(i)is not int or i<0 for i in path):raise ValueError('Control path requires nonnegative indexes')
    try:
        record=controls[path[0]]
        if len(path)==1:return record
        return at_path(GroupArchive.parse(record).children,path[1:])
    except IndexError:raise ValueError('Control path outside existing records')

def replace_path(controls,path,replacement):
    if len(path)==1:controls[path[0]]=replacement;return
    group=GroupArchive.parse(controls[path[0]])
    replace_path(group.children,path[1:],replacement)
    controls[path[0]]=group.to_record()
