"""McgsPro 3.5.1 native project fields. Pure in-memory file editing."""
import base64
import math
import struct


def binary(value):
    return base64.b64decode(value['binary'], validate=True)


def wrap(value):
    return {'binary': base64.b64encode(value).decode('ascii')}


def u32(b, p):
    if p < 0 or p + 4 > len(b):
        raise ValueError('Truncated integer')
    return struct.unpack_from('<I', b, p)[0]


def string(b, p):
    def take(n):
        nonlocal p
        if n < 0 or p < 0 or p+n > len(b):
            raise ValueError('Truncated text')
        v = b[p:p+n]; p += n
        return v
    width = 1
    n = int.from_bytes(take(1), 'little')
    if n == 255:
        n = int.from_bytes(take(2), 'little')
        if n == 65534:
            width = 2; n = int.from_bytes(take(1), 'little')
            if n == 255:
                n = int.from_bytes(take(2), 'little')
        if n == 65535:
            n = int.from_bytes(take(4), 'little')
    return take(n*width).decode('utf-16le' if width == 2 else 'gbk'), p


def text(value):
    if not isinstance(value, str) or '\x00' in value:
        raise ValueError('Text must be a string without NUL')
    b = value.encode('utf-16le'); n = len(b)//2
    if n >= 65535:
        raise ValueError('Text too long')
    return b'\xff\xfe\xff' + (bytes([n]) if n < 255 else b'\xff'+struct.pack('<H', n)) + b


def window(b):
    title, pos = string(b, 12)
    if title != 'MCGS-SET DOCUMENT;VERSION 01.00':
        raise ValueError('Unsupported native document')
    count_pos = pos; count = u32(b, pos); pos += 4
    if count > (len(b)-pos)//6:
        raise ValueError('Invalid record count')
    records = []
    for _ in range(count):
        kind, size = struct.unpack_from('<IH', b, pos); pos += 6
        if size == 65535:
            size = u32(b, pos); pos += 4
        if not 0x5000 <= kind < 0x6000 or pos+size > len(b):
            raise ValueError('Invalid control frame')
        records.append((kind, b[pos:pos+size])); pos += size
    if u32(b, pos)+10 != len(b)-pos:
        raise ValueError('Invalid page property extent')
    return b[:count_pos], records, b[pos:]


def pack_window(header, records, trailer):
    result = header + struct.pack('<I', len(records))
    for kind, payload in records:
        result += (struct.pack('<IH', kind, len(payload)) if len(payload) < 65535
                   else struct.pack('<IHI', kind, 65535, len(payload))) + payload
    result += trailer
    window(result)
    return result


def bounds(value):
    if not isinstance(value, list) or len(value) != 4 or any(type(x) is not int or abs(x)>32768 for x in value):
        raise ValueError('Bounds require four bounded integers')
    if value[0] >= value[2] or value[1] >= value[3]:
        raise ValueError('Positive control dimensions required')
    return struct.pack('<4i', *value)


def common(b):
    if len(b) < 70 or b[5] not in (0, 1):
        raise ValueError('Unsupported common control')
    p = 12
    if b[5]:
        _, p = string(b, p+8)
    name_pos = p+54
    name, end = string(b, name_pos)
    if not name or len(name)>256:
        raise ValueError('Unsupported control name')
    return {'bounds': list(struct.unpack_from('<4i', b, p)), 'bounds_pos': p,
            'name': name, 'name_pos': name_pos, 'name_end': end}


def edit_control(kind, b, edits):
    expected={0x5008:321.1,0x5002:1.0,0x5004:1.0,0x5025:325.1}
    if kind not in expected or b[:4]!=struct.pack('<f',expected[kind]):
        raise ValueError('Unsupported control class/version for editing')
    c = common(b); changes = []
    if 'bounds' in edits:
        changes.append((c['bounds_pos'], c['bounds_pos']+16, bounds(edits['bounds'])))
    if 'name' in edits:
        changes.append((c['name_pos'], c['name_end'], text(edits['name'])))
    if 'text' in edits:
        if kind != 0x5008 or u32(b, c['name_end']) != 12 or b[c['name_end']+12:c['name_end']+14] != bytes(2):
            raise ValueError('Text editing requires a static label')
        start = c['name_end']+14; _, end = string(b, start)
        changes.append((start, end, text(edits['text'])))
    if 'binding' in edits or 'minimum' in edits or 'maximum' in edits:
        if kind != 0x5025:
            raise ValueError('Binding/range editing requires numeric input')
        start = c['name_end']
        extent = struct.unpack_from('<H',b,start)[0]
        if extent < 16 or start+extent+32 > len(b) or b[start+4:start+12] not in (bytes.fromhex('72005700fd070000'),bytes.fromhex('0000000003000000')):
            raise ValueError('Unsupported numeric input property frame')
        fixed_at = start+extent+4
        binding_at = fixed_at+28
        old, end = string(b, binding_at)
        if not old:
            raise ValueError('Numeric input has no direct binding')
        if 'binding' in edits:
            changes.append((binding_at, end, text(edits['binding'])))
            # Name binding is consumed by the official input loader; exact ID
            # placement is validated against the template and supplied explicitly.
            ident = edits.get('binding_id')
            if type(ident) is not int or ident < 0:
                raise ValueError('A matching binding_id is required')
            changes.append((fixed_at+20, fixed_at+24, struct.pack('<I', ident)))
        high, low = struct.unpack_from('<2f', b, end)
        low = edits.get('minimum', low); high = edits.get('maximum', high)
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (low, high)) or low>high:
            raise ValueError('Invalid input range')
        changes.append((end, end+8, struct.pack('<2f', high, low)))
    allowed = {'bounds','name','text','binding','binding_id','minimum','maximum'}
    if set(edits)-allowed or not changes:
        raise ValueError('Unknown or empty control edit')
    for a, z, value in sorted(changes, reverse=True):
        b = b[:a]+value+b[z:]
    common(b)
    return b


