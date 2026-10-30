"""Read-only native-field renderer following the proven native paint gates.

No MCS access, vendor process, GUI automation, device access, or event execution.
Native plugin drawing and system scrollbar chrome are explicitly approximated.
This revision rejects the old unconditional common brush/pen assumption.
Std two-state selectors, Input frame and Multi primary ink match static evidence.

用法：python 离线预览.py --export-dir <run.ps1 inspect 导出或候选导出> --output <新目录>
      [--full-dir <另一份含 MCGSLINGUIST 的导出>] [--windows 1 2 ...] [--active-map <规则.json>]
已知与原厂运行时不一致的地方见 references/ui-tools.md。
"""
from pathlib import Path
import argparse, base64, copy, hashlib, importlib.util, io, json, math, re, struct, sys, subprocess, html
from collections import Counter
from PIL import Image,ImageDraw,ImageFont

import os, shutil
import time
sys.dont_write_bytecode=True
NATIVE=Path(__file__).resolve().parents[1]/'scripts'/'native'
sys.path.insert(0,str(NATIVE))
from 原生界面样式 import CommonEnvelope,MultiState,GroupArchive,GenericMetadata,MultiButtonTail,fonts
from mcs_window_archive import WindowArchive,Reader,ControlRecord
from mcs_button_control import ButtonArchive,_picture
from mcs_input_text import LabelRecord,InputRecord
from mcs_plugin_controls import PluginControl,RecipeCore,XYCore
from 窗口事件归档 import 窗口事件
from 报警表原生样式 import AlarmStyle
from 原生趋势样式 import HistoryCurveStyle
from 旧下拉框与历史表样式 import parse_record as parse_old_legacy_style
from 当前存盘浏览样式 import parse_record as parse_current_savedata_style
def parse_legacy_style(record):
    return parse_current_savedata_style(record) if record.type_id==0x5033 else parse_old_legacy_style(record)
import mcgs_native_zip as nativezip

def plugin_fonts(raw,plugin=False):
    """外部构件字体表：u8 标志 + u32 个数 + 每项 u32 语言、LOGFONT 前 28 字节与字体名。"""
    r=Reader(raw);flags=r.u8();n=r.u32();result=[]
    assert n<=32
    for _ in range(n):
        lang=r.u32();data=r.take(60 if plugin else 28)
        family=data[28:].split(b'\0',1)[0].decode('cp936') if plugin else r.cstring()[0]
        vals=struct.unpack('<5i8B',data[:28])
        keys=('height_raw','width','escapement','orientation','weight','italic','underline','strikeout','charset','out_precision','clip_precision','quality','pitch_and_family')
        item=dict(zip(keys,vals));item.update(language=lang,height=abs(vals[0]),family=family,map_flags=flags)
        result.append(item)
    assert r.pos==len(raw)
    return result
FONT_DIR=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'

PALETTE=dict(ink='#233748',muted='#5F7282',line='#A7BDCD',white='#FFFFFF',head='#DCEAF4',field='#EDF4F9',secondary='#E7F0F7',blue='#236FAE')
FONTS={}
def sha(b):return hashlib.sha256(b).hexdigest()
def dump(p,o):Path(p).write_text(json.dumps(o,ensure_ascii=False,indent=2)+'\n','utf-8')
def clr(n):return '#%02X%02X%02X'%(n&255,(n>>8)&255,(n>>16)&255)

def common_gdi(cm):
    po,bo=cm.pen_offset,cm.brush_offset
    return dict(brush_enable=struct.unpack_from('<H',cm.prefix,bo)[0],
                brush_style=struct.unpack_from('<I',cm.prefix,bo+2)[0],
                pen_enable=struct.unpack_from('<H',cm.prefix,po)[0],
                pen_style=struct.unpack_from('<I',cm.prefix,po+2)[0],
                pen_width=struct.unpack_from('<I',cm.prefix,po+6)[0])

def draw_edge(im,rect,pressed=False):
    """Static DrawEdge(5/A, BF_RECT) approximation, explicitly reported."""
    x,y,r,b=map(round,rect);d=ImageDraw.Draw(im)
    if r-x<7 or b-y<7:return
    tl,br=('#808080','#FFFFFF') if pressed else ('#FFFFFF','#808080')
    d.line((x+1,b-2,x+1,y+1,r-2,y+1),fill=tl,width=1)
    d.line((x+2,b-2,r-2,b-2,r-2,y+2),fill=br,width=1)
    tl2,br2=('#404040','#D4D0C8') if pressed else ('#D4D0C8','#404040')
    d.line((x+2,b-3,x+2,y+2,r-3,y+2),fill=tl2,width=1)
    d.line((x+3,b-3,r-3,b-3,r-3,y+3),fill=br2,width=1)

def button_states(q,translate):
    p=q.metadata.properties.words
    return [dict(selector=0,fill=clr(p[6]),border=clr(p[7]),brush_enable=p[8],pen_enable=p[9],ink=clr(p[5]),style=p[15],caption=translate(q.metadata.properties.caption.value),font=fonts(q.metadata.properties.font)[0] if fonts(q.metadata.properties.font) else {},image_slot=1),
            dict(selector=1,fill=clr(p[1]),border=clr(p[2]),brush_enable=p[10],pen_enable=p[11],ink=clr(q.caption_words[1]),style=q.caption_words[0]%10000,caption=translate(q.caption.value),font=fonts(q.font)[0] if fonts(q.font) else {},image_slot=0)]

def picture_descriptor(raw):
    """Describe stored image content; the native enable flag is separate."""
    if not raw:return dict(storage='absent',empty=True,known=True,name=None)
    r=Reader(raw);mode=r.u32()
    if mode==0x80:
        name=r.cstring()[0]
        return dict(storage='reference',mode=mode,name=name,empty=not bool(name),known=r.pos==len(raw))
    if mode==3:
        width,height=r.u32(),r.u32()
        return dict(storage='embedded',mode=mode,width=width,height=height,empty=width==height==0,known=width==height==0 and r.pos==len(raw),name=None)
    return dict(storage='unknown',mode=mode,known=False,empty=None,name=None)

def input_picture_descriptor(data,start=0):
    r=Reader(data,start);r.take(20);r.cstring();r.u32();offset=r.pos;enabled=r.u32();r.take(12);r.cstring();r.u32()
    begin=r.pos;image=_picture(r) if enabled else b''
    return dict(enabled=enabled,flag_offset=offset,picture_start=begin,picture_end=r.pos,picture=picture_descriptor(image))

