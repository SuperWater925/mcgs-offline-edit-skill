"""Native McgsPro editing; software releases are recorded, structural codecs decide support."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

import native_format as f
from mcs_input_text import InputRecord
from mcs_window_archive import ControlRecord

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
HOME = Path(__file__).resolve().parent.parent


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def pwsh():
    configured = os.environ.get('MCGS_PWSH')
    path = configured or shutil.which('pwsh')
    if not path or not Path(path).is_file():
        raise ValueError('PowerShell 7 required; set MCGS_PWSH to its executable path')
    return Path(path)


def db(request):
    process = subprocess.run([str(pwsh()), '-NoProfile', '-NonInteractive', '-File', str(HOME/'scripts/database.ps1')],
                             input=json.dumps(request, ensure_ascii=True).encode('ascii'),
                             capture_output=True, timeout=120)
    if process.returncode:
        error = process.stderr.decode('utf-8-sig', errors='replace')
        raise RuntimeError('Database operation failed: '+error[:1200])
    return json.loads(process.stdout.decode('utf-8-sig'))


def one(items):
    items=list(items)
    if len(items)!=1:
        raise ValueError(f'Unique object required, found {len(items)}')
    return items[0]


def system(data, name):
    return one(r for r in data['System']['rows'] if r['strName']==name)


def canonical(data):
    return {key: {'fields':[(v['name'],v['type'],v.get('auto_increment',False)) for v in value['fields']],
                  'indexes':sorted((x['name'],x['primary'],x['unique'],tuple(x['columns'])) for x in value.get('indexes',[])),
                  'rows':sorted(json.dumps(r,sort_keys=True,ensure_ascii=True) for r in value['rows'])}
            for key,value in data.items()}


def title(value):
    if not isinstance(value,str) or not value or len(value.encode('utf-16le'))//2>32 or '\x00' in value:
        raise ValueError('Object names require 1..32 characters without NUL')
    return value


def set_variables(data, additions, updates):
    row=system(data,'ObjData'); rows=f.variables(f.binary(row['lbContext']))
    templates=json.loads((HOME/'assets/primitives.json').read_text(encoding='utf-8'))
    validate_initial = {item['name'] for item in additions}
    validate_initial.update(item['name'] for item in updates if 'initial' in item)
    for item in additions:
        if set(item)-{'name','type','initial','note','unit'}:
            raise ValueError('Unknown variable property')
        name=title(item['name']);kind=item['type']
        if any(r['name']==name for r in rows) or kind not in templates['variables']:
            raise ValueError('Duplicate variable or unsupported type')
        template=templates['variables'][kind]
        rows.append({'id':max((r['id'] for r in rows),default=-1)+1,'name':name,'kind':template['kind'],
                     'note':item.get('note',''),'unit':item.get('unit',''),
                     'initial':str(item.get('initial','0')),
                     'prefix':bytes.fromhex(template['prefix']), 'extension':bytes.fromhex(template['extension'])})
    for item in updates:
        if set(item)-{'name','initial','note','unit'}:
            raise ValueError('Unknown variable update')
        target=one(r for r in rows if r['name']==item['name'])
        if target['kind'] not in (1,2,3):
            raise ValueError('Only scalar variable properties can be changed')
        for key in ('initial','note','unit'):
            if key in item:target[key]=str(item[key])
    for r in rows:
        if r['name'] in validate_initial and r['kind'] in (1,2):
            try: value=float(r['initial'])
            except ValueError:raise ValueError('Numeric initial value required')
            if not __import__('math').isfinite(value) or (r['kind']==1 and value not in (0,1)):
                raise ValueError('Invalid numeric initial value')
    if additions or updates:
        row['lbContext']=f.wrap(f.pack_variables(rows))
    return {r['name']:r for r in rows}


def control(item, variables, primitives):
    if set(item)-{'type','name','bounds','text','binding','minimum','maximum'}:
        raise ValueError('Unknown control property')
    preset=primitives['controls'].get(item['type'])
    if preset is None:raise ValueError('Unsupported control type')
    edits={k:v for k,v in item.items() if k!='type'}
    title(edits['name'])
    if 'binding' in edits:
        if edits['binding'] not in variables:raise ValueError('Unknown variable binding')
        if variables[edits['binding']]['kind'] not in (1,2):raise ValueError('Numeric input requires numeric variable')
        edits['binding_id']=variables[edits['binding']]['id']
        edits['binding_type']=variables[edits['binding']]['kind']
    elif item['type']=='numeric-input':raise ValueError('Numeric input binding required')
    payload=bytes.fromhex(preset['payload'])
    if item['type']=='numeric-input':
        parsed=InputRecord.parse(ControlRecord(preset['kind'],payload,b'',0))
        parsed.disable_images()
        payload=parsed.to_bytes()
    return preset['kind'],f.edit_control(preset['kind'],payload,edits)


def root_startup(blob, prefix_size, page_name, page_id):
    pos=prefix_size
    for strings in (True,False,True,False):
        count=struct.unpack_from('<H',blob,pos)[0];pos+=2
        for _ in range(count):
            if strings:_,pos=f.string(blob,pos)
            else:pos+=4
    return (blob[:prefix_size]+struct.pack('<H',1)+f.text(page_name)+struct.pack('<HI',1,page_id)
            +bytes(4)+blob[pos:])


def create_data(spec):
    if set(spec)-{'variables','pages'}:raise ValueError('Unknown project property')
    data=json.loads((HOME/'assets/blank-project.json').read_text(encoding='utf-8'))
    presets=json.loads((HOME/'assets/primitives.json').read_text(encoding='utf-8'))
    variables=set_variables(data,spec.get('variables',[]),[])
    base=data['WndUser']['rows'][0];header,_,trailer=f.window(f.binary(base['lbObjects']))
    pages=[]
    for ident,item in enumerate(spec['pages'],1):
        if set(item)-{'name','controls'}:raise ValueError('Unknown page property')
        name=title(item['name']);controls=[control(c,variables,presets) for c in item.get('controls',[])]
        if len({f.common(b)['name'] for _,b in controls})!=len(controls):raise ValueError('Duplicate control name')
        row=copy.deepcopy(base);row.update(iID=ident,strName=name,iCompileFlag=0)
        row['lbObjects']=f.wrap(f.pack_window(header,controls,f.page_properties(trailer,ident=ident,name=name)))
        pages.append(row)
    if not pages or len({r['strName'] for r in pages})!=len(pages):raise ValueError('Unique nonempty page list required')
    data['WndUser']['rows']=pages
    root=data['WndControl']['rows'][0]
    root['lbObjects']=f.wrap(root_startup(f.binary(root['lbObjects']),presets['root_prefix_size'],pages[0]['strName'],1))
    return data


def inspect_data(data):
    result={'version':f.binary(system(data,'MCGSVER')['lbContext']).decode('utf-16le').rstrip('\x00'),
            'variables':[], 'pages':[]}
    for row in f.variables(f.binary(system(data,'ObjData')['lbContext'])):
        result['variables'].append({k:row[k] for k in ('id','name','kind','initial','note','unit')})
    for row in data['WndUser']['rows']:
        _,records,_=f.window(f.binary(row['lbObjects'])); controls=[]
        for index,(kind,b) in enumerate(records):
            c={'index':index,'kind':hex(kind),'sha256':hashlib.sha256(b).hexdigest()}
            try:
                props=f.common(b);c.update(name=props['name'],bounds=props['bounds'])
                if kind==0x5008 and f.u32(b,props['name_end'])==12:
                    c['text']=f.string(b,props['name_end']+14)[0]
            except (ValueError,UnicodeError,struct.error):c['properties']='opaque'
            controls.append(c)
        result['pages'].append({'id':row['iID'],'name':row['strName'],'controls':controls})
    return result


def edit_data(data,spec):
    if set(spec)-{'source_sha256','add_variables','variables','pages'}:raise ValueError('Unknown edit property')
    variables=set_variables(data,spec.get('add_variables',[]),spec.get('variables',[]))
    primitives=json.loads((HOME/'assets/primitives.json').read_text(encoding='utf-8'))
    for page in spec.get('pages',[]):
        if set(page)-{'id','controls','add_controls'}:raise ValueError('Unknown page edit')
        row=one(r for r in data['WndUser']['rows'] if r['iID']==page['id'])
        header,records,trailer=f.window(f.binary(row['lbObjects']))
        for change in page.get('controls',[]):
            if set(change)!={'name','sha256','edits'}:raise ValueError('Name, sha256 and edits required')
            hits=[]
            for index,(kind,b) in enumerate(records):
                try:
                    if f.common(b)['name']==change['name']:hits.append(index)
                except (ValueError,UnicodeError,struct.error):pass
            index=one(hits);kind,b=records[index]
            if hashlib.sha256(b).hexdigest()!=change['sha256']:raise ValueError('Control preimage mismatch')
            edits=dict(change['edits'])
            if 'name' in edits:title(edits['name'])
            if 'binding' in edits:
                target=variables.get(edits['binding'])
                if target is None or target['kind'] not in (1,2):raise ValueError('Numeric binding not found')
                edits['binding_id']=target['id']
                edits['binding_type']=target['kind']
            records[index]=(kind,f.edit_control(kind,b,edits))
        records.extend(control(c,variables,primitives) for c in page.get('add_controls',[]))
        names=[]
        for _,b in records:
            try:names.append(f.common(b)['name'])
            except (ValueError,UnicodeError,struct.error):pass
        if len(set(names))!=len(names):raise ValueError('Duplicate control name')
        row['lbObjects']=f.wrap(f.pack_window(header,records,trailer));row['iCompileFlag']=0
    return data


def read(path):
    return db({'action':'read','path':str(Path(path).resolve())})


def ensure_output(path):
    path=Path(path).absolute()
    if path.suffix.lower()!='.mcp' or path.exists() or not path.parent.is_dir():
        raise ValueError('New .mcp output in an existing directory required')
    for parent in (path,*path.parents):
        if parent.is_symlink() or (parent.exists() and getattr(parent.stat(),'st_file_attributes',0)&1024):
            raise ValueError('Linked output rejected')
    return path


def check_family(data):
    version=f.binary(system(data,'MCGSVER')['lbContext']).decode('utf-16le').rstrip('\x00')
    if not version.startswith('McgsPro '):raise ValueError('Expected a native McgsPro family project; software release is informational')


def write_project(output,spec,source=None):
    output=ensure_output(output)
    if source:
        source=Path(source).resolve()
        before_sha=sha(source)
        if before_sha!=spec.get('source_sha256'):raise ValueError('Source SHA256 mismatch')
        before=read(source);check_family(before)
        after=edit_data(copy.deepcopy(before),spec)
        if sha(source)!=before_sha:raise ValueError('Source changed while planning')
        with source.open('rb') as src,output.open('xb') as dst:shutil.copyfileobj(src,dst)
        changes=[]
        for table,new in after.items():
            key='iID' if table in ('System','WndUser') else None
            for old,row in zip(before[table]['rows'],new['rows']):
                values={k:v for k,v in row.items() if v!=old[k]}
                if values:
                    if not key:raise ValueError('Unexpected table modification')
                    changes.append({'action':'update','table':table,'key':key,'id':row[key],'values':values})
        db({'action':'write','path':str(output),'changes':changes})
    else:
        before_sha=None;after=create_data(spec)
        db({'action':'create','path':str(output),'seed':after})
    actual=read(output)
    if canonical(actual)!=canonical(after):
        raise ValueError('Output full-table readback mismatch; candidate is not accepted')
    if source and sha(source)!=before_sha:raise ValueError('Original changed; candidate is not accepted')
    return {'status':'file_readback_passed','output':str(output),'sha256':sha(output),
            'source_unchanged':True if source else None,'tables_checked':len(actual),
            'pages':len(actual['WndUser']['rows']),'host_validation':'pending','physically_tested':False}


def main():
    if sys.version_info < (3,11):
        raise ValueError('Python 3.11 or newer is required')
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    doctor=sub.add_parser('doctor');doctor.add_argument('--workdir',default='.')
    demo=sub.add_parser('demo');demo.add_argument('--directory',required=True)
    view=sub.add_parser('inspect');view.add_argument('source')
    for cmd in ('create','edit'):
        p=sub.add_parser(cmd);p.add_argument('--spec',required=True);p.add_argument('--output',required=True)
        if cmd=='edit':p.add_argument('--source',required=True)
    args=parser.parse_args()
    if args.command=='doctor':
        result=db({'action':'doctor'})
        folder=Path(args.workdir).resolve()
        if not folder.is_dir():raise ValueError('Existing writable doctor workdir required')
        scratch=folder/('.mcgs-doctor-'+__import__('uuid').uuid4().hex+'.mdb')
        seed={'Probe':{'fields':[{'name':'iID','type':3,'size':4},{'name':'payload','type':205,'size':4}],
                       'rows':[{'iID':1,'payload':f.wrap(bytes([0,1,2,255]))}]}}
        try:
            db({'action':'create','path':str(scratch),'seed':seed})
            observed=read(scratch)
            if canonical(observed)!=canonical(seed):raise ValueError('Provider BLOB roundtrip failed')
            result['ace_create_and_blob_readback']=True
        finally:
            if scratch.is_file():scratch.unlink()
        result.update(python=sys.version,python_packages_required=[],mcp_server_required=False,
                      target_family='McgsPro', template_provenance='McgsPro 3.5.1.6963', software_version_gate=False)
    elif args.command=='demo':
        folder=Path(args.directory).absolute();folder.mkdir(exist_ok=False)
        initial=json.loads((HOME/'examples/create.json').read_text(encoding='utf-8'))
        first=write_project(folder/'demo.mcp',initial)
        observed=inspect_data(read(folder/'demo.mcp'))
        label=one(c for c in observed['pages'][0]['controls'] if c.get('name')=='标题')
        plan={'source_sha256':first['sha256'],
              'variables':[{'name':'设定值','initial':'35'}],
              'pages':[{'id':1,'controls':[{'name':'标题','sha256':label['sha256'],
                        'edits':{'text':'离线修改后的工程标题'}}]}]}
        (folder/'edit.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
        second=write_project(folder/'demo-edited.mcp',plan,folder/'demo.mcp')
        result={'create':first,'edit':second,'host_validation':'pending'}
        (folder/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    elif args.command=='inspect':
        result=inspect_data(read(args.source));result['source_sha256']=sha(args.source)
    else:
        spec=json.loads(Path(args.spec).read_text(encoding='utf-8-sig'))
        result=write_project(args.output,spec,getattr(args,'source',None))
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'status':'error','type':type(exc).__name__,'message':str(exc)},ensure_ascii=False))
        sys.exit(1)
