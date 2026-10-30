"""Pure offline McgsStu 0x5027 standard-button archive reader and factory.

Sources: native original window 39, vendor demo windows, and static
CDrawButton serializers (88bf20/88c740), ButtonProperties (890240).
No vendor executable code is imported or invoked. Changed expressions and
scripts are source only; each edited output requires native compile/runtime verification.

``click_script`` is installed as the button's native *release script* so the
native enable/safety condition applies. It is not a generic Click event:
the vendor help explicitly says generic events bypass button safety.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import copy
import hashlib
import json
import re
import struct
import sys

ROOT = Path(__file__).resolve().parent
from mcs_window_archive import (ControlRecord, FormatError, Reader,
                                WindowArchive, write_count, write_cstring)


@dataclass
class CString:
    value: str
    original: str
    raw: bytes
    wide: bool

    @classmethod
    def parse(cls, r):
        value, raw, wide = r.cstring()
        return cls(value, value, raw, wide)

    def to_bytes(self):
        return self.raw if self.value == self.original else write_cstring(self.value, self.wide)


@dataclass
class ByteArray:
    value: bytes
    original: bytes
    prefix: bytes

    @classmethod
    def parse(cls, r):
        value, prefix = r.byte_array()
        return cls(value, value, prefix)

    def to_bytes(self):
        prefix = self.prefix if len(self.value) == len(self.original) else write_count(len(self.value))
        return prefix + self.value


@dataclass
class Array:
    items: list
    prefix: bytes
    strings: bool = False
    original_count: int = 0

    @classmethod
    def parse(cls, r, strings=False):
        start = r.pos
        n = r.count()
        if n > 65536:
            raise FormatError("Unreasonable button array count")
        prefix = r.data[start:r.pos]
        return cls([CString.parse(r) if strings else r.u32() for _ in range(n)], prefix, strings, n)

    def to_bytes(self):
        prefix = self.prefix if len(self.items) == self.original_count else write_count(len(self.items))
        if self.strings:
            return prefix + b"".join(v.to_bytes() for v in self.items)
        return prefix + b"".join(struct.pack("<I", v) for v in self.items)

    def clear_values(self, integer=0):
        for i, item in enumerate(self.items):
            if self.strings:
                item.value = ""
            else:
                self.items[i] = integer


def _font(r):
    """Native font map: BYTE flags, DWORD count, language + LOGFONTW fields.

    The LOGFONT name is a CString; the preceding 28 bytes are preserved.
    We do not edit fonts, invent language records, or use screen font APIs.
    """
    start = r.pos
    r.u8()
    n = r.u32()
    if n > 64:
        raise FormatError(f"Unsupported font map at {start}: {n} languages")
    for _ in range(n):
        r.u32()
        r.take(28)
        r.cstring()
    return r.data[start:r.pos]


def _picture(r):
    """Keep proven native reference-image encoding; reject other formats."""
    start = r.pos
    mode = r.u32()
    if mode == 0x80:
        r.cstring()
    elif mode == 2:
        # Native embedded image: width, height, bounded serialized payload.
        # The payload may be SVG/bitmap/metafile; do not rewrite its internals.
        width,height,size=r.u32(),r.u32(),r.u32()
        if size>64*1024*1024:raise FormatError('Embedded picture exceeds bounds')
        r.take(size)
    elif mode == 3:
        # Legacy zero-size image payload, NOT an image-disable marker.
        # Native loading may normalize this to mode0x80 plus an empty name.
        # Disabling requires the owner control's proven enable gate; if that
        # gate conditionally serializes the image, omit its entire span.
        # Nonempty embedded-image branches are not synthesized here.
        if r.u32() != 0 or r.u32() != 0:
            raise FormatError("Nonempty embedded picture requires its own parser")
    else:
        raise FormatError(f"Unsupported native picture encoding {mode:#x}")
    return r.data[start:r.pos]


def font_heights(data):
    r = Reader(data)
    r.u8()
    n = r.u32()
    heights = []
    if n > 64:
        raise FormatError("Unsupported font language count")
    for _ in range(n):
        r.u32()
        heights.append(r.unpack("<i"))
        r.take(24)
        r.cstring()
    if r.pos != len(data):
        raise FormatError("Unexpected native font tail")
    return heights


def _resize_font(data, pixel_height):
    if pixel_height is None:
        return data
    if type(pixel_height) is not int or not 8 <= pixel_height <= 128:
        raise ValueError("Button font height must be 8..128 pixels")
    font_heights(data)
    result = bytearray(data)
    r = Reader(data)
    r.u8()
    n = r.u32()
    for _ in range(n):
        r.u32()
        result[r.pos:r.pos + 4] = struct.pack("<i", -pixel_height)
        r.take(28)
        r.cstring()
    return bytes(result)


@dataclass
class ButtonProperties:
    words: list[int]
    caption: CString
    font: bytes
    picture: bytes
    action_words: list[int]
    action_text_down: CString
    action_text_up: CString
    action_parameters: list[int]
    flags_down: Array
    texts_down: Array
    flags_up: Array
    texts_up: Array
    ids_down: Array
    ids_up: Array
    press_script: CString
    preserved_text: CString
    press_compiled: ByteArray
    preserved_compiled: ByteArray
    reserved: ByteArray

    @classmethod
    def parse(cls, data):
        r = Reader(data)
        words = list(struct.unpack("<18I", r.take(72)))
        caption = CString.parse(r)
        font = _font(r)
        picture = _picture(r) if words[16] else b""
        action_words = [r.u32(), r.u32()]
        down, up = CString.parse(r), CString.parse(r)
        parameters = list(struct.unpack("<5I", r.take(20)))
        arrays = [Array.parse(r), Array.parse(r, True), Array.parse(r),
                  Array.parse(r, True), Array.parse(r), Array.parse(r)]
        press, text = CString.parse(r), CString.parse(r)
        compiled = [ByteArray.parse(r) for _ in range(3)]
        if r.pos != len(data):
            raise FormatError(f"Unexpected ButtonProperties bytes at {r.pos}/{len(data)}")
        return cls(words, caption, font, picture, action_words, down, up,
                   parameters, *arrays, press, text, *compiled)

    def to_bytes(self):
        return (struct.pack("<18I", *self.words) + self.caption.to_bytes() +
                self.font + self.picture + struct.pack("<2I", *self.action_words) +
                self.action_text_down.to_bytes() + self.action_text_up.to_bytes() +
                struct.pack("<5I", *self.action_parameters) +
                b"".join(a.to_bytes() for a in [self.flags_down, self.texts_down,
                    self.flags_up, self.texts_up, self.ids_down, self.ids_up]) +
                self.press_script.to_bytes() + self.preserved_text.to_bytes() +
                self.press_compiled.to_bytes() + self.preserved_compiled.to_bytes() +
                self.reserved.to_bytes())

    def clear_actions(self):
        # These defaults occur in the vendor's script-only XY buttons.
        self.action_words[:] = [0, 0]
        self.action_text_down.value = self.action_text_up.value = ""
        self.action_parameters[:] = [0, 0xffffffff, 0xffffffff, 0, 0]
        for a in [self.flags_down, self.flags_up]:
            a.clear_values(0)
        for a in [self.texts_down, self.texts_up]:
            a.clear_values()
        for a in [self.ids_down, self.ids_up]:
            a.clear_values(0xffffffff)
        self.press_script.value = self.preserved_text.value = ""
        self.press_compiled.value = self.preserved_compiled.value = self.reserved.value = b""


@dataclass
class ButtonMetadata:
    empty_events: bytes
    words: bytes
    extension: ByteArray
    properties_blob: ByteArray
    extension_tail: ByteArray
    tail: bytes
    properties: ButtonProperties

    @classmethod
    def parse(cls, data):
        r = Reader(data)
        start = r.pos
        if r.count():
            raise FormatError("Generic control events need their own class-aware parser")
        events = data[start:r.pos]
        words = r.take(8)
        extension = ByteArray.parse(r)
        remaining = len(r.data) - r.pos
        if remaining not in (0, 4):
            raise FormatError('Button metadata tail structure not proven')
        tail = r.take(remaining)
        if r.pos != len(data):
            raise FormatError("Unexpected button metadata tail")
        e = Reader(extension.value)
        blob = ByteArray.parse(e)
        extension_tail = ByteArray.parse(e)
        if e.pos != len(extension.value):
            raise FormatError("Unexpected extension archive tail")
        return cls(events, words, extension, blob, extension_tail, tail,
                   ButtonProperties.parse(blob.value))

    def to_bytes(self):
        self.properties_blob.value = self.properties.to_bytes()
        self.extension.value = self.properties_blob.to_bytes() + self.extension_tail.to_bytes()
        return self.empty_events + self.words + self.extension.to_bytes() + self.tail


@dataclass
class ButtonArchive:
    record: ControlRecord
    prefix: bytes
    rect_offset: int
    rect: tuple[int, int, int, int]
    name: CString
    metadata_array: ByteArray
    metadata: ButtonMetadata
    enable_compiled: ByteArray
    action_texts: Array
    action_ids: Array
    action_modes: Array
    caption_words: list[int]
    caption: CString
    alignment: list[int]
    picture: bytes
    font: bytes
    action_words: list[int]
    enabled_expression: CString
    enabled_invert: int
    release_script: CString
    release_compiled: ByteArray
    safety_mode: int
    hold_time: int
    confirmation_time: int
    disabled_appearance: int

    @classmethod
    def parse(cls, record):
        if record.type_id != 0x5027:
            raise FormatError("Expected native standard button type 0x5027")
        r = Reader(record.payload)
        version = r.unpack("<f")
        style = [r.u32(), r.u32()]
        if style[0] & 0x100:
            r.take(8)
            r.cstring()
        rect_offset = r.pos
        rect = struct.unpack("<4i", r.take(16))
        r.take(18 + 14)  # Native pen and brush serialization.
        if r.count():
            raise FormatError("Nonempty button animation array requires its own parser")
        r.take(4)
        prefix = record.payload[:r.pos]
        name = CString.parse(r)
        metadata_array = ByteArray.parse(r)
        metadata = ButtonMetadata.parse(metadata_array.value)
        enable_compiled = ByteArray.parse(r)
        text, ids, modes = Array.parse(r, True), Array.parse(r), Array.parse(r)
        caption_words = [r.u32(), r.u32()]
        caption = CString.parse(r)
        align = [r.u32(), r.u32()]
        picture, font = _picture(r), _font(r)
        action_words = [r.u32(), r.u32()]
        enabled, invert = CString.parse(r), r.u32()
        script, compiled = CString.parse(r), ByteArray.parse(r)
        # 88c740 stores these final fields explicitly: +204, +206, +208, +228.
        safety, hold, confirm, appearance = r.u8(), r.u16(), r.u16(), r.u8()
        if r.pos != len(record.payload):
            raise FormatError(f"Button trailing bytes at {r.pos}/{len(record.payload)}")
        result=cls(copy.deepcopy(record), prefix, rect_offset, rect, name,
                   metadata_array, metadata, enable_compiled, text, ids, modes,
                   caption_words, caption, align, picture, font, action_words,
                   enabled, invert, script, compiled, safety, hold, confirm, appearance)
        if result.to_bytes()!=record.payload:
            raise FormatError('Button actual structure does not round-trip exactly')
        return result

    def to_bytes(self):
        prefix = bytearray(self.prefix)
        prefix[self.rect_offset:self.rect_offset + 16] = struct.pack("<4i", *self.rect)
        self.metadata_array.value = self.metadata.to_bytes()
        return (bytes(prefix) + self.name.to_bytes() + self.metadata_array.to_bytes() +
                self.enable_compiled.to_bytes() + self.action_texts.to_bytes() +
                self.action_ids.to_bytes() + self.action_modes.to_bytes() +
                struct.pack("<2I", *self.caption_words) + self.caption.to_bytes() +
                struct.pack("<2I", *self.alignment) + self.picture + self.font +
                struct.pack("<2I", *self.action_words) + self.enabled_expression.to_bytes() +
                struct.pack("<I", self.enabled_invert) + self.release_script.to_bytes() +
                self.release_compiled.to_bytes() +
                struct.pack("<BHHB", self.safety_mode, self.hold_time,
                            self.confirmation_time, self.disabled_appearance))

    def to_record(self):
        result = copy.deepcopy(self.record)
        result.payload = self.to_bytes()
        return result

    def summary(self):
        return dict(name=self.name.value, rect=list(self.rect), caption=self.caption.value,
                    modern_caption=self.metadata.properties.caption.value,
                    enabled_expression=self.enabled_expression.value,
                    enabled_invert=self.enabled_invert,
                    disabled_appearance=self.disabled_appearance,
                    release_script=self.release_script.value,
                    press_script=self.metadata.properties.press_script.value,
                    expression_compiled_bytes=len(self.enable_compiled.value),
                    release_compiled_bytes=len(self.release_compiled.value),
                    press_compiled_bytes=len(self.metadata.properties.press_compiled.value),
                    native_generic_click_event=False)






def bind_click(record, script, enabled_expression=None):
    """5027 only: bind the native release script; reject generic table events."""
    a = ButtonArchive.parse(record)
    a.release_script.value = str(script)
    a.release_compiled.value = b""
    if enabled_expression is not None:
        a.enabled_expression.value = str(enabled_expression)
        a.enabled_invert = 0
        a.enable_compiled.value = b""
        a.disabled_appearance = 1
    return a.to_record()