def image_hazards(info):
    hazards=[]
    for slot in info:
        if not slot.get('enabled'):continue
        pic=slot['picture']
        if pic.get('empty'):hazards.append(dict(slot=slot.get('slot'),state=slot.get('state'),reason='enabled_native_image_is_empty',picture=pic))
        elif not pic.get('known'):hazards.append(dict(slot=slot.get('slot'),state=slot.get('state'),reason='enabled_image_encoding_unknown_to_renderer',picture=pic))
    return hazards
def fnt(h=24,family='微软雅黑',weight=400):
    h=max(8,min(128,round(h)));name='msyhbd.ttc' if weight>=600 else 'msyh.ttc'
    if family=='宋体':name='simsun.ttc'
    if family=='黑体':name='simhei.ttf'
    key=(h,name)
    if key not in FONTS:FONTS[key]=ImageFont.truetype(str(FONT_DIR/name),h)
    return FONTS[key]
def text(im,rect,value,h=24,ink=None,center=False,family='微软雅黑',weight=400,issues=None,identity=None,right=False):
    x,y,r,b=[round(v) for v in rect]
    if r<=x or b<=y or r<0 or b<0 or x>=im.width or y>=im.height:return
    value=str(value).replace('\r\r','\n').replace('\r\n','\n').replace('\r','\n')
    font=fnt(h,family,weight);d=ImageDraw.Draw(im);lines=value.split('\n');lineh=max(h,1)
    width=max((d.textlength(s,font=font) for s in lines),default=0)
    if issues is not None and (width>r-x-4 or len(lines)*lineh>b-y+4):
        issues.append(dict(control=identity,text=value,font_height=h,rect=[x,y,r,b],text_width=round(width,1),available_width=r-x-4))
    tile=Image.new('RGBA',(r-x,b-y),(0,0,0,0));td=ImageDraw.Draw(tile)
    sy=(b-y-len(lines)*lineh)/2
    for n,line in enumerate(lines):
        bb=td.textbbox((0,0),line,font=font);tw=td.textlength(line,font=font)
        td.text((((r-x-tw)/2 if center else (r-x-tw-3) if right else 3),sy+n*lineh-bb[1]),line,font=font,fill=ink or PALETTE['ink'])
    im.paste(tile,(x,y),tile)

def vector_asset(image,known_assets):
    """Decode native CDrawCell vector data stored inside a BMP pixel envelope."""
    off=struct.unpack_from('<I',image,10)[0]
    if image[off:off+4]!=b'VECT':return None,[]
    r=Reader(image,off+4);r.u32();width,height=r.u32(),r.u32()
    if r.u16()!=1 or r.u16()!=0xffff or r.u16()!=0:raise ValueError('Unproven VECT archive map')
    if r.take(r.u16())!=b'CDrawCell':raise ValueError('Unproven VECT class')
    cell=CommonEnvelope.parse(ControlRecord(0x5004,image[r.pos:],b'',0));r=Reader(cell.content);n=r.u32()
    im=Image.new('RGBA',(width,height),(0,0,0,0));d=ImageDraw.Draw(im);limits=[]
    for _ in range(n):
        kind=r.u32();raw,prefix=r.byte_array();cm=CommonEnvelope.parse(ControlRecord(kind,raw,prefix,0))
        rr=[round(v*(width if i%2==0 else height)/10000) for i,v in enumerate(cm.rect)]
        gd=common_gdi(cm)
        fill=clr(struct.unpack_from('<I',cm.prefix,cm.brush_offset+6)[0]) if gd['brush_enable'] and gd['brush_style']==0 else None
        border=clr(struct.unpack_from('<I',cm.prefix,cm.pen_offset+14)[0]) if gd['pen_enable'] and gd['pen_style']!=5 else None
        if kind==0x5004:
            if fill is not None or border is not None:d.rectangle(rr,fill=fill,outline=border)
        elif kind==0x5002 and border:d.line(rr,fill=border,width=1)
        elif kind in (0x501d,0x501e):
            if fill is not None or border is not None:d.rectangle(rr,fill=fill,outline=border)
            limits.append(dict(type=hex(kind),limit='原生渐变/圆角具体绘制近似，未改源资源'))
        elif kind==0x5009:
            q=Reader(cm.content);mode=q.u32();nm=q.cstring()[0] if mode==0x80 else None
            if nm in known_assets:
                a=known_assets[nm].resize((max(1,rr[2]-rr[0]),max(1,rr[3]-rr[1])));im.paste(a,tuple(rr[:2]),a)
            else:limits.append(dict(type=hex(kind),picture=nm,limit='嵌套原生图片分支未在此静态缩略中展开'))
        else:limits.append(dict(type=hex(kind),limit='原生矢量子类型绘图未实现'))
    return im,limits

def convert_svg_batch(items):
    """Load sharp once per preview, preserving every input SVG byte string."""
    if not items:return {},{}
    node=os.environ.get('MCGS_NODE') or shutil.which('node')
    if not node:return {},{key:'SVG 图片需要 Node.js（设置 MCGS_NODE）和 sharp（设置 MCGS_SHARP）' for key in items}
    code="const chunks=[];process.stdin.on('data',c=>chunks.push(c));process.stdin.on('end',async()=>{try{const sharp=require("+json.dumps(os.environ.get('MCGS_SHARP','sharp'))+");const a=JSON.parse(Buffer.concat(chunks).toString('utf8'));const out=await Promise.all(a.map(async x=>{try{return {id:x.id,png:(await sharp(Buffer.from(x.svg,'base64')).png().toBuffer()).toString('base64')}}catch(e){return {id:x.id,error:String(e)}}}));process.stdout.write(JSON.stringify(out))}catch(e){process.stderr.write(String(e));process.exitCode=1}})"
    payload=[{'id':key,'svg':base64.b64encode(value).decode('ascii')} for key,value in items.items()]
    try:
        result=subprocess.run([node,'-e',code],input=json.dumps(payload).encode('utf-8'),capture_output=True,timeout=120)
        if result.returncode:raise RuntimeError(result.stderr.decode('utf-8',errors='replace')[:1200])
        converted={};errors={}
        for item in json.loads(result.stdout):
            if 'error' in item:errors[item['id']]=item['error']
            else:converted[item['id']]=base64.b64decode(item['png'],validate=True)
        if set(converted)|set(errors)!=set(items):raise ValueError('SVG batch response is incomplete')
        return converted,errors
    except Exception as error:return {},{key:str(error) for key in items}


