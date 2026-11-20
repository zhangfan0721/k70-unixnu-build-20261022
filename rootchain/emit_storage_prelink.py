"""Use pinned NativePrelink and complete its legacy XNU metadata placement.

Legacy arm_vm_init uses PRELINK_INFO's end as vm_kernel_slid_top. Place
that metadata after every static segment, without changing component bytes,
pointer bindings, protections, module sizes or kernel validation code.
"""
from pathlib import Path
import argparse,hashlib,importlib.util,json,struct,subprocess,sys

PIN='2b6ffb50117eee820b98aca9bd51b5c7dfb2970e'

def info_last(image,report,macho):
    parsed=macho(image);segments=parsed['segments']
    info,=[s for s in segments if s['name']=='__PRELINK_INFO']
    high=max(s['va']+s['size'] for s in segments if s['size'] and s is not info)
    new_va=(high+4095)&~4095
    if new_va+info['size']>=1<<64:raise ValueError('Metadata address overflow')
    old_va=info['va'];output=bytearray(image)
    changed=[(info['command_offset']+24,8)]
    struct.pack_into('<Q',output,changed[0][0],new_va)
    for section in info['sections']:
        if not old_va<=section['va']<=section['va']+section['size']<=old_va+info['size']:
            raise ValueError('Metadata section outside original segment')
        at=section['command_offset']+32
        struct.pack_into('<Q',output,at,new_va+section['va']-old_va);changed.append((at,8))
    # The only mutable bytes are the metadata segment/section VM addresses.
    cursor=0
    for at,size in sorted(changed):
        if output[cursor:at]!=image[cursor:at]:raise ValueError('Unexpected payload change')
        cursor=at+size
    if output[cursor:]!=image[cursor:]:raise ValueError('Unexpected payload tail change')
    macho(output)
    report['legacy_layout']={'upstream_pin':PIN,'original_candidate_sha256':hashlib.sha256(image).hexdigest(),
        'old_info_va':hex(old_va),'new_info_va':hex(new_va),'static_slid_top':hex(new_va+info['size']),
        'metadata_vm_fields_only':True,'runtime_qualified':False}
    for segment in report['coalesced_segments']:
        if segment['name']=='__PRELINK_INFO':segment['va']=new_va
    report['candidate_sha256']=hashlib.sha256(output).hexdigest()
    return bytes(output),report

def main():
    p=argparse.ArgumentParser()
    for name in ('tool','kernel','prelinked','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--root',action='append',required=True);p.add_argument('--slide',type=lambda v:int(v,0),required=True)
    a=p.parse_args()
    if a.output.exists() or a.output.with_suffix('.json').exists():raise ValueError('Candidate already exists')
    assert subprocess.check_output(['git','-C',str(a.tool),'rev-parse','HEAD'],text=True).strip()==PIN
    assert not subprocess.check_output(['git','-C',str(a.tool),'diff','--name-only'],text=True)
    sys.path.insert(0,str(a.tool));from native_prelink import macho
    spec=importlib.util.spec_from_file_location('pinned_prelink_emitter',a.tool/'emit_prelink.py')
    upstream=importlib.util.module_from_spec(spec);spec.loader.exec_module(upstream)
    image,report=upstream.emit(a.kernel.read_bytes(),a.prelinked.read_bytes(),a.root,a.slide)
    image,report=info_last(image,report,macho)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('xb') as f:f.write(image)
    with a.output.with_suffix('.json').open('x') as f:f.write(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'candidate_sha256':report['candidate_sha256'],'legacy_layout':report['legacy_layout']},indent=2))
if __name__=='__main__':main()
