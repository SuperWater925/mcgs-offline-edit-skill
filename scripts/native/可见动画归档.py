"""Pure offline CAniVisible singleton factory for proven native controls.

Disk format is CAni's old serializer: float32, CString expression; Visible
then writes DWORD condition. No vendor code, GUI, or runtime is invoked.
mode 0 is proven by CAniVisiblePage DDX_Radio 0x42b and RT_DIALOG 0x77b:
the first radio is Visible, the second is Invisible when expression != 0.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import copy
import hashlib
import json
import struct
import sys

from mcs_window_archive import ControlRecord, Reader, WindowArchive, FormatError, write_count, write_cstring

ROOT = Path(__file__).resolve().parent
CLASS_HEADER = b"\xff\xff\x00\x00\x0b\x00CAniVisible"
DEFAULT_FLOAT = struct.pack("<f", 1.0)  # CAni ctor 5c3653, constant 1077a44.
SUPPORTED_TYPES = (0x5004, 0x5008, 0x5025, 0x503d)


@dataclass
class VisibleObject:
    header: bytes
    float_raw: bytes
    expression: str
    original_expression: str
    expression_raw: bytes
    wide: bool
    mode: int

    @classmethod
    def parse(cls, r):
        header = r.take(len(CLASS_HEADER))
        if header != CLASS_HEADER:
            raise FormatError("Only a new-map CAniVisible singleton is supported")
        opaque = r.take(4)
        expression, raw, wide = r.cstring()
        mode = r.u32()
        if mode not in (0, 1):
            raise FormatError("Unproven CAniVisible mode")
        return cls(header, opaque, expression, expression, raw, wide, mode)

    @classmethod
    def new(cls, expression):
        raw = write_cstring(expression)
        return cls(CLASS_HEADER, DEFAULT_FLOAT, expression, expression, raw, True, 0)

    def to_bytes(self):
        expression = self.expression_raw if self.expression == self.original_expression else write_cstring(self.expression, self.wide)
        return self.header + self.float_raw + expression + struct.pack("<I", self.mode)


def _common_array(record):
    if record.type_id not in SUPPORTED_TYPES:
        raise FormatError(f"Control {record.type_id:#x} common prefix is not proven for this factory")
    r = Reader(record.payload)
    version = r.unpack("<f")
    if (record.type_id in (0x5004, 0x503d) and version != 1.0) or (record.type_id in (0x5008, 0x5025) and not 250 <= version <= 400):
        raise FormatError("Unsupported native control version")
    flags, flags2 = r.u32(), r.u32()
    if flags & 0x100:
        r.take(8)
        r.cstring()
    rect_offset = r.pos
    r.take(16 + 18 + 14)
    count_start = r.pos
    count = r.count()
    count_end = r.pos
    obj = None
    if count == 1:
        obj = VisibleObject.parse(r)
    elif count:
        raise FormatError("Existing nonempty animation array is not synthesized or altered")
    array_end = r.pos
    base_word = r.u16()
    base_flags = r.u16()
    name, _, _ = r.cstring()
    metadata, _ = r.byte_array()
    return dict(count_start=count_start, count_end=count_end, array_end=array_end,
                count=count, object=obj, base_word=base_word, base_flags=base_flags,
                name=name, rect_offset=rect_offset, content_offset=r.pos,
                version=version, flags=flags, flags2=flags2, metadata_bytes=len(metadata))


def 添加可见条件(control_record, expression):
    """Attach one native Visible animation to an empty animation array.

    expression != 0 shows the control. The new expression needs native
    compilation; common +0xb0 bit 0 is set exactly as native property Apply.
    Existing animations are rejected to avoid changing CArchive class maps.
    The returned ControlRecord has an in-memory restore token for exact undo.
    """
    if not isinstance(expression, str) or not expression.strip() or "\0" in expression:
        raise ValueError("Visibility expression must be nonempty native source")
    info = _common_array(control_record)
    if info["count"]:
        raise FormatError("Add visibility only to a control whose animation array is empty")
    start, end = info["count_start"], info["array_end"]
    data = control_record.payload
    animation = write_count(1) + VisibleObject.new(expression).to_bytes()
    result = copy.deepcopy(control_record)
    result.payload = (data[:start] + animation + struct.pack("<H", info["base_word"] | 1) + data[end + 2:])
    result._mcgs_visible_restore = dict(empty_array=data[start:end], base_word=data[end:end + 2])
    return result


def 剥除可见条件(control_record, original_control=None):
    """Undo a singleton added by this module, preserving all other fields.

    For a record reparsed from disk, supply the original empty-animation
    control explicitly because a saved archive cannot encode its prior dirty
    flag. No private restoration bytes are written into the native payload.
    """
    info = _common_array(control_record)
    if info["count"] != 1:
        raise FormatError("Expected one native Visible animation")
    if original_control is not None:
        if original_control.type_id != control_record.type_id:
            raise FormatError("Original control type differs")
        before = _common_array(original_control)
        if before["count"]:
            raise FormatError("Original control animation array must be empty")
        raw = original_control.payload
        restore = dict(empty_array=raw[before["count_start"]:before["array_end"]],
                       base_word=raw[before["array_end"]:before["array_end"] + 2])
    else:
        restore = getattr(control_record, "_mcgs_visible_restore", None)
        if restore is None:
            raise FormatError("Reparsed records need their original control for exact dirty-flag restoration")
    start, end = info["count_start"], info["array_end"]
    result = copy.deepcopy(control_record)
    result.payload = (control_record.payload[:start] + restore["empty_array"] +
                      restore["base_word"] + control_record.payload[end + 2:])
    if hasattr(result, "_mcgs_visible_restore"):
        del result._mcgs_visible_restore
    return result


def 读取可见条件(control_record):
    info = _common_array(control_record)
    obj = info["object"]
    return dict(name=info["name"], count=info["count"], expression=obj.expression if obj else None,
                mode=obj.mode if obj else None, nonzero_visible=(obj.mode == 0) if obj else None,
                initial_float_bits=obj.float_raw.hex() if obj else None,
                base_word=info["base_word"])


def 去可见条件供解析(control_record):
    """Return (no-animation copy, expression) for existing native field readers.

    This is a read/inspection projection, not an exact undo: the current
    base dirty word is preserved. Use 剥除可见条件 with the origin token or
    original control when exact historical bytes must be restored.
    """
    info = _common_array(control_record)
    result = copy.deepcopy(control_record)
    if not info["count"]:
        return result, None
    start, end = info["count_start"], info["array_end"]
    result.payload = control_record.payload[:start] + write_count(0) + control_record.payload[end:]
    return result, info["object"].expression


add_visibility = 添加可见条件
remove_visibility = 剥除可见条件
read_visibility = 读取可见条件
without_visibility_for_parsing = 去可见条件供解析
