"""当前5033非空原生字段列表的精确只读/样式span适配；不写MCS。

原有352.1 codec只覆盖member1b8列表为空的10B前缀。当前记录的同一
前缀为6B原样头、DWORD数量、逐项CString+DWORD；仅把后续已证样式
span按列表实际长度平移，列表和全部非样式字节始终原样保留。
"""
from pathlib import Path
import copy,struct,sys
HERE=Path(__file__).resolve().parent
from 原生界面样式 import Reader,CommonEnvelope
from 旧下拉框与历史表样式 import NativeStyle,parse_save_data

def parse_current_save_data(data):
    r=Reader(data)
    if r.take(6)!=bytes(6):raise ValueError('当前SaveData前6B头不匹配，禁止猜边界')
    n=r.u32()
    if not 0<=n<=1000:raise ValueError('当前SaveData原生字段数量越界')
    fields=[]
    for _ in range(n):
        start=r.pos
        name=r.cstring()[0]
        word=r.u32()
        fields.append(dict(name=name,native_word=word,offset=start,end=r.pos))
    end=r.pos
    normalized=data[:6]+bytes(4)+data[end:]
    base=parse_save_data(normalized)
    shift=end-10
    result=NativeStyle(data)
    for key,(a,b,kind) in base.spans.items():
        assert a>=10
        result._add(key,a+shift,b-a,kind)
        assert result.values[key]==base.values[key]
    result.metadata=copy.deepcopy(base.metadata)
    result.metadata.update(native_field_list=fields,native_field_prefix_bytes=end,style_offset_shift=shift,
        original_front_six_bytes_hex=data[:6].hex(),native_word_meaning_not_inferred=True)
    result.metadata['post_font_offset']+=shift
    result.metadata['unmodified_m208_color_offset']+=shift
    # Read-only member-address map from native 9c88a0 serialization order.
    # Addresses label structure positions only, not inferred runtime semantics.
    q=Reader(data,end)
    columns=q.u32()
    for _ in range(columns):
        q.take(8)
        for _ in range(5):q.cstring()
        q.take(8)
    assert q.u32()==0
    q.cstring()
    config={}
    def word(name):
        offset=q.pos
        value=q.u32()
        config[name]=dict(offset=offset,kind='DWORD',value=value,raw_hex=data[offset:q.pos].hex())
    def string(name):
        offset=q.pos
        value=q.cstring()[0]
        config[name]=dict(offset=offset,kind='CString',value=value,raw_hex=data[offset:q.pos].hex())
    for name in ('100','104','108','10c','110','114','118','198','120','reserved1','reserved2','140'):word(name)
    for name in ('144','148','14c','150','154','158','15c','160','164'):string(name)
    for name in ('17c','180','184','188','18c','190','194'):word(name)
    for name in ('19c','1b4','1cc'):string(name)
    word('1d0')
    string('1d4')
    for name in ('1d8','1dc','1e0','1e4','1fc','200','20c'):word(name)
    result.metadata['native_config_member_map']=config
    if result.to_bytes()!=data:raise ValueError('当前SaveData原文回环不匹配')
    return result

def parse_record(record):
    if record.type_id!=0x5033:raise ValueError('本轮只接原生5033存盘浏览')
    cm=CommonEnvelope.parse(record)
    return parse_current_save_data(cm.content)
