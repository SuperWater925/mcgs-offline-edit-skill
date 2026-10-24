"""已实证MCGSZIPE+双原文长度+标准zlib的纯文件封装；不执行厂商代码。"""
import struct
import zlib


MARKER=b'MCGSZIPE'
MAX_PLAIN=64*1024*1024


def unpack(raw):
    if raw[:8]!=MARKER:raise ValueError('本轮要求保留用户原厂MCGSZIPE封装')
    if len(raw)<18:raise ValueError('MCGSZIPE块过短')
    first,second=struct.unpack('<2I',raw[8:16])
    if first!=second or not 0<first<=MAX_PLAIN:raise ValueError('MCGSZIPE双长度不一致或越界')
    if raw[16:18]!=b'\x78\x01':raise ValueError('未验证的原厂zlib压缩级别头')
    decoder=zlib.decompressobj();plain=decoder.decompress(raw[16:],first+1)
    if len(plain)>first or decoder.unconsumed_tail:raise ValueError('实际解压长度超过声明')
    plain+=decoder.flush()
    if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail or len(plain)!=first:
        raise ValueError('MCGSZIPE解压eof/尾部或长度不符')
    return plain


def pack(plain):
    if not 0<len(plain)<=MAX_PLAIN:raise ValueError('归档长度越界')
    raw=MARKER+struct.pack('<2I',len(plain),len(plain))+zlib.compress(plain,1)
    if unpack(raw)!=plain:raise ValueError('MCGSZIPE压缩封装回环失败')
    return raw
