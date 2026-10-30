"""MCGS Stu 3.5 MFC 配方/策略归档的纯文件编解码器。

不调用原厂进程/DLL。仅支持已有样本证实的类；未知类/字段版本会停止解析。
生成源码动作的编译码为空；Stgy.iCompileFlag沿原厂保存值1，不将其解释为编译证据。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import copy
import json
from pathlib import Path
import struct
from typing import Any


class FormatError(ValueError):
    pass


@dataclass
class Node:
    class_name: str
    fields: dict[str, Any] = field(default_factory=dict)
    schema: int = 0


class Reader:
    def __init__(self, data: bytes, position: int = 0):
        self.data = data
        self.pos = position
        self.classes: dict[int, tuple[str, int]] = {}
        self.objects: dict[int, Node] = {}
        self.next_map_index = 1

    def take(self, count: int) -> bytes:
        if count < 0 or self.pos + count > len(self.data):
            raise FormatError(f"Unexpected EOF at {self.pos:#x}, length {count}")
        out = self.data[self.pos:self.pos + count]
        self.pos += count
        return out

    def u8(self):
        return self.take(1)[0]

    def u16(self):
        return struct.unpack("<H", self.take(2))[0]

    def u32(self):
        return struct.unpack("<I", self.take(4))[0]

    def count(self):
        count = self.u16()
        return self.u32() if count == 0xFFFF else count

    def string(self) -> str:
        if self.take(3) != b"\xff\xfe\xff":
            raise FormatError(f"Expected MFC Unicode CString at {self.pos - 3:#x}")
        length = self.u8()
        if length == 0xFF:
            length = self.u16()
            if length == 0xFFFF:
                length = self.u32()
        return self.take(length * 2).decode("utf-16le", errors="strict")

    def byte_array(self) -> bytes:
        return self.take(self.count())

    def array(self) -> list[Node | None]:
        return [self.object() for _ in range(self.count())]

    def object(self) -> Node | None:
        tag = self.u16()
        if tag == 0:
            return None
        if tag == 0xFFFF:
            schema = self.u16()
            name = self.take(self.u16()).decode("ascii")
            self.classes[self.next_map_index] = (name, schema)
            self.next_map_index += 1
        elif tag & 0x8000:
            try:
                name, schema = self.classes[tag & 0x7FFF]
            except KeyError as error:
                raise FormatError(f"Unknown class reference {tag:#x} at {self.pos - 2:#x}") from error
        else:
            try:
                return self.objects[tag]
            except KeyError as error:
                raise FormatError(f"Unknown object reference {tag:#x}") from error
        node = Node(name, schema=schema)
        self.objects[self.next_map_index] = node
        self.next_map_index += 1
        node.fields = read_node_fields(self, name)
        return node

    def finish(self):
        if self.pos != len(self.data):
            raise FormatError(f"Unparsed tail at {self.pos:#x}/{len(self.data):#x}")


class Writer:
    def __init__(self):
        self.data = bytearray()
        self.classes: dict[tuple[str, int], int] = {}
        self.objects: dict[int, int] = {}
        self.next_map_index = 1

    def put(self, data: bytes):
        self.data.extend(data)

    def u8(self, value: int):
        self.put(struct.pack("<B", value))

    def u16(self, value: int):
        self.put(struct.pack("<H", value))

    def u32(self, value: int):
        self.put(struct.pack("<I", value & 0xFFFFFFFF))

    def count(self, value: int):
        if value < 0xFFFF:
            self.u16(value)
        else:
            self.u16(0xFFFF)
            self.u32(value)

    def string(self, value: str):
        encoded = value.encode("utf-16le")
        length = len(encoded) // 2
        self.put(b"\xff\xfe\xff")
        if length < 0xFF:
            self.u8(length)
        elif length < 0xFFFF:
            self.u8(0xFF)
            self.u16(length)
        else:
            self.u8(0xFF)
            self.u16(0xFFFF)
            self.u32(length)
        self.put(encoded)

    def byte_array(self, value: bytes):
        self.count(len(value))
        self.put(value)

    def array(self, value: list[Node | None]):
        self.count(len(value))
        for node in value:
            self.object(node)

    def object(self, node: Node | None):
        if node is None:
            self.u16(0)
            return
        if id(node) in self.objects:
            index = self.objects[id(node)]
            if index >= 0x8000:
                raise FormatError("Large MFC object reference not supported")
            self.u16(index)
            return
        key = (node.class_name, node.schema)
        if key in self.classes:
            index = self.classes[key]
            if index >= 0x7FFF:
                raise FormatError("Large MFC class reference not supported")
            self.u16(0x8000 | index)
        else:
            self.classes[key] = self.next_map_index
            self.next_map_index += 1
            self.u16(0xFFFF)
            self.u16(node.schema)
            name = node.class_name.encode("ascii")
            self.u16(len(name))
            self.put(name)
        self.objects[id(node)] = self.next_map_index
        self.next_map_index += 1
        write_node_fields(self, node)


def read_node_fields(reader: Reader, name: str) -> dict:
    if name == "CStrategyBlock":
        return dict(rows=reader.array(), header_words=[reader.u32(), reader.u32()], name=reader.string(), comment=reader.string(), tail_words=[reader.u32() for _ in range(5)])
    if name == "CStrategyRow":
        return dict(cells=reader.array())
    if name == "CStrategyCell":
        return dict(conditions=reader.array(), actions=reader.array())
    if name in ("CStgyConnIF", "CStgyFuncProg"):
        # 基类DWORD语义未凭样本推定；新对象严格沿用原厂模板的值。
        fields = dict(state_word=reader.u32(), label=reader.string(), compiled=reader.byte_array())
        fields["expression" if name == "CStgyConnIF" else "source"] = reader.string()
        return fields
    if name in ("CTriggerStart", "CTriggerEnd", "CTriggerUser", "CTriggerLoop", "CTriggerEvent"):
        fields = dict(trigger_id=reader.u32(), strategy_id=reader.u32(), trigger_type=reader.u32(), note=reader.string(), common_tail=[reader.u32() for _ in range(3)])
        if name == "CTriggerLoop":
            fields["loop_tail"] = [reader.u32() for _ in range(8)]
        if name == "CTriggerEvent":
            fields.update(event_cache=reader.byte_array(),event_expression=reader.string(),event_words=[reader.u32(),reader.u32()])
        return fields
    raise FormatError(f"Unsupported MFC runtime class {name!r} at {reader.pos:#x}")


def write_node_fields(writer: Writer, node: Node):
    name, fields = node.class_name, node.fields
    if name == "CStrategyBlock":
        writer.array(fields["rows"])
        metadata = Writer()
        metadata.string(fields["name"])
        metadata.string(fields["comment"])
        for word in fields["tail_words"]:
            metadata.u32(word)
        if (fields["header_words"][0] | (fields["header_words"][1] << 32)) != len(metadata.data):
            raise FormatError("CStrategyBlock metadata length must match its two CStrings and five DWORDs")
        for word in fields["header_words"]:
            writer.u32(word)
        writer.put(metadata.data)
    elif name == "CStrategyRow":
        writer.array(fields["cells"])
    elif name == "CStrategyCell":
        writer.array(fields["conditions"])
        writer.array(fields["actions"])
    elif name in ("CStgyConnIF", "CStgyFuncProg"):
        writer.u32(fields["state_word"])
        writer.string(fields["label"])
        writer.byte_array(fields["compiled"])
        writer.string(fields["expression" if name == "CStgyConnIF" else "source"])
    elif name in ("CTriggerStart", "CTriggerEnd", "CTriggerUser", "CTriggerLoop", "CTriggerEvent"):
        for field_name in ("trigger_id", "strategy_id", "trigger_type"):
            writer.u32(fields[field_name])
        writer.string(fields["note"])
        for word in fields["common_tail"]:
            writer.u32(word)
        if name == "CTriggerLoop":
            for word in fields["loop_tail"]:
                writer.u32(word)
        if name == "CTriggerEvent":
            writer.byte_array(fields["event_cache"])
            writer.string(fields["event_expression"])
            for word in fields["event_words"]:writer.u32(word)
    else:
        raise FormatError(f"Unsupported MFC runtime class {name!r}")


def parse_strategy_array(data: bytes) -> list[Node]:
    reader = Reader(data)
    result = reader.array()
    reader.finish()
    return result


def serialize_strategy_array(nodes: list[Node]) -> bytes:
    writer = Writer()
    writer.array(nodes)
    return bytes(writer.data)


@dataclass
class StrategyAndTrigger:
    format_marker: int
    strategies: list[Node]
    triggers: list[Node]

    @classmethod
    def parse(cls, data: bytes):
        reader = Reader(data)
        marker, length = reader.u32(), reader.u32()
        if length != len(data) - 8:
            raise FormatError("StgyAndTrigger payload length mismatch")
        result = cls(marker, reader.array(), reader.array())
        reader.finish()
        return result

    def serialize(self):
        writer = Writer()
        writer.array(self.strategies)
        writer.array(self.triggers)
        return struct.pack("<II", self.format_marker, len(writer.data)) + bytes(writer.data)


@dataclass
class RecipeField:
    binding: str
    title: str
    data_type: int


@dataclass
class RecipeGroup:
    format_marker: int
    name: str
    fields: list[RecipeField]
    records: list[list[str]]
    log_tail: tuple[int, ...]

    @classmethod
    def parse(cls, data: bytes):
        reader = Reader(data)
        marker, name, field_count = reader.u32(), reader.string(), reader.u32()
        fields = [RecipeField(reader.string(), reader.string(), reader.u32()) for _ in range(field_count)]
        records = [[reader.string() for _ in range(reader.count())] for _ in range(reader.u32())]
        remaining=len(data)-reader.pos
        if remaining not in (0,12):raise FormatError('Unknown recipe trailing field layout')
        tail = tuple(reader.u32() for _ in range(remaining//4))
        reader.finish()
        if any(len(record) != field_count for record in records):
            raise FormatError("Recipe record width mismatch")
        return cls(marker, name, fields, records, tail)

    def serialize(self):
        writer = Writer()
        writer.u32(self.format_marker)
        writer.string(self.name)
        writer.u32(len(self.fields))
        for field_item in self.fields:
            writer.string(field_item.binding)
            writer.string(field_item.title)
            writer.u32(field_item.data_type)
        writer.u32(len(self.records))
        for record in self.records:
            if len(record) != len(self.fields):
                raise FormatError("Recipe record width mismatch")
            writer.count(len(record))
            for value in record:
                writer.string(value)
        for word in self.log_tail:
            writer.u32(word)
        return bytes(writer.data)


def parse_recipe_index(data: bytes) -> list[str]:
    reader = Reader(data)
    names = [reader.string() for _ in range(reader.u32())]
    reader.finish()
    return names


def serialize_recipe_index(names: list[str]) -> bytes:
    writer = Writer()
    writer.u32(len(names))
    for name in names:
        writer.string(name)
    return bytes(writer.data)


def serialize_trigger_payload(trigger: Node) -> bytes:
    """Trigger表lbContext不带MFC对象类头；System中同一对象带类头。"""
    writer = Writer()
    write_node_fields(writer, trigger)
    return bytes(writer.data)


def refresh_strategy_metadata_length(node: Node):
    """原厂样本15条均证实两个DWORD为后续元数据长度低/高位。"""
    metadata = Writer()
    metadata.string(node.fields["name"])
    metadata.string(node.fields["comment"])
    for word in node.fields["tail_words"]:
        metadata.u32(word)
    node.fields["header_words"] = [len(metadata.data) & 0xFFFFFFFF, len(metadata.data) >> 32]


def single_program_action(block: Node) -> Node:
    """只接受有实证的单行/单单元/单脚本动作模板，拒绝悄然丢弃其他图节点。"""
    rows = block.fields["rows"]
    if len(rows) != 1 or len(rows[0].fields["cells"]) != 1:
        raise FormatError("Expected one-row one-cell native strategy template")
    cell = rows[0].fields["cells"][0]
    if len(cell.fields["conditions"]) != 1 or len(cell.fields["actions"]) != 1:
        raise FormatError("Expected one native condition and one native action")
    condition, action = cell.fields["conditions"][0], cell.fields["actions"][0]
    if condition.class_name != "CStgyConnIF" or action.class_name != "CStgyFuncProg":
        raise FormatError("Native template is not a script action cell")
    if condition.fields["compiled"] or condition.fields["expression"] != "\x010":
        raise FormatError("Template condition is not the demonstrated default connector")
    return action


def append_source_strategies(
    strategies: list[Node], triggers: list[Node],
    source_programs: list[tuple[str, str]],
    template_strategy: Node, template_user_trigger: Node,
) -> tuple[list[Node], list[Node], dict[str, dict]]:
    """纯内存生成；保持原策略/触发及原编译码，新增用户触发源码策略。"""
    if template_user_trigger.class_name != "CTriggerUser" or template_user_trigger.fields["trigger_type"] != 3:
        raise FormatError("Require demonstrated CTriggerUser template")
    original_names = {node.fields["name"] for node in strategies}
    new_names = [name for name, _ in source_programs]
    if len(set(new_names)) != len(new_names) or original_names & set(new_names):
        raise FormatError("Strategy name collision")
    strategy_id = max(node.fields["tail_words"][2] for node in strategies) + 1
    trigger_id = max(node.fields["trigger_id"] for node in triggers) + 1
    added_strategies, added_triggers, mapping = [], [], {}
    for name, source in source_programs:
        if not source.strip() or len(name) > 32:
            raise FormatError("Invalid native strategy name/source")
        block = copy.deepcopy(template_strategy)
        action = single_program_action(block)
        action.fields["compiled"] = b""
        action.fields["source"] = source
        block.fields["name"] = name
        block.fields["comment"] = "触摸屏本地配方与全组预览；源码待原厂编译"
        block.fields["tail_words"][2] = strategy_id
        refresh_strategy_metadata_length(block)
        trigger = copy.deepcopy(template_user_trigger)
        trigger.fields["trigger_id"] = trigger_id
        trigger.fields["strategy_id"] = strategy_id
        added_strategies.append(block)
        added_triggers.append(trigger)
        mapping[name] = dict(strategy_id=strategy_id, trigger_id=trigger_id, trigger_type=3, class_name="CTriggerUser")
        strategy_id += 1
        trigger_id += 1
    return strategies + added_strategies, triggers + added_triggers, mapping


def make_recipe_group(
    name: str,
    fields: list[tuple[str, str, int]],
    native_empty_template: RecipeGroup,
    records: list[list[str]] | None = None,
) -> RecipeGroup:
    """fields为(真实中文变量名,静态中文标题,原生类型1/2/3)；无自造ID偏置。"""
    if native_empty_template.records or len(native_empty_template.fields) != 1:
        raise FormatError("Require demonstrated empty recipe group with name column")
    if native_empty_template.fields[0].binding or native_empty_template.fields[0].data_type != 3:
        raise FormatError("Invalid demonstrated native name column")
    if any(kind not in (1, 2, 3) for _, _, kind in fields):
        raise FormatError("Unsupported recipe native type")
    return RecipeGroup(
        native_empty_template.format_marker, name,
        [RecipeField("", "配方名称", 3)] + [RecipeField(binding, title, kind) for binding, title, kind in fields],
        records or [], native_empty_template.log_tail,
    )