def page_properties(trailer, *, ident=None, name=None, width=None, height=None):
    if trailer[4:12] != bytes.fromhex('0200000000c21500') or struct.unpack_from('<H', trailer, 12)[0] != 3:
        raise ValueError('Unsupported page properties')
    b = bytearray(trailer)
    if ident is not None:
        struct.pack_into('<I', b, 14, ident)
    pos = 18
    fields = []
    for _ in range(3):
        if struct.unpack_from('<H', b, pos)[0] != 8:
            raise ValueError('Unsupported page text variant')
        size = u32(b, pos+2); fields.append((pos, pos+6+size)); pos += 6+size
    if width is not None or height is not None:
        for index, val in ((2,width),(3,height)):
            if val is not None:
                if type(val) is not int or not 1 <= val <= 16384:
                    raise ValueError('Invalid page size')
                struct.pack_into('<I', b, pos+index*6+2, val)
    if name is not None:
        raw = name.encode('utf-16le'); a,z = fields[0]
        b[a:z] = struct.pack('<HI',8,len(raw))+raw
    struct.pack_into('<I', b, 0, len(b)-10)
    return bytes(b)


def variables(blob):
    if len(blob)<12 or struct.unpack_from('<f',blob)[0] != 12.0 or u32(blob,4) != len(blob)-8:
        raise ValueError('Unsupported variable document')
    count=u32(blob,8); pos=12; rows=[]
    if count > len(blob)//100:
        raise ValueError('Invalid variable count')
    for ident in range(count):
        name,pos=string(blob,pos);note,pos=string(blob,pos);unit,pos=string(blob,pos)
        start=pos;kind=u32(blob,pos)
        if kind not in (1,2,3,0xffffffff):
            raise ValueError('Unsupported variable type')
        _, middle=string(blob,pos+36);initial,end=string(blob,middle+28)
        if end+24>len(blob) or u32(blob,end+12)!=ident:
            raise ValueError('Variable identity mismatch')
        prefix=blob[start:end+24]; pos=end+24; extension_start=pos
        for group_index in range(2):
            n=u32(blob,pos); pos+=4+4*n
            if n>count or pos>len(blob):
                raise ValueError('Invalid variable group vector')
            if group_index==0:
                enabled=u32(blob,pos);pos+=4
                if enabled not in (0,1):raise ValueError('Invalid alarm flag')
                if enabled:
                    alarms=u32(blob,pos);pos+=4
                    if alarms>len(blob)//44:raise ValueError('Invalid alarm count')
                    for _ in range(alarms):_,pos=string(blob,pos+40)
        _,pos=string(blob,pos)
        rows.append({'id':ident,'name':name,'note':note,'unit':unit,'kind':kind,
                     'initial':initial,'prefix':prefix,'extension':blob[extension_start:pos]})
    if pos!=len(blob) or len({r['name'] for r in rows})!=count:
        raise ValueError('Variable extent or duplicate name')
    return rows


def pack_variables(rows):
    body=b''
    for i,row in enumerate(rows):
        prefix=row['prefix'];_,middle=string(prefix,36);_,end=string(prefix,middle+28)
        prefix=bytearray(prefix[:middle+28]+text(row['initial'])+prefix[end:])
        _,new_end=string(prefix,middle+28);struct.pack_into('<I',prefix,new_end+12,i)
        body+=text(row['name'])+text(row['note'])+text(row['unit'])+bytes(prefix)+row['extension']
    result=struct.pack('<fII',12.,len(body)+4,len(rows))+body
    variables(result)
    return result
