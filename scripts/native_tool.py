"""Bounded, portable McgsStu archive audit and single-source patch preparation.

Never opens an MCS database, launches vendor code or writes an input export.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
NATIVE = Path(__file__).resolve().parent / 'native'
sys.path.insert(0, str(NATIVE))
import mcgs_native_zip as nz
import mcgs_recipe_strategy as st
from mcs_window_archive import WindowArchive
from 窗口事件归档 import 窗口事件
import 对象归档 as objects

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def save(path, data):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(data, ensure_ascii=False, indent=2) + '\n')

class Export:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.index = load(self.directory / 'index.json')
        self.fp = load(self.directory / 'fingerprints.json')
        if self.index['sha256'] != self.fp['sha256']:
            raise ValueError('Export and fingerprints have different baselines')
        self.rows = {(r['table'], str(r['row_key'])): r for r in self.index['rows']}

    def blob(self, table, key, field):
        info = self.rows[table, str(key)][field]
        path = (self.directory / info['file']).resolve()
        if not path.is_relative_to(self.directory):
            raise ValueError('Export BLOB path escapes its directory')
        raw = path.read_bytes()
        if len(raw) != info['bytes'] or sha(raw) != info['sha256']:
            raise ValueError('Export BLOB fingerprint mismatch')
        return raw

    def strategy_pair(self):
        raw = self.blob('Stgy', '0', 'lbObjects')
        registry_raw = self.blob('System', 'StgyAndTrigger', 'lbContext')
        # The demonstrated form has the same outer MCGSZIPE wrapper on both.
        plain, registry_plain = nz.unpack(raw), nz.unpack(registry_raw)
        nodes, registry = st.parse_strategy_array(plain), st.StrategyAndTrigger.parse(registry_plain)
        if st.serialize_strategy_array(nodes) != plain or registry.serialize() != registry_plain:
            raise ValueError('Strategy containers do not round-trip exactly')
        if st.serialize_strategy_array(registry.strategies) != plain:
            raise ValueError('The two native strategy arrays disagree')
        return nodes, registry, plain, registry_plain

def audit(export):
    result = {'input_sha256': export.index['sha256'], 'windows': [], 'unsupported': [],
              'source_written': False, 'native_compile_verified': False,
              'native_runtime_verified': False, 'physically_tested': False}
    nodes, registry, _, _ = export.strategy_pair()
    result['strategy_count'], result['trigger_count'] = len(nodes), len(registry.triggers)
    result['two_strategy_containers_equal'] = True
    obj_raw = export.blob('System', 'ObjData', 'lbContext')
    version, obj = objects.parse(obj_raw)
    if objects.serialize(version, obj) != obj_raw:
        raise ValueError('ObjData round-trip failed')
    objects.validate_objects(obj)
    result['object_count'] = len(obj)
    recipe_names = st.parse_recipe_index(export.blob('System', 'MCGS_RECIPE_DATA', 'lbContext'))
    recipe_count = 0
    for name in recipe_names:
        raw = export.blob('System', 'MCGS_RECIPE_' + name, 'lbContext')
        definition = st.RecipeGroup.parse(raw)
        if definition.name != name or definition.serialize() != raw:
            raise ValueError('Recipe registration/definition mismatch')
        recipe_count += 1
    result['recipe_group_count'] = recipe_count
    for (table, key), row in export.rows.items():
        if table != 'WndUser':
            continue
        raw = export.blob(table, key, 'lbObjects')
        try:
            window = WindowArchive.parse(raw)
            if window.to_bytes() != raw:
                raise ValueError('Window envelope round-trip failed')
            settings = window.settings()
            if settings.to_bytes() != window.trailer:
                raise ValueError('Window settings round-trip failed')
            event = 窗口事件.解析(settings.event_tail)
            if event.序列化() != settings.event_tail:
                raise ValueError('Window event round-trip failed')
            result['windows'].append({'id': key, 'controls': len(window.controls), 'roundtrip_equal': True})
        except (ValueError, UnicodeError) as error:
            result['unsupported'].append({'table': table, 'key': key, 'reason': str(error)})
    result['supported_archives_roundtrip'] = not result['unsupported']
    return result

def strategy_source(export, name, source_path, output):
    nodes, registry, plain, registry_plain = export.strategy_pair()
    matches = [i for i, node in enumerate(nodes) if node.fields['name'] == name]
    if len(matches) != 1:
        raise ValueError('Strategy name must match exactly one existing native strategy')
    index = matches[0]
    before = st.single_program_action(nodes[index])
    # Preserve the user's file newlines. The source is the change contract.
    source = Path(source_path).read_bytes().decode('utf-8-sig')
    if not source.strip() or '\x00' in source:
        raise ValueError('Source must be nonempty UTF-8 text without NUL')
    if re.search(r'(?im)^\s*Else\s*If\b', source):
        raise ValueError('MCGS source must use proven If/Then/Else/EndIf, not ElseIf/Else IF')
    if before.fields['source'] == source:
        raise ValueError('Source is unchanged; no patch is needed')
    changed = copy.deepcopy(nodes)
    action = st.single_program_action(changed[index])
    action.fields['source'], action.fields['compiled'] = source, b''
    for i, (old, new) in enumerate(zip(nodes, changed)):
        if i != index and st.serialize_strategy_array([old]) != st.serialize_strategy_array([new]):
            raise ValueError('Unrelated strategy changed')
    updated = copy.deepcopy(registry)
    updated.strategies = changed
    if [st.serialize_trigger_payload(t) for t in updated.triggers] != [st.serialize_trigger_payload(t) for t in registry.triggers]:
        raise ValueError('Trigger changed')
    inverse = copy.deepcopy(changed)
    inverse[index] = copy.deepcopy(nodes[index])
    inv_registry = copy.deepcopy(updated)
    inv_registry.strategies = inverse
    if st.serialize_strategy_array(inverse) != plain or inv_registry.serialize() != registry_plain:
        raise ValueError('Inverse strategy patch is not byte exact')
    out = Path(output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    operations = []
    for table, key, field, key_column, filename, raw in (
        ('Stgy', '0', 'lbObjects', 'iStgyID', 'Stgy_0_lbObjects.bin', nz.pack(st.serialize_strategy_array(changed))),
        ('System', 'StgyAndTrigger', 'lbContext', 'strName', 'System_StgyAndTrigger_lbContext.bin', nz.pack(updated.serialize())),
    ):
        (out / filename).write_bytes(raw)
        operations.append({'action': 'update', 'table': table, 'key_column': key_column,
                           'key': 0 if table == 'Stgy' else key,
                           'before': {field: export.fp['fingerprints'][table][key][field]},
                           'values': {field: {'blob': filename, 'sha256': sha(raw)}}})
    manifest = {'format': 'mcgs-stu-mcs-bounded-update-v1', 'input_sha256': export.index['sha256'],
                'description': 'Existing strategy source replacement; changed action cache only; both containers',
                'operations': operations}
    save(out / 'manifest.json', manifest)
    proof = {'strategy_name': name, 'strategy_index': index,
             'before_source_sha256': sha(before.fields['source'].encode('utf-8')),
             'after_source_sha256': sha(source.encode('utf-8')),
             'changed_action_cache_bytes': 0, 'other_strategy_nodes_and_caches_exact': True,
             'all_triggers_exact': True, 'inverse_both_containers_exact': True,
             'candidate_not_database_reread': True, 'mcs_written': False,
             'native_compile_verified': False, 'native_runtime_verified': False}
    save(out / 'preparation.json', proof)
    return {'manifest': str(out / 'manifest.json'), **proof}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    check = commands.add_parser('audit')
    check.add_argument('--export', dest='export_dir', required=True)
    patch = commands.add_parser('strategy-source')
    patch.add_argument('--export', dest='export_dir', required=True)
    patch.add_argument('--strategy-name', required=True)
    patch.add_argument('--source', required=True)
    patch.add_argument('--out', required=True)
    args = parser.parse_args()
    export = Export(args.export_dir)
    result = audit(export) if args.command == 'audit' else strategy_source(export, args.strategy_name, args.source, args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error), 'mcs_written': False}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