class Project:
    def __init__(self,export,full=None,active_rules=None,window_ids=None):
        started=time.perf_counter()
        self.export=Path(export);self.full=Path(full) if full else self.export
        self.active_rules=list(active_rules or [])
        for rule in self.active_rules:
            assert isinstance(rule.get('caption'),str) and all(isinstance(w,int) for w in rule.get('windows',[])),rule
        index_path=next((self.export/n for n in ('结构索引.json','完整结构索引.json','index.json') if (self.export/n).is_file()),None)
        if index_path is None:raise FileNotFoundError('导出目录里没有 index.json / 完整结构索引.json')
        self.index_sha=sha(index_path.read_bytes());ix=json.loads(index_path.read_text('utf-8-sig'))
        self.input_sha=ix['sha256'];self.is_candidate=ix.get('candidate_not_database_reread',False);self.windows={};self.read_errors=[]
        window_rows={row['iID']:row for row in ix['rows'] if row['table']=='WndUser'}
        self.total_window_count=len(window_rows)
        self.requested_windows=None if window_ids is None else list(window_ids)
        if window_ids is not None and set(window_ids)-set(window_rows):raise ValueError('请求的窗口号不存在')
        def load_window(wid):
            if wid in self.windows or wid not in window_rows:return
            row=window_rows[wid]
            raw=(self.export/row['lbObjects']['file']).read_bytes()
            if sha(raw)!=row['lbObjects']['sha256']:raise ValueError('Export hash mismatch')
            plain=nativezip.unpack(raw) if raw.startswith(nativezip.MARKER) else raw
            a=WindowArchive.parse(plain);assert a.to_bytes()==plain
            s=a.settings();props=[q.value for q in s.properties];ev=窗口事件.解析(s.event_tail)
            parents=list(struct.unpack_from('<3i',ev.扩展,8))
            w=dict(id=row['iID'],name=props[1],width=props[6],height=props[7],bg=props[15],parents=parents,controls=a.controls,source_sha=sha(raw))
            self.windows[w['id']]=w
            for parent in parents:load_window(parent)
        for wid in window_rows if window_ids is None else window_ids:load_window(wid)
        full_index=next((self.full/n for n in ('完整结构索引.json','结构索引.json','index.json') if (self.full/n).is_file()),None)
        idx=json.loads(full_index.read_text('utf-8-sig'))
        self.assets={};self.asset_errors=[];self.asset_render_limits=[];self.language=b'';self.strings={}
        pictures=[]
        for row in idx['rows']:
            if row['table']!='System':continue
            name=row.get('strName','')
            if name=='MCGSLINGUIST':
                self.language=(self.full/row['lbContext']['file']).read_bytes()
                if self.language.startswith(nativezip.MARKER):self.language=nativezip.unpack(self.language)
            if not name.startswith('MCGS_PICTURE_DATA_'):continue
            b=(self.full/row['lbContext']['file']).read_bytes()
            try:
                r=Reader(b);nm=r.cstring()[0];r.cstring();kind=r.u32();width=r.u32();height=r.u32();n=r.u32();image=r.take(n)
                assert r.pos==len(b)
                pictures.append((name,nm,image))
            except Exception as e:self.asset_errors.append(dict(name=name,error=str(e)))
        svg_items={str(i):image[image.index(b'<?xml'):] for i,(_,_,image) in enumerate(pictures) if image.startswith(b'VS') and b'<?xml' in image}
        converted,svg_errors=convert_svg_batch(svg_items)
        self.svg_batch_count=1 if svg_items else 0
        for i,(name,nm,image) in enumerate(pictures):
            try:
                vector,limits=vector_asset(image,self.assets) if image.startswith(b'BM') else (None,[])
                if vector is not None:
                    self.assets[nm]=vector
                    if limits:self.asset_render_limits.append(dict(picture_name=nm,limits=limits))
                    continue
                if image.startswith(b'VS') and b'<?xml' in image:
                    if str(i) in svg_errors:raise RuntimeError(svg_errors[str(i)])
                    image=converted[str(i)]
                image=Image.open(io.BytesIO(image)).convert('RGBA')
                self.assets[nm]=image
            except Exception as e:self.asset_errors.append(dict(name=name,picture_name=nm,error=str(e)))
        self.load_ms=round((time.perf_counter()-started)*1000,3)
    def translate(self,value):
        if not value or not value.startswith('\x07'):return value
        key=value[1:]
        if not key.isdigit():return value
        if key in self.strings:return self.strings[key]
        needle=struct.pack('<I',int(key));pos=0
        while True:
            pos=self.language.find(needle,pos)
            if pos<0:break
            try:
                n,lang=struct.unpack_from('<2I',self.language,pos+4)
                if 1<=n<=32 and lang==0:
                    text=Reader(self.language,pos+12).cstring()[0]
                    if len(text)<1000:self.strings[key]=text;return text
            except Exception:pass
            pos+=1
        return '资源 '+key
    def layers(self,wid):
        out=[];seen=set()
        def visit(n):
            if n not in self.windows or n in seen:return
            seen.add(n)
            for p in self.windows[n]['parents']:visit(p)
            out.append(n)
        visit(wid);return out
    def native_model(self,record,window,index,path='',group_rect=None,descendant_style=None):
        cm=CommonEnvelope.parse(record);p=cm.project_without_animations();rect=list(cm.rect)
        if group_rect:
            gx,gy,gr,gb=group_rect;rect=[gx+rect[0]*(gr-gx)/10000,gy+rect[1]*(gb-gy)/10000,gx+rect[2]*(gr-gx)/10000,gy+rect[3]*(gb-gy)/10000]
        rect=[round(v) for v in rect];name=cm.name.value;identity=f'{window}/{path}{name}'
        ro=cm.rect_offset;po=cm.pen_offset;bo=cm.brush_offset
        d=dict(window=window,index=index,name=name,type=record.type_id,rect=rect,identity=identity,animations=cm.animations,
               fill=clr(struct.unpack_from('<I',cm.prefix,bo+6)[0]),border=clr(struct.unpack_from('<I',cm.prefix,po+14)[0]),
               **common_gdi(cm))
        if record.type_id==0x5008:
            q=LabelRecord.parse(p);unit=self.translate(q.unit);d.update(align=q.style,kind='text',caption=self.translate(q.caption),font=fonts(q.font)[0] if fonts(q.font) else {},ink=clr(q.colour),unit=unit)
            outputs=[a for a in cm.animations if a['class_name']=='CAniOutput']
            if outputs:d.update(dynamic=True,caption='—'+(' '+unit if unit else ''),binding=outputs[0]['expression'])
        elif record.type_id==0x5025:
            q=InputRecord.parse(p);unit=self.translate(q.unit);d.update(align=q.properties[3],disabled_grey=(q.enabled_expression.strip()=='0' and q.disabled_style==1),kind='value',font=fonts(q.font)[0] if fonts(q.font) else {},caption='—'+(' '+unit if unit else ''),binding=q.variable,fill=clr(q.properties[1]),ink=clr(q.properties[0]),frame=q.properties[2])
            appearance=input_picture_descriptor(q.appearance);metadata=input_picture_descriptor(q.common.metadata,14)
            d['native_images']=[dict(slot='input.appearance',**appearance),dict(slot='input.metadata_mirror',**metadata)]
            d['image_mirror_consistent']=appearance['enabled']==metadata['enabled'] and appearance['picture']==metadata['picture']
        elif record.type_id==0x5027:
            q=ButtonArchive.parse(p);d.update(kind='button',caption=self.translate(q.caption.value),font=fonts(q.font)[0] if fonts(q.font) else {},ink=clr(q.caption_words[1]),picture=q.picture,source=q.release_script.value)
            d['native_images']=[dict(slot='button.old_picture',enabled=q.metadata.properties.words[0],picture=picture_descriptor(q.picture)),dict(slot='button.new_picture',enabled=q.metadata.properties.words[16],picture=picture_descriptor(q.metadata.properties.picture))]
            d['native_button_states']=button_states(q,self.translate)
            d['stored_two_state_style']=dict(states=d['native_button_states'],alignment_words_3_4=q.metadata.properties.words[3:5],paint_selector='native5ee240:0 vs nonzero; this page shows0')
        elif record.type_id in (0x5028,0x502a):
            q=MultiState.parse(record);d.update(kind='multi',multi=q,font={})
            d['native_images']=[dict(slot=f'multi.image_child_{n}',state=state,enabled=1,picture=picture_descriptor(ch.picture)) for state,children in enumerate(q.images) for n,ch in enumerate(children)]
        elif record.type_id==0x5009:
            r=Reader(cm.content);mode=r.u32();d.update(kind='picture',picture_name=r.cstring()[0] if mode==0x80 else None)
        elif record.type_id==0x503a:
            q=GroupArchive.parse(record);d.update(kind='group',children=q.children)
        elif record.type_id==0x502e:
            q=HistoryCurveStyle(cm.content);d.update(kind='history',history=q)
        elif record.type_id in (0x503c,0x5033):
            q=parse_legacy_style(record);d.update(kind='combo' if record.type_id==0x503c else 'savedata',legacy=q)
        elif record.type_id==0x503d:
            q=PluginControl.parse(p);d.update(kind='plugin',plugin_path=q.path,plugin_core=q.core)
            if 'DrawRecipe.ui' in q.path:
                rec=RecipeCore.parse(q.core);d.update(kind='table',recipe=rec,font=plugin_fonts(rec.fields['m4c_font'],True)[0],data_font=plugin_fonts(rec.fields['m54_font'],True)[0],row_height=rec.fields['m70'],header_fill=clr(rec.fields['m40']),header_ink=clr(rec.fields['m48']),row_fill=clr(rec.fields['m60']),alternate_fill=clr(rec.fields['m68']),row_ink=clr(rec.fields['m50']),grid=clr(rec.fields['m58']))
            elif 'XYPicture.ui' in q.path:
                xy=XYCore.parse(q.core);d.update(kind='xy',xy=xy,font=plugin_fonts(xy.fields['md4_font'],True)[0])
            elif 'AlarmTableView.ui' in q.path:
                alarm=AlarmStyle(q.core);fo={role:plugin_fonts(q.core[pos:pos+n],True)[0] for role,pos,n in alarm.fonts}
                d.update(kind='alarm',alarm=alarm,font=fo['title_font'],data_font=fo['body_font'])
        elif record.type_id in (0x5002,0x5004,0x5005):d['kind']='line' if record.type_id==0x5002 else 'shape'
        else:d['kind']='native'
        if descendant_style and d['kind'] in ('text','value','button','multi'):
            n=descendant_style.get('labels_height',22) if d['kind']=='text' else descendant_style.get('inputs_height',24)
            caption=d.get('caption','');available=d['rect'][2]-d['rect'][0]-4
            while n>18 and caption and fnt(n).getlength(caption)>available:n-=1
            d.update(font=dict(family='微软雅黑',height=n,weight=400),ink=descendant_style['ink'])
        d['caption']=self.translate(d.get('caption',''))
        d['image_semantic_hazards']=image_hazards(d.get('native_images',[]))
        for slot in d.get('native_images',[]):
            if slot.get('enabled') and slot['picture'].get('name') and slot['picture']['name'] not in self.assets:
                d['image_semantic_hazards'].append(dict(slot=slot.get('slot'),state=slot.get('state'),reason='enabled_reference_not_resolved_by_renderer',picture=slot['picture']))
        if d.get('image_mirror_consistent') is False:d['image_semantic_hazards'].append(dict(reason='input_image_enable_or_picture_mirrors_disagree'))
        return d

