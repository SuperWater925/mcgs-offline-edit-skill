"""CDrawHisPic 352.1 style spans, proven from native writer 90a3c0.

Four LOGPENs, CMcgsFont/ink pairs and the sixteen trace LOGPENs are
independent visual fields. Sources, ranges, selected-point outputs, IDs,
times, flags and the entire remaining archive are preserved as raw slices.
90a3c0 store order; trace 914fb0 + base915130; 904aee/90589b feed the
two ink members to CDC virtual+38 SetTextColor. No vendor code executes.
"""
from dataclasses import dataclass
import struct
from 原生界面样式 import Reader,CString,Array,_font,set_font,fonts

@dataclass
class Span:
 name:str
 raw:bytes
 kind:str
 offset:int

class HistoryCurveStyle:
 def __init__(self,data):
  self.original=bytes(data);self.spans=[];r=Reader(data)
  def take(name,kind):
   start=r.pos
   if kind=='s':CString.parse(r)
   elif kind=='f':_font(r)
   elif kind=='p':r.take(16)
   elif kind=='a':Array.parse(r,True)
   else:r.take(4)
   self.spans.append(Span(name,data[start:r.pos],kind,start))
  take('bindings','a')
  for key in ('fc','10c','11c','12c'):take(key,'p')
  take('4c','s')
  for key in ('13c','140','144','148','14c','150','154'):take(key,'i')
  take('158','s');take('15c','i')
  for key in ('160','164','168','16c','170','174','178','17c'):take(key,'s')
  take('198','f');take('1b0','i');take('1b4','s')
  for key in ('1b8','1bc','1c0','1c4','1c8','1cc','1d0','1d4','1d8','1dc','1e0','1e4'):take(key,'i')
  take('1e8','f');take('200','i');take('curve_count','i')
  self.curve_count=int.from_bytes(self.spans[-1].raw,'little')
  if self.curve_count!=16:raise ValueError('Unproven CDrawHisPic trace count')
  for j in range(self.curve_count):
   for key,kind in [('nativeKey','s'),('name','s'),('type','i'),('id','i'),('visible','i'),('source','s'),('unit','s'),('datatype','i'),('min','s'),('max','s'),('output','s'),('reserved','i'),('reserved2','i'),('pen','p')]:take(f'curve{j}_{key}',kind)
  self.spans.append(Span('opaque_tail',data[r.pos:],'b',r.pos))
  assert self.to_bytes()==data
 def to_bytes(self):return b''.join(s.raw for s in self.spans)
 def fields(self):return {s.name:s.raw for s in self.spans}
 def style(self,*,ink,line,color_map,font_height=20):
  allowed={'fc','10c','11c','12c','198','1b0','1e8','200'}|{f'curve{j}_pen' for j in range(16)};changes=[]
  for s in self.spans:
   old=s.raw
   if s.kind=='f':s.raw=set_font(old,height=font_height,family='微软雅黑',weight=400)
   elif s.name in ('1b0','200'):s.raw=struct.pack('<I',ink)
   elif s.name in ('fc','10c','11c','12c'):
    pen=list(struct.unpack('<4I',old));pen[3]=line;s.raw=struct.pack('<4I',*pen)
   elif s.name.startswith('curve') and s.kind=='p':
    pen=list(struct.unpack('<4I',old));pen[3]=color_map(pen[3]);s.raw=struct.pack('<4I',*pen)
   if s.raw!=old:changes.append(dict(field=s.name,old_offset=s.offset,before_hex=old.hex(),after_hex=s.raw.hex()))
   assert s.name in allowed or s.raw==old
  result=self.to_bytes();check=HistoryCurveStyle(result)
  before=HistoryCurveStyle(self.original).fields();after=check.fields()
  assert before.keys()==after.keys()
  assert all(before[k]==after[k] for k in before if k not in allowed)
  return result,dict(changes=changes,allowed_fields=sorted(allowed),business_fields_identical=True,opaque_tail_identical=True)
