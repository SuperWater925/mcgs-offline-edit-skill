"""Portable Stu/Pro audit and bounded control/strategy/recipe preparation.

Never opens an MCS database, launches vendor code or writes an input export.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
import time

sys.dont_write_bytecode = True
NATIVE = Path(__file__).resolve().parent / 'native'
sys.path.insert(0, str(NATIVE))
import mcgs_native_zip as nz
import mcgs_recipe_strategy as st
from mcs_window_archive import WindowArchive
from 窗口事件归档 import 窗口事件
import 对象归档 as objects

def unwrapped(raw):
    return nz.unpack(raw) if raw.startswith(nz.MARKER) else raw

def wrapped_like(original, plain):
    return nz.pack(plain) if original.startswith(nz.MARKER) else plain

def pro_format():
    path = Path(__file__).resolve().parents[1] / 'assets/pro-3.5-cli/scripts/native_format.py'
    spec = importlib.util.spec_from_file_location('mcgs_pro_native_format', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

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
        if not self.index.get('project_family') and ('System', 'MCGSVER') in self.rows:
            version = unwrapped(self.blob('System', 'MCGSVER', 'lbContext')).decode('utf-16le').rstrip('\0')
            self.index['project_version'] = version
            self.index['project_family'] = 'Pro' if version.startswith('McgsPro ') else 'Stu'

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
        # Stu may wrap these archives; the measured Pro corpus stores them raw.
        plain, registry_plain = unwrapped(raw), unwrapped(registry_raw)
        nodes, registry = st.parse_strategy_array(plain), st.StrategyAndTrigger.parse(registry_plain)
        if st.serialize_strategy_array(nodes) != plain or registry.serialize() != registry_plain:
            raise ValueError('Strategy containers do not round-trip exactly')
        if st.serialize_strategy_array(registry.strategies) != plain:
            raise ValueError('The two native strategy arrays disagree')
        return nodes, registry, plain, registry_plain

def audit_pro(export):
    result = {'input_sha256': export.index['sha256'], 'project_family': 'Pro',
              'project_version': export.index.get('project_version'), 'software_version_gate': False,
              'windows': [], 'unsupported': [], 'source_written': False,
              'native_compile_verified': False, 'native_runtime_verified': False, 'physically_tested': False}
    module = pro_format()
    raw = unwrapped(export.blob('System', 'ObjData', 'lbContext'))
    try:
        values = module.variables(raw)
        if module.pack_variables(values) != raw:
            raise ValueError('Pro ObjData byte roundtrip differs')
        result['object_count'] = len(values)
        result['objects_roundtrip_equal'] = True
    except (ValueError, UnicodeError) as exc:
        result['unsupported'].append({'feature': 'ObjData', 'reason': str(exc)})
    try:
        nodes, registry, _, _ = export.strategy_pair()
        result.update(strategy_count=len(nodes), trigger_count=len(registry.triggers), two_strategy_containers_equal=True)
    except (ValueError, UnicodeError) as exc:
        result['unsupported'].append({'feature': 'strategy_pair', 'reason': str(exc)})
    if ('System', 'MCGS_RECIPE_DATA') in export.rows:
        try:
            names = st.parse_recipe_index(unwrapped(export.blob('System', 'MCGS_RECIPE_DATA', 'lbContext')))
            for name in names:
                raw = unwrapped(export.blob('System', 'MCGS_RECIPE_' + name, 'lbContext'))
                group = st.RecipeGroup.parse(raw)
                if group.name != name or group.serialize() != raw:
                    raise ValueError('Recipe registration/definition mismatch')
            result['recipe_group_count'] = len(names)
        except (ValueError, UnicodeError) as exc:
            result['unsupported'].append({'feature': 'recipes', 'reason': str(exc)})
    for (table, key), row in export.rows.items():
        if table != 'WndUser':
            continue
        try:
            raw = unwrapped(export.blob(table, key, 'lbObjects'))
            window = WindowArchive.parse(raw)
            settings = window.settings()
            if window.to_bytes() != raw or settings.to_bytes() != window.trailer:
                raise ValueError('Pro window/settings byte roundtrip differs')
            event = 窗口事件.解析(settings.event_tail)
            if event.序列化() != settings.event_tail:
                raise ValueError('Pro window events byte roundtrip differs')
            result['windows'].append({'id': key, 'controls': len(window.controls), 'roundtrip_equal': True})
        except (ValueError, UnicodeError) as exc:
            result['unsupported'].append({'table': table, 'key': key, 'reason': str(exc)})
    result['supported_archives_roundtrip'] = not result['unsupported']
    return result

def _audit_basic(export):
    if export.index.get('project_family') == 'Pro':
        return audit_pro(export)
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

def audit(export):
    from collections import Counter
    from 原生界面样式 import CommonEnvelope,GroupArchive,MultiState
    from mcs_input_text import InputRecord,InputMetadata,LabelRecord
    from mcs_button_control import ButtonArchive
    from mcs_plugin_controls import PluginControl,RecipeCore,XYCore
    from 原生趋势样式 import HistoryCurveStyle
    from 当前存盘浏览样式 import parse_current_save_data
    from 旧下拉框与历史表样式 import parse_combo
    from 报警表原生样式 import AlarmStyle
    from mcs_file_browser import FileBrowserCore
    result=_audit_basic(export)
    result.update(project_family=export.index.get('project_family'),project_version=export.index.get('project_version'),software_version_gate=False)
    counts=Counter();types=Counter();defects=[];opaque_plugins=Counter()
    def equal(a,b):
        if a!=b:raise ValueError('Archive byte roundtrip differs')
    def visit(c,window,path):
        types[hex(c.type_id)]+=1
        try:
            cm=CommonEnvelope.parse(c);equal(cm.to_record().payload,c.payload);counts['common']+=1
            projected=cm.project_without_animations()
            if c.type_id in (0x5008,0x5025,0x5027):
                parser={0x5008:LabelRecord,0x5025:InputRecord,0x5027:ButtonArchive}[c.type_id]
                q=parser.parse(projected);equal(q.to_bytes(),projected.payload)
                equal(cm.restore_projected(projected).payload,c.payload)
                counts[{0x5008:'label',0x5025:'input',0x5027:'button'}[c.type_id]]+=1
                if c.type_id==0x5025:
                    try:InputMetadata.parse(q.common.metadata)
                    except ValueError:defects.append({'window':window,'path':path,'name':cm.name.value,'reason':'stale nested metadata lengths; primary and mirror appearance match; explicit normalize-inputs available'})
            elif c.type_id in (0x5028,0x502a):
                equal(MultiState.parse(c).to_record().payload,c.payload);counts['multi_state']+=1
            elif c.type_id==0x503a:
                g=GroupArchive.parse(c);equal(g.to_record().payload,c.payload);counts['group']+=1
                for i,child in enumerate(g.children):visit(child,window,path+[i])
            elif c.type_id==0x503d:
                p=PluginControl.parse(projected);equal(p.to_record().payload,projected.payload);counts['plugin_envelope']+=1
                lower=p.path.lower()
                if 'recipe' in lower:equal(RecipeCore.parse(p.core).to_bytes(),p.core);counts['recipe_control']+=1
                elif 'xy' in lower:equal(XYCore.parse(p.core).to_bytes(),p.core);counts['xy_control']+=1
                elif 'alarmtableview' in lower:equal(AlarmStyle(p.core).to_bytes(),p.core);counts['alarm_table']+=1
                elif 'filebrowser' in lower:equal(FileBrowserCore.parse(p.core).to_bytes(),p.core);counts['file_browser']+=1
                else:opaque_plugins[p.path]+=1
            elif c.type_id==0x502e:
                equal(HistoryCurveStyle(cm.content).to_bytes(),cm.content);counts['history_curve']+=1
            elif c.type_id==0x5033:
                equal(parse_current_save_data(cm.content).to_bytes(),cm.content);counts['save_data']+=1
            elif c.type_id==0x503c:
                equal(parse_combo(cm.content).to_bytes(),cm.content);counts['combo']+=1
        except (ValueError,UnicodeError) as exc:result['unsupported'].append({'window':window,'control_path':path,'type':hex(c.type_id),'reason':str(exc)})
    for (table,key),row in export.rows.items():
        if table=='WndUser':
            try:
                w=WindowArchive.parse(unwrapped(export.blob(table,key,'lbObjects')))
                for i,c in enumerate(w.controls):visit(c,key,[i])
            except (ValueError,UnicodeError) as exc:result['unsupported'].append({'window':key,'reason':str(exc)})
    registered=[]
    if ('System','MCGS_RECIPE_DATA') in export.rows:
        registered=st.parse_recipe_index(unwrapped(export.blob('System','MCGS_RECIPE_DATA','lbContext')))
    definitions=[]
    for (table,key),row in export.rows.items():
        if table=='System' and key.startswith('MCGS_RECIPE_') and key!='MCGS_RECIPE_DATA':
            try:
                raw=unwrapped(export.blob(table,key,'lbContext'));q=st.RecipeGroup.parse(raw);equal(q.serialize(),raw)
                if key!='MCGS_RECIPE_'+q.name:raise ValueError('Recipe definition name differs from row key')
                definitions.append(q.name)
            except (ValueError,UnicodeError) as exc:result['unsupported'].append({'recipe_row':key,'reason':str(exc)})
    result.update(control_types=dict(types),control_archives_checked=dict(counts),known_input_metadata_length_defects=defects,
                  opaque_plugins_preserved=dict(opaque_plugins),recipe_definition_count=len(definitions),
                  orphan_recipe_definitions_preserved=[n for n in definitions if n not in registered],
                  supported_archives_roundtrip=not result['unsupported'])
    return result

def selected_program(block, action_path=None):
    if action_path is None:
        return st.single_program_action(block)
    if len(action_path)!=3 or any(type(i)is not int or i<0 for i in action_path):
        raise ValueError('Action path must be row,cell,action: three nonnegative indexes')
    row,cell,action=action_path
    try:node=block.fields['rows'][row].fields['cells'][cell].fields['actions'][action]
    except (IndexError,KeyError,TypeError):raise ValueError('Action path does not exist')
    if node is None or node.class_name!='CStgyFuncProg':
        raise ValueError('Selected action is not a native script action')
    return node

def strategy_source(export, name, source_path, output, action_path=None):
    nodes, registry, plain, registry_plain = export.strategy_pair()
    matches = [i for i, node in enumerate(nodes) if node.fields['name'] == name]
    if len(matches) != 1:
        raise ValueError('Strategy name must match exactly one existing native strategy')
    index = matches[0]
    before = selected_program(nodes[index],action_path)
    # Preserve the user's file newlines. The source is the change contract.
    source = Path(source_path).read_bytes().decode('utf-8-sig')
    if not source.strip() or '\x00' in source:
        raise ValueError('Source must be nonempty UTF-8 text without NUL')
    # This byte editor is not the vendor compiler. Preserve supplied source;
    # language legality is verified on the actual Stu/Pro compiler afterwards.
    if before.fields['source'] == source:
        raise ValueError('Source is unchanged; no patch is needed')
    changed = copy.deepcopy(nodes)
    action = selected_program(changed[index],action_path)
    action.fields['source'], action.fields['compiled'] = source, b''
    for i, (old, new) in enumerate(zip(nodes, changed)):
        if i != index and st.serialize_strategy_array([old]) != st.serialize_strategy_array([new]):
            raise ValueError('Unrelated strategy changed')
    updated = copy.deepcopy(registry)
    updated.strategies = changed
    if [st.serialize_trigger_payload(t) for t in updated.triggers] != [st.serialize_trigger_payload(t) for t in registry.triggers]:
        raise ValueError('Trigger changed')
    inverse = copy.deepcopy(changed)
    inverse_action=selected_program(inverse[index],action_path)
    inverse_action.fields['source']=before.fields['source']
    inverse_action.fields['compiled']=before.fields['compiled']
    inv_registry = copy.deepcopy(updated)
    inv_registry.strategies = inverse
    if st.serialize_strategy_array(inverse) != plain or inv_registry.serialize() != registry_plain:
        raise ValueError('Inverse strategy patch is not byte exact')
    out = Path(output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    operations = []
    for table, key, field, key_column, filename, raw in (
        ('Stgy', '0', 'lbObjects', 'iStgyID', 'Stgy_0_lbObjects.bin', wrapped_like(export.blob('Stgy','0','lbObjects'),st.serialize_strategy_array(changed))),
        ('System', 'StgyAndTrigger', 'lbContext', 'strName', 'System_StgyAndTrigger_lbContext.bin', wrapped_like(export.blob('System','StgyAndTrigger','lbContext'),updated.serialize())),
    ):
        (out / filename).write_bytes(raw)
        operations.append({'action': 'update', 'table': table, 'key_column': key_column,
                           'key': 0 if table == 'Stgy' else key,
                           'before': {field: export.fp['fingerprints'][table][key][field]},
                           'values': {field: {'blob': filename, 'sha256': sha(raw)}}})
    manifest = {'format': 'mcgs-native-bounded-update-v1', 'input_sha256': export.index['sha256'],
                'description': 'Existing strategy source replacement; changed action cache only; both containers',
                'operations': operations}
    save(out / 'manifest.json', manifest)
    proof = {'strategy_name': name, 'strategy_index': index, 'action_path':action_path,
             'before_source_sha256': sha(before.fields['source'].encode('utf-8')),
             'after_source_sha256': sha(source.encode('utf-8')),
             'changed_action_cache_bytes': 0, 'other_strategy_nodes_and_caches_exact': True,
             'all_triggers_exact': True, 'inverse_both_containers_exact': True,
             'candidate_not_database_reread': True, 'mcs_written': False,
             'source_syntax_checked':False,
             'native_compile_verified': False, 'native_runtime_verified': False}
    save(out / 'preparation.json', proof)
    return {'manifest': str(out / 'manifest.json'), **proof}

def recipe_cell(export,name,row,column,value,output):
    key='MCGS_RECIPE_'+name
    original=export.blob('System',key,'lbContext');plain=unwrapped(original)
    recipe=st.RecipeGroup.parse(plain)
    if recipe.name!=name or recipe.serialize()!=plain:
        raise ValueError('Recipe identity or original byte roundtrip differs')
    if not 0<=row<len(recipe.records) or not 0<=column<len(recipe.fields):
        raise ValueError('Recipe row/column is outside existing records')
    if '\0' in value:raise ValueError('Recipe value must not contain NUL')
    old=recipe.records[row][column]
    if old==value:raise ValueError('Recipe value unchanged')
    recipe.records[row][column]=value;new_plain=recipe.serialize()
    if st.RecipeGroup.parse(new_plain).serialize()!=new_plain:raise ValueError('Changed recipe roundtrip differs')
    recipe.records[row][column]=old
    if recipe.serialize()!=plain:raise ValueError('Recipe inverse differs')
    out=Path(output).resolve();out.mkdir(parents=True,exist_ok=False)
    raw=wrapped_like(original,new_plain);(out/'recipe.bin').write_bytes(raw)
    manifest={'format':'mcgs-native-bounded-update-v1','input_sha256':export.index['sha256'],'operations':[{'action':'update','table':'System','key_column':'strName','key':key,'before':{'lbContext':export.fp['fingerprints']['System'][key]['lbContext']},'values':{'lbContext':{'blob':'recipe.bin','sha256':sha(raw)}}}]}
    save(out/'manifest.json',manifest)
    proof={'input_sha256':export.index['sha256'],'group':name,'row':row,'column':column,'other_fields_and_cells_preserved':True,'inverse_exact':True,'native_compile_verified':False,'native_runtime_verified':False,'source_written':False}
    save(out/'preparation.json',proof)
    return {'manifest':str(out/'manifest.json'),**proof}

def controls_patch(export,spec,output):
    import control_patch as cp
    if set(spec)!={'input_sha256','controls'} or spec['input_sha256']!=export.index['sha256']:
        raise ValueError('Control spec requires current input_sha256 and controls')
    if not isinstance(spec['controls'],list) or not spec['controls']:raise ValueError('Empty controls list')
    family=export.index.get('project_family')
    raw=export.blob('System','ObjData','lbContext')
    if family=='Pro':variables=pro_format().variables(unwrapped(raw))
    else:
        _,rows=objects.parse(raw)
        variables=[{'name':r.name.value,'kind':r.kind,'id':r.id} for r in rows]
    variables={v['name']:v for v in variables}
    windows={};originals={};plain_originals={};paths=[];replacements={}
    for change in spec['controls']:
        if set(change)!={'window','path','sha256','edits'}:raise ValueError('Control operation requires window/path/sha256/edits')
        key=str(change['window']);path=change['path']
        for oldkey,oldpath in paths:
            if oldkey==key and (path[:len(oldpath)]==oldpath or oldpath[:len(path)]==path):raise ValueError('Duplicate or overlapping control paths')
        paths.append((key,path))
        if key not in windows:
            original=export.blob('WndUser',key,'lbObjects');plain=unwrapped(original);w=WindowArchive.parse(plain)
            if w.to_bytes()!=plain:raise ValueError('Window original roundtrip differs')
            windows[key]=w;originals[key]=original;plain_originals[key]=plain;replacements[key]=[]
        w=windows[key];record=cp.at_path(w.controls,path)
        if sha(record.payload)!=change['sha256']:raise ValueError('Control preimage SHA differs')
        replacement=cp.edit(record,change['edits'],variables)
        if replacement.payload==record.payload:raise ValueError('Control operation has no change')
        cp.replace_path(w.controls,path,replacement)
        replacements[key].append((path,record,replacement))
    serialized={}
    for key,w in windows.items():
        after=w.to_bytes()
        if WindowArchive.parse(after).to_bytes()!=after:raise ValueError('Changed window roundtrip differs')
        for path,record,replacement in reversed(replacements[key]):cp.replace_path(w.controls,path,record)
        if w.to_bytes()!=plain_originals[key]:raise ValueError('Control inverse changed another record or window field')
        for path,record,replacement in replacements[key]:cp.replace_path(w.controls,path,replacement)
        if w.to_bytes()!=after:raise ValueError('Control replacement replay differs')
        serialized[key]=after
    out=Path(output).resolve();out.mkdir(parents=True,exist_ok=False);operations=[]
    for key,w in windows.items():
        filename='window-'+key+'.bin';raw=wrapped_like(originals[key],serialized[key]);(out/filename).write_bytes(raw)
        operations.append({'action':'update','table':'WndUser','key_column':'iID','key':int(key),'before':{'lbObjects':export.fp['fingerprints']['WndUser'][key]['lbObjects']},'values':{'lbObjects':{'blob':filename,'sha256':sha(raw)}}})
    save(out/'manifest.json',{'format':'mcgs-native-bounded-update-v1','input_sha256':export.index['sha256'],'operations':operations})
    proof={'control_count':len(paths),'window_count':len(windows),'outside_target_records_exact':True,'window_fields_and_events_exact':True,'animations_preserved':True,'inverse_replacement_exact':True,'source_written':False,'native_compile_verified':False,'native_runtime_verified':False}
    save(out/'preparation.json',proof)
    return {'manifest':str(out/'manifest.json'),**proof}

class BatchExport(Export):
    """One verified in-memory view per batch; the project baseline never changes."""
    def __init__(self, export):
        self.directory=export.directory
        self.index=copy.deepcopy(export.index)
        self.fp=copy.deepcopy(export.fp)
        self.rows=export.rows
        self.verified={}
        self.changed={}

    def blob(self,table,key,field):
        ident=(table,str(key),field)
        if ident in self.changed:return self.changed[ident]
        if ident not in self.verified:self.verified[ident]=super().blob(table,key,field)
        return self.verified[ident]

    def accept(self,manifest):
        data=load(manifest)
        if data['input_sha256']!=self.index['sha256']:raise ValueError('Batch step baseline differs')
        for op in data['operations']:
            table,key=op['table'],str(op['key'])
            for field,info in op['values'].items():
                if op['before'][field]!=self.fp['fingerprints'][table][key][field]:
                    raise ValueError('Batch step before fingerprint differs')
                path=(manifest.parent/info['blob']).resolve()
                if not path.is_relative_to(manifest.parent):raise ValueError('Batch step BLOB path escapes')
                raw=path.read_bytes()
                if sha(raw)!=info['sha256']:raise ValueError('Batch step BLOB SHA differs')
                self.changed[table,key,field]=raw
                self.fp['fingerprints'][table][key][field]=f'binary:{len(raw)}:{sha(raw)}'


def batch_edit(export,plan_path,output):
    """Compose proven bounded edits, including repeated rows, into one transaction."""
    started=time.perf_counter()
    plan_path=Path(plan_path).resolve();plan=load(plan_path)
    if set(plan)!={'input_sha256','steps'} or plan['input_sha256']!=export.index['sha256']:
        raise ValueError('Batch plan requires current input_sha256 and steps')
    if not isinstance(plan['steps'],list) or not plan['steps']:raise ValueError('Empty batch steps')
    out=Path(output).resolve()
    if out.exists():raise ValueError('Batch output must be a new directory')
    view=BatchExport(export);proofs=[]
    with tempfile.TemporaryDirectory(prefix='mcgs-bounded-batch-') as temporary:
        for index,step in enumerate(plan['steps']):
            if not isinstance(step,dict):raise ValueError('Batch step must be an object')
            command=step.get('command');step_out=Path(temporary)/str(index)
            tick=time.perf_counter()
            if command=='controls':
                if set(step)!={'command','spec'}:raise ValueError('Controls batch step requires only spec')
                proof=controls_patch(view,load((plan_path.parent/step['spec']).resolve()),step_out)
            elif command=='strategy-source':
                if set(step)-{'command','strategy_name','source','action_path'} or not {'strategy_name','source'}<=set(step):
                    raise ValueError('Strategy batch step requires strategy_name/source and optional action_path')
                proof=strategy_source(view,step['strategy_name'],(plan_path.parent/step['source']).resolve(),step_out,step.get('action_path'))
            elif command=='recipe-cell':
                if set(step)!={'command','group','row','column','value'} or type(step['row'])is not int or type(step['column'])is not int or not isinstance(step['value'],str):
                    raise ValueError('Recipe batch step requires group/row/column/value')
                proof=recipe_cell(view,step['group'],step['row'],step['column'],step['value'],step_out)
            else:raise ValueError('Batch supports controls, strategy-source and recipe-cell only')
            view.accept(step_out/'manifest.json')
            proof.pop('manifest',None)
            proofs.append({'command':command,'elapsed_ms':round((time.perf_counter()-tick)*1000,3),**proof})
        blobs=[]
        keys={'System':'strName','Stgy':'iStgyID','WndUser':'iID'}
        for (table,key,field),raw in sorted(view.changed.items()):
            fingerprint=f'binary:{len(raw)}:{sha(raw)}'
            if fingerprint==export.fp['fingerprints'][table][key][field]:continue
            filename=f'blob-{len(blobs):04d}.bin'
            op={'action':'update','table':table,'key_column':keys[table],
                'key':key if table=='System' else int(key),
                'before':{field:export.fp['fingerprints'][table][key][field]},
                'values':{field:{'blob':filename,'sha256':sha(raw)}}}
            blobs.append((filename,raw,op))
        if not blobs:raise ValueError('Batch has no net change')
        out.mkdir(parents=True,exist_ok=False)
        for filename,raw,_ in blobs:(out/filename).write_bytes(raw)
        save(out/'manifest.json',{'format':'mcgs-native-bounded-update-v1','input_sha256':export.index['sha256'],
                                 'operations':[op for _,_,op in blobs]})
        proof={'step_count':len(proofs),'fields':len(blobs),'steps':proofs,
               'elapsed_ms':round((time.perf_counter()-started)*1000,3),
               'single_baseline':True,'source_written':False,'candidate_not_database_reread':True,
               'native_compile_verified':False,'native_runtime_verified':False}
        save(out/'preparation.json',proof)
        return {'manifest':str(out/'manifest.json'),**proof}


def normalize_inputs(export,output):
    import control_patch as cp
    from mcs_input_text import InputRecord,InputMetadata
    from 原生界面样式 import CommonEnvelope,GroupArchive
    changes=[]
    def visit(controls,key,path=()):
        for i,record in enumerate(controls):
            current=list(path)+[i]
            if record.type_id==0x503a:visit(GroupArchive.parse(record).children,key,current)
            if record.type_id!=0x5025:continue
            q=InputRecord.parse(CommonEnvelope.parse(record).project_without_animations())
            try:InputMetadata.parse(q.common.metadata)
            except ValueError:
                changes.append({'window':int(key),'path':current,'sha256':sha(record.payload),'edits':{'repair_input_metadata':True}})
    for (table,key),row in export.rows.items():
        if table=='WndUser':visit(WindowArchive.parse(unwrapped(export.blob(table,key,'lbObjects'))).controls,key)
    if not changes:raise ValueError('No measured stale nested input metadata counts found')
    result=controls_patch(export,{'input_sha256':export.index['sha256'],'controls':changes},output)
    save(Path(output)/'repairs.json',{'scope':'only nested metadata length prefixes; exact primary/mirror appearance required','controls':changes})
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    check = commands.add_parser('audit')
    check.add_argument('--export', dest='export_dir', required=True)
    batch=commands.add_parser('batch-edit')
    batch.add_argument('--export',dest='export_dir',required=True)
    batch.add_argument('--plan',required=True)
    batch.add_argument('--out',required=True)
    patch = commands.add_parser('strategy-source')
    patch.add_argument('--export', dest='export_dir', required=True)
    patch.add_argument('--strategy-name', required=True)
    patch.add_argument('--source', required=True)
    patch.add_argument('--out', required=True)
    patch.add_argument('--action-path',help='Explicit existing script row,cell,action indexes')
    recipe=commands.add_parser('recipe-cell')
    recipe.add_argument('--export',dest='export_dir',required=True)
    recipe.add_argument('--group',required=True)
    recipe.add_argument('--row',type=int,required=True)
    recipe.add_argument('--column',type=int,required=True)
    recipe.add_argument('--value',required=True)
    recipe.add_argument('--out',required=True)
    controls=commands.add_parser('controls')
    controls.add_argument('--export',dest='export_dir',required=True)
    controls.add_argument('--spec',required=True)
    controls.add_argument('--out',required=True)
    normalize=commands.add_parser('normalize-inputs')
    normalize.add_argument('--export',dest='export_dir',required=True)
    normalize.add_argument('--out',required=True)
    args = parser.parse_args()
    export = Export(args.export_dir)
    if args.command=='audit':result=audit(export)
    elif args.command=='batch-edit':result=batch_edit(export,args.plan,args.out)
    elif args.command=='normalize-inputs':result=normalize_inputs(export,args.out)
    elif args.command=='controls':result=controls_patch(export,load(Path(args.spec)),args.out)
    elif args.command=='recipe-cell':result=recipe_cell(export,args.group,args.row,args.column,args.value,args.out)
    else:
        path=[int(v) for v in args.action_path.split(',')] if args.action_path else None
        result=strategy_source(export,args.strategy_name,args.source,args.out,path)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    if hasattr(sys.stdout,'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8',errors='replace')
    try:
        main()
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error), 'mcs_written': False}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