def render_project(project,out,window_ids=None):
    started=time.perf_counter()
    out=Path(out);out.mkdir(parents=True,exist_ok=True);results=[];models=[]
    for wid,w in sorted(project.windows.items()):
        if window_ids and wid not in window_ids:continue
        im=Image.new('RGB',(w['width'],w['height']),clr(w['bg']));layers=project.layers(wid);issues=[];opaque=[];buttons=[];tables=[];drawn=[];pictures_used=set();image_checks=[];paint_checks=[]
        def render_model(c,depth=0):
            if c is None:return
            x,y,r,b=c['rect'];kind=c['kind'];name=c['name'];ident=c['identity'];d=ImageDraw.Draw(im)
            if c.get('native_images') is not None:
                image_checks.append(dict(control=ident,rect=c['rect'],slots=c['native_images'],hazards=c['image_semantic_hazards'],stored_two_state_style=c.get('stored_two_state_style'),image_mirror_consistent=c.get('image_mirror_consistent')))
            if x>=im.width or y>=im.height or r<0 or b<0:return
            if r-x>25000 or b-y>25000:return
            drawn.append(dict(window=c['window'],name=name,type=hex(c['type']),rect=c['rect']))
            ff=c.get('font',{});h=ff.get('height',24);family=ff.get('family','微软雅黑');ink=c.get('ink',PALETTE['ink'])
            if kind=='picture':
                asset=project.assets.get(c.get('picture_name'))
                if asset and r>x and b>y:
                    pictures_used.add(c['picture_name'])
                    a=asset.resize((r-x,b-y));im.paste(a,(x,y),a)
            elif kind=='shape':
                fill=c.get('fill') if c['brush_enable'] and c['brush_style']==0 else None
                border=c.get('border') if c['pen_enable'] and c['pen_style']!=5 else None
                if c['brush_enable'] and c['brush_style'] not in (0,1):opaque.append(dict(control=ident,unsupported_common_brush_style=c['brush_style'],solid_color_not_assumed=True))
                if fill is not None or border is not None:d.rectangle((x,y,r,b),fill=fill,outline=border,width=max(1,min(3,c.get('pen_width',1))))
                paint_checks.append(dict(control=ident,kind=kind,brush_enable=c['brush_enable'],pen_enable=c['pen_enable'],fill_drawn=fill,border_drawn=border))
            elif kind=='line':
                if c['pen_enable'] and c['pen_style']!=5:d.line((x,y,r,b),fill=c.get('line_color',c['border']),width=c.get('line_width',max(1,min(3,c.get('pen_width',1)))))
            elif kind=='text':
                lf=c.get('fill') if c['brush_enable'] and c['brush_style']==0 else None
                lb=c.get('border') if c['pen_enable'] and c['pen_style']!=5 else None
                if lf is not None or lb is not None:d.rectangle((x,y,r,b),fill=lf,outline=lb)
                text(im,c['rect'],c.get('caption',''),h,ink,center=c.get('align')==1,right=c.get('align')==2,family=family,weight=ff.get('weight',400),issues=None if c.get('dynamic') else issues,identity=ident)
            elif kind=='value':
                frame=c['frame'];valid_frame=frame in (0,1,2)
                fill=c['fill'] if valid_frame and c['brush_enable'] else None
                border='#000000' if frame==1 else None
                if fill is not None or border is not None:d.rectangle((x,y,r,b),fill=fill,outline=border)
                if frame==2:
                    draw_edge(im,c['rect'],pressed=True)
                    opaque.append(dict(control=ident,native_input_DrawEdge_A_BF_RECT=True,system_3d_colors_and_pixels_approximated=True))
                paint_checks.append(dict(control=ident,kind=kind,native_frame=frame,valid_frame=valid_frame,brush_enable=c['brush_enable'],fill_drawn=fill,border_drawn=border,ink=ink))
                slot=c.get('native_images',[{}])[0]
                if slot.get('enabled') and slot['picture'].get('name') in project.assets:
                    nm=slot['picture']['name'];a=project.assets[nm].resize((max(1,r-x),max(1,b-y)));im.paste(a,(x,y),a);pictures_used.add(nm)
                text(im,c['rect'],c.get('caption','—'),h,'#9AA3AD' if c.get('disabled_grey') else ink,center=c.get('align')==1,family=family)
            elif kind=='button':
                state=c['native_button_states'][0]
                fill=state['fill'] if state['brush_enable'] and c['brush_style']==0 else None
                border=state['border'] if state['pen_enable'] and c['pen_style']!=5 else None
                if fill is not None or border is not None:d.rectangle((x,y,r,b),fill=fill,outline=border)
                if state['pen_enable'] and state['style'] in (0,1):
                    draw_edge(im,c['rect'],pressed=False)
                    opaque.append(dict(control=ident,native_button_DrawEdge_5_BF_RECT=True,system_3d_colors_and_pixels_approximated=True))
                slot=c['native_images'][state['image_slot']]
                if slot['enabled'] and slot['picture'].get('name') in project.assets:
                    nm=slot['picture']['name'];a=project.assets[nm].resize((max(1,r-x),max(1,b-y)));im.paste(a,(x,y),a);pictures_used.add(nm)
                ff=state['font'];text(im,c['rect'],state['caption'],ff.get('height',24),state['ink'],True,ff.get('family','微软雅黑'),ff.get('weight',400),issues,ident)
                paint_checks.append(dict(control=ident,kind=kind,state_selector=0,fill_drawn=fill,border_drawn=border,all_native_states=c['native_button_states'],common_colors_not_used_as_unconditional_fallback=True))
                buttons.append(dict(control=ident,rect=c['rect'],width=r-x,height=b-y))
            elif kind=='multi':
                q=c['multi'];state=0
                title=next((t.caption.value for state_texts in q.texts for t in state_texts),'')
                actualtitle=c.get('caption') or project.translate(title)
                # --active-map 规则：caption 相同、当前画面在 windows 里、且（给了 layer 时）按钮属于该公共层，就画激活态。
                for rule in project.active_rules:
                    if rule['caption']==actualtitle and wid in rule['windows'] and rule.get('layer',c['window'])==c['window']:
                        state=min(1,len(q.fills)-1);break
                packed=q.fills[state][0] if q.fills else None
                if packed==0x00010002:
                    pen=c['pen_enable'] and c['type']!=0x5028
                    d.rectangle((x,y,r,b),fill=clr(q.fills[state][1]),outline=c.get('border') if pen else None)
                    if c['pen_enable'] and not pen:paint_checks.append(dict(control=ident,kind='multi_common_pen',drawn=False,reason='0x5028 common 画笔原厂运行时不画'))
                elif packed is not None and packed&0xffff==2 and packed>>16==0:
                    # Stock hollow brush: second DWORD is not a solid fill.
                    d.rectangle((x,y,r,b),outline=c.get('border',PALETTE['line']))
                    opaque.append(dict(control=ident,type=hex(c['type']),state=state,packed_fill=packed,solid_color_not_used=True,stock_brush_and_pattern_boundary_approximated=True))
                else:
                    # Native 3D branch uses factory border/fill drawing.
                    d.rectangle((x,y,r,b),fill='#F0F0F0',outline='#A5A5A5')
                    d.line((x+1,b-1,x+1,y+1,r-1,y+1),fill='white')
                    opaque.append(dict(control=ident,type=hex(c['type']),state=state,packed_fill=packed,original_3d_fill_approximated=True,second_dword_not_claimed_as_solid_color=True))
                ow=q.common.rect[2]-q.common.rect[0];oh=q.common.rect[3]-q.common.rect[1]
                if q.images:
                    for ch in q.images[min(state,len(q.images)-1)]:
                        rr=Reader(ch.picture);mode=rr.u32();pic=rr.cstring()[0] if mode==0x80 else None;a=project.assets.get(pic)
                        if a:
                            pictures_used.add(pic)
                            a=a.resize((max(1,r-x),max(1,b-y)));im.paste(a,(x,y),a)
                groups=q.texts[min(state,len(q.texts)-1)] if q.texts else []
                for ch in groups:
                    local=ch.rect;cr=[x+round(local[0]*(r-x)/ow),y+round(local[1]*(b-y)/oh),x+round(local[2]*(r-x)/ow),y+round(local[3]*(b-y)/oh)]
                    cf=fonts(ch.font)[0] if fonts(ch.font) else {};cf=c.get('font') or cf
                    cap=c.get('caption') or project.translate(ch.caption.value);ci=clr(struct.unpack_from('<I',ch.tail,0)[0])
                    text(im,cr,cap,cf.get('height',24),ci,True,cf.get('family','微软雅黑'),cf.get('weight',400),issues,ident)
                    paint_checks.append(dict(control=ident,kind='multi_text',state=state,caption=cap,ink=ci,tail0_primary_color=struct.unpack_from('<I',ch.tail,0)[0],tail2_auxiliary_color=struct.unpack_from('<I',ch.tail,8)[0],navigation_state_is_route_simulation=True))
                if c['type']==0x5028:buttons.append(dict(control=ident,rect=c['rect'],width=r-x,height=b-y))
            elif kind=='group':
                for i,record in enumerate(c['children']):
                    child=project.native_model(record,c['window'],i,path=name+'/',group_rect=c['rect'],descendant_style=c.get('descendant_style'))
                    render_model(child,depth+1)
            elif kind=='table':
                q=c['recipe'];updates={v['index']:v for v in c.get('column_updates',[])};row=max(24,c['row_height']);cursor=x+1;visible=[]
                d.rectangle((x,y,r,b),fill=c.get('row_fill',PALETTE['white']),outline=c.get('grid',c['border']))
                for n,yy in enumerate(range(y+row,b,row)):
                    if n%2:d.rectangle((x+1,yy,r-19,min(b,yy+row)),fill=c.get('alternate_fill',c.get('row_fill',PALETTE['white'])))
                for i,col in enumerate(q.columns):
                    if not col.values[1]:continue
                    upd=updates.get(i,{});width=upd.get('width',col.values[2]);title=upd.get('title',col.title);end=cursor+width
                    d.rectangle((cursor,y+1,min(end,r-18),y+row),fill=c.get('header_fill',PALETTE['head']))
                    text(im,[cursor,y+1,min(end,r-18),y+row],title,h,c.get('header_ink',PALETTE['ink']),True,family,issues=issues,identity=ident+'/'+title)
                    d.line((cursor,y,cursor,b),fill=c.get('grid',PALETTE['line']));visible.append(dict(title=title,width=width));cursor=end
                for yy in range(y+row,b,row):d.line((x,yy,r-18,yy),fill=c.get('grid',PALETTE['line']))
                d.rectangle((r-18,y+1,r-1,b-1),fill='#ECECEC',outline='#A5A5A5')
                tables.append(dict(control=ident,rect=c['rect'],columns=visible,total_width=cursor-x-1,available_width=r-x-20,row_height=row,focus_row_fill=clr(q.fields['m78']),focus_cell_fill=clr(q.fields['m80']),focus_ink=clr(q.fields['m88']),data_font=c['data_font'],selection_not_exercised_with_runtime_data=True))
            elif kind=='xy':
                q=c['xy'];d.rectangle((x,y,r,b),fill=clr(q.tail['m5c']),outline=clr(struct.unpack_from('<I',q.tail['m4c'],12)[0]))
                gy=clr(struct.unpack_from('<I',q.fields['m8c'],12)[0]);gx=clr(struct.unpack_from('<I',q.fields['m64'],12)[0])
                for n in range(1,6):d.line((x+64,y+(b-y-32)*n/6,r-12,y+(b-y-32)*n/6),fill=gy)
                for n in range(1,9):d.line((x+64+(r-x-80)*n/9,y+8,x+64+(r-x-80)*n/9,b-28),fill=gx)
                text(im,[x+64,y+12,r-16,b-32],'计划曲线 · 动态数据占位',18,clr(q.fields['mbc']),True)
                text(im,[x+8,b-26,r-8,b],'0             时间 / 秒',18,clr(q.fields['me0']))
            elif kind=='alarm':
                q=c['alarm'];row=max(20,q.value('row_height'));head=clr(q.value('title_background'));grid=clr(q.value('grid_color'))
                d.rectangle((x,y,r,b),fill=clr(q.value('odd_background')),outline=grid)
                d.rectangle((x+1,y+1,r-1,min(b,y+row)),fill=head)
                for n,yy in enumerate(range(y+row,b,row)):
                    fill=clr(q.value('even_background' if n%2 else 'odd_background'))
                    d.rectangle((x+1,yy,r-1,min(b,yy+row)),fill=fill);d.line((x,yy,r,yy),fill=grid)
                opaque.append(dict(control=ident,type=hex(c['type']),path=c.get('plugin_path'),rect=c['rect'],internal_style_fields_read=True,column_definition_tail_opaque=True,columns_not_invented=True,field_colors={key:clr(q.value(key)) for key in ['title_background','title_text','odd_background','even_background','grid_color','focus_background','focus_text']}))
            elif kind=='history':
                q=c['history'];fields=q.fields();ink=clr(int.from_bytes(fields['1b0'],'little'));ff=fonts(fields['198'])[0]
                d.rectangle((x,y,r,b),fill=c['fill'],outline=c['border'])
                grid=clr(struct.unpack_from('<I',fields['fc'],12)[0])
                for n in range(1,7):d.line((x+68,y+50+(b-y-84)*n/7,r-24,y+50+(b-y-84)*n/7),fill=grid)
                for n in range(1,11):d.line((x+68+(r-x-92)*n/11,y+50,x+68+(r-x-92)*n/11,b-34),fill=grid)
                visible=[]
                for n in range(q.curve_count):
                    if int.from_bytes(fields[f'curve{n}_visible'],'little'):
                        title=project.translate(Reader(fields[f'curve{n}_name']).cstring()[0]);pen=clr(struct.unpack_from('<I',fields[f'curve{n}_pen'],12)[0]);visible.append((title,pen))
                for n,(title,pen) in enumerate(visible[:8]):
                    lx=x+24+n*(r-x-48)/max(1,len(visible[:8]));d.line((lx,y+22,lx+26,y+22),fill=pen,width=3)
                    text(im,[lx+30,y+8,lx+(r-x-48)/max(1,len(visible[:8]))-8,y+40],title,ff['height'],ink,family=ff['family'])
                text(im,[x+100,y+80,r-40,b-70],'原生趋势 · 动态曲线数据占位',22,ink,True)
                opaque.append(dict(control=ident,type=hex(c['type']),internal_style_fields_read=True,grid_font_trace_styles_read=True,dynamic_trace_data_not_generated=True,axis_pixel_placement_approximated=True))
            elif kind=='combo':
                q=c['legacy'];v=q.values;fh=fonts(v['mfc_font'])[0];closed_height=v['m12c']
                rr=[x,y,r,min(b,y+closed_height)]
                d.rectangle(rr,fill=clr(v['mf0']),outline=c['border']);text(im,[x+4,y,r-28,rr[3]],'—',fh['height'],clr(v['mf8']),family=fh['family'])
                mid=(rr[1]+rr[3])/2;d.polygon([(r-20,mid-3),(r-8,mid-3),(r-14,mid+4)],fill=clr(v['mf8']))
                opaque.append(dict(control=ident,type=hex(c['type']),internal_style_fields_read=True,dropdown_chrome_approximated=True,full_rect_includes_dropdown_extent=True,closed_row_height=closed_height))
            elif kind=='savedata':
                q=c['legacy'];v=q.values;tx,ty,tr,tb=v['m2a8'];row=v['m204'];hf=fonts(v['m210_font'])[0]
                d.rectangle((x,y,r,b),fill=c['fill'],outline=c['border']);d.rectangle((tx,ty,tr,tb),fill=clr(v['m25c']),outline=clr(v['m268']))
                for n,yy in enumerate(range(ty+row,tb,row)):
                    d.rectangle((tx+1,yy,tr-1,min(tb,yy+row)),fill=clr(v['m278'] if n%2 else v['m25c']));d.line((tx,yy,tr,yy),fill=clr(v['m268']))
                cursor=tx+1;columns=[]
                for col in q.metadata['columns']:
                    end=cursor+col['width'];title=project.translate(col['texts'][1]);limit=min(end,tr-18)
                    if limit>cursor:
                        d.rectangle((cursor,ty+1,limit,ty+row),fill=clr(v['m240']));text(im,[cursor,ty+1,limit,ty+row],title,hf['height'],clr(v['m248']),True,hf['family'],issues=issues,identity=ident+'/'+title)
                        d.line((cursor,ty,cursor,tb),fill=clr(v['m268']))
                    columns.append(dict(title=title,width=col['width']));cursor=end
                tables.append(dict(control=ident,rect=[tx,ty,tr,tb],columns=columns,total_width=cursor-tx-1,available_width=tr-tx-20,row_height=row,preserved_native_column_widths=True))
                opaque.append(dict(control=ident,type=hex(c['type']),internal_style_fields_read=True,selection_colors_read=True,column_title_source='metadata.columns[*].texts[1]，原生列定义保留',native_data_not_generated=True))
            else:
                d.rectangle((x,y,r,b),fill=c.get('fill',PALETTE['field']),outline=c.get('border',PALETTE['line']))
                labels={0x502e:'原生趋势区域',0x5033:'原生统计表区域',0x503c:'原生选择列表'}
                title=labels.get(c['type'],'原生报警浏览区域' if 'Alarm' in c.get('plugin_path','') else '原生构件区域')
                text(im,[x+8,y+8,r-8,min(b,y+44)],title,20,PALETTE['muted'])
                if b-y>80:text(im,[x+8,y+44,r-8,min(b,y+80)],'仅显示已读取的边界；内部绘制待原生主题字段复读',18,PALETTE['muted'])
                opaque.append(dict(control=ident,type=hex(c['type']),path=c.get('plugin_path'),rect=c['rect'],internal_drawing_approximated=True))
        for lid in layers:
            layer=project.windows[lid]
            for i,record in enumerate(layer['controls']):
                try:render_model(project.native_model(record,lid,i))
                except Exception as e:project.read_errors.append(dict(window=lid,index=i,error=str(e)))
        canvas=Image.new('RGB',(im.width,im.height+88),'white');canvas.paste(im,(0,0))
        mode='候选原生块字段' if project.is_candidate else '实际工程导出字段'
        text(canvas,[16,im.height+4,im.width-16,im.height+40],f'{wid:02d} {w["name"]} · 公共层 '+','.join(map(str,layers))+f' · {mode}',20,PALETTE['muted'])
        text(canvas,[16,im.height+42,im.width-16,im.height+82],'离线字段渲染，非原厂截图 · 动态值均为占位 · 原生内部构件/滚动条绘制近似处已列报告',19,PALETTE['muted'])
        fn=out/f'{wid:02d}_{w["name"]}.png';canvas.save(fn)
        results.append(dict(id=wid,name=w['name'],image=str(fn),layers=layers,own_control_count=len(w['controls']),rendered_control_records=len(drawn),fixed_text_overflow=issues,tables=tables,touch_controls=buttons,pictures_used=sorted(pictures_used),native_image_gate_checks=image_checks,native_paint_checks=paint_checks,opaque_internals=opaque))
    thumbs=[];tw=480;th=320;cols=4
    for page in results:
        full=Image.open(page['image']).convert('RGB');thumb=Image.new('RGB',(tw,th),'white');full.thumbnail((tw,th-34));thumb.paste(full,((tw-full.width)//2,34))
        structural=' · 结构窗' if not page['own_control_count'] else ''
        text(thumb,[8,0,tw-8,32],f'{page["id"]:02d} {page["name"]}'+structural,20,PALETTE['ink']);thumbs.append(thumb)
    contact=Image.new('RGB',(cols*tw,math.ceil(len(thumbs)/cols)*th),'#D7E2EB')
    for n,thumb in enumerate(thumbs):contact.paste(thumb,((n%cols)*tw,(n//cols)*th))
    sheet=out/('全部窗口_公共层合成总览.png' if window_ids is None else '指定窗口_公共层合成总览.png');contact.save(sheet)
    used_assets=set(n for p in results for n in p['pictures_used'])
    image_map={q['control']:q for p in results for q in p['native_image_gate_checks']}
    report=dict(input_sha256=project.input_sha,source_export_folder=str(project.export),source_index_sha256=project.index_sha,source_window_blob_sha256={str(i):w['source_sha'] for i,w in project.windows.items()},renderer_sha256=sha(Path(__file__).read_bytes()),phase='candidate_native_blocks' if project.is_candidate else 'actual_native_export',language_table_loaded=bool(project.language),active_rules=project.active_rules,actual_mcs_reread=not project.is_candidate,window_count=len(results),
                all_pages=results,contact_sheet=str(sheet),read_errors=project.read_errors,picture_assets_loaded=len(project.assets),asset_decode_limits=project.asset_errors,vector_asset_render_approximations=project.asset_render_limits,used_picture_assets=sorted(used_assets),visible_asset_render_approximations=[v for v in project.asset_render_limits if v['picture_name'] in used_assets],
                native_image_semantics=dict(enable_flags_followed=True,unique_control_checks=list(image_map.values()),hazards=[dict(control=k,**v) for k,q in image_map.items() for v in q['hazards']],native_check_result_not_inferred_from_pixels=True),
                native_paint_semantics=dict(standard_button_two_state_selector_indexes=[8,9,10,11],standard_default_state_color_indexes=[6,7,5],input_color_and_frame_indexes=[0,1,2],input_frame1_border='native fixed black',multi_primary_ink='childtail DWORD0',common_enable_words_respected=True,navigation_active_state='按 --active-map 规则模拟，未执行原生表达式；无规则时全部画常态',multi_5028_common_pen='不画（原厂运行时不画）',draw_edge_pixels='原生分支已证，系统3D颜色与像素为静态近似，未伪作flat',text_alignment='Label/Input水平垂直对齐、字形与裁切仍为静态近似；MCS原对齐字段完整保留，不能据此图认定像素一致',disabled_state='安全条件、变灰/隐藏政策未执行，使用正常静态色；运行条件可能改变文字显示'),
                original_empty_structural_windows=[dict(id=w['id'],name=w['name'],own_control_count=0,parents=w['parents'],note='原工程本窗无独立控件；渲染其原公共层，不新增虚构业务功能') for w in project.windows.values() if not w['controls']],
                control_type_counts=dict(Counter(hex(c.type_id) for w in project.windows.values() for c in w['controls'])),
                dynamic_values='—占位，未执行事件或读取设备',gui=False,mcs_written=False,native_runtime_screenshot=False,
                limits='已证原生颜色、字体、表格列宽及行高均读取实际字段；趋势轴精确像素定位、报警不透明列定义和系统滚动条外观采用明确标注的静态近似。无设备运行数据，不能证明实际GUI/运行表现。')
    report.update(requested_windows=project.requested_windows,parsed_window_count=len(project.windows),total_window_count=project.total_window_count,
                  svg_batch_count=project.svg_batch_count,
                  timings_ms={'load':project.load_ms,'render':round((time.perf_counter()-started)*1000,3)})
    dump(out/'离线渲染报告.json',report)
    cards=[]
    for page in results:
        fn=Path(page['image']).name;title=html.escape(f'{page["id"]:02d} {page["name"]}')
        note=f'独立控件 {page["own_control_count"]} · 公共层 '+','.join(map(str,page['layers']))
        if not page['own_control_count']:note+=' · 原工程结构窗'
        cards.append(f'<article><h2>{title}</h2><p>{html.escape(note)}</p><a href="{html.escape(fn,quote=True)}"><img loading="lazy" src="{html.escape(fn,quote=True)}" alt="{title}"></a></article>')
    gallery='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>离线预览</title><style>body{font:16px Microsoft YaHei,sans-serif;background:#edf4f9;color:#233748;margin:24px}header{max-width:1200px;margin:auto}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(460px,1fr));gap:20px}article{background:white;padding:16px;border:1px solid #a7bdcd}h2{font-size:22px;margin:0 0 8px}p{color:#5f7282;margin:0 0 12px}img{width:100%;display:block}a{color:#236fae}</style><header><h1>离线预览</h1><p>按实际原生字段递归合成公共窗口。点击各图查看完整尺寸。动态值均为占位；原工程无独立控件的结构窗保留原公共层组合。</p><p>离线字段渲染，非原厂截图。内部样式来自已证字段；趋势轴定位、报警不透明列定义与系统滚动条等绘制近似处已在渲染报告标记。此索引不代表GUI或运行验收。</p><p><a href="'+html.escape(Path(sheet).name,quote=True)+'">打开缩略总览</a> · <a href="离线渲染报告.json">读取字段与边界说明</a></p></header><main>'+''.join(cards)+'</main></html>'
    (out/'全工程预览索引.html').write_text(gallery,'utf-8')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description='只读导出目录，按原生字段离线画出窗口；不打开数据库、不启动厂商程序。')
    p.add_argument('--export-dir',type=Path,required=True,help='run.ps1 inspect 的导出，或候选导出')
    p.add_argument('--full-dir',type=Path,help='取多语言表和图片的导出，默认与 --export-dir 相同')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--windows',type=int,nargs='+',help='只画这些窗口号（公共层会一起合成）')
    p.add_argument('--active-map',type=Path,help='导航激活规则 JSON：[{"caption":"设备","windows":[2],"layer":1}, ...]')
    a=p.parse_args()
    if a.output.exists() and any(a.output.iterdir()):raise SystemExit('输出目录必须是新目录或空目录')
    rules=json.loads(a.active_map.read_text('utf-8-sig')) if a.active_map else []
    r=render_project(Project(a.export_dir,a.full_dir,rules,a.windows),a.output,a.windows)
    print(json.dumps(dict(windows=r['window_count'],contact_sheet=r['contact_sheet'],read_errors=r['read_errors'],assets=r['picture_assets_loaded'],language_table_loaded=r['language_table_loaded'],phase=r['phase']),ensure_ascii=False,indent=2))
