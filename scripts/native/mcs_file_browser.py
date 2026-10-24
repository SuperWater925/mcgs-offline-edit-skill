"""FileBrowser.ui schema 0xA codec from offline serializer/constructor evidence.

No vendor library is imported or executed. No native FileBrowser instance was
found in installed samples: generation is supported by editor write/read and
runtime-reader evidence, not a claim of successful vendor compilation.
"""
from dataclasses import dataclass
from pathlib import Path
import copy
import hashlib
import json
import struct
import sys

HERE=Path(__file__).resolve().parent
from mcs_window_archive import Reader,WindowArchive,write_cstring
from mcs_plugin_controls import PluginControl,RecipeCore,utf8_read,utf8_write,buffer_read,buffer_write

NATIVE_PATH='@\\ActiveX\\用户定制构件\\文件浏览器构件\\FileBrowser.ui#文件浏览器[3.52]'

@dataclass
class FileBrowserCore:
    header:bytes
    fields:dict
    # DrawFileBrowser::Serialize 0x10004e70 calls base 0x1001ddc0, then
    # SerializeNew 0x100064b0. Write branch 64cf..6821; read 6826..6b65.
    # UTF8 helper 1d630/1d700; int/color 1d350/1d410 and 1d380/1d440.
    SPEC=(('m34_font','bytes'),('m38_font','bytes'),('m3c_font','bytes'),
          ('m58','i'),('m5c','i'),('m60','i'),('m64','i'),('m68','i'),('m6c','i'),('m70','i'),('m74','i'),('m78','i'),('m7c','i'),('m80','i'),('m88','i'),
          ('m40','str'),('m44','str'),('m48','str'),
          ('m138','i'),('m13c','i'),('m140','i'),('m144','i'),('m148','i'),('m14c','i'),('m150','i'),('m154','i'),('m158','i'),
          ('mb8','i'),('m94','i'),('m98','i'),
          ('ma4','i'),('ma0','str'),('mac','i'),('ma8','str'),('mb4','i'),('mb0','str'),
          ('m9c','i'),('mbc','str'),('mc0_cache','bytes'))
    @classmethod
    def parse(cls,data):
        r=Reader(data);header=r.take(20)
        if struct.unpack_from('<I',header,16)[0]!=0xa:raise ValueError('Only statically proven FileBrowser schema 0xA is supported')
        values={}
        for key,kind in cls.SPEC:
            values[key]=r.unpack('<i') if kind=='i' else utf8_read(r) if kind=='str' else buffer_read(r)
        if r.pos!=len(data):raise ValueError(f'Unparsed FileBrowser bytes {r.pos}/{len(data)}')
        return cls(header,values)
    def to_bytes(self):
        out=self.header
        for key,kind in self.SPEC:
            value=self.fields[key]
            out+=struct.pack('<i',value) if kind=='i' else utf8_write(value) if kind=='str' else buffer_write(value)
        return out
