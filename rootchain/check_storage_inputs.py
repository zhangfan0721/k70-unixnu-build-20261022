"""Verify the real selected components, closure, rebased constructors and entrypoints.

No original component is executed. This is a static prerequisite, never runtime
or complete C++ object-layout qualification. Apple bytes and reports stay local.
"""
from pathlib import Path
import argparse,hashlib,json,struct,sys,subprocess

EXPECTED={'com.apple.iokit.IOStorageFamily':'2.1','com.apple.filesystems.hfs.kext':'627.100.6'}
KPI={'com.apple.kpi.'+s for s in ('mach','private','unsupported','iokit','libkern','bsd')}
PIN='2b6ffb50117eee820b98aca9bd51b5c7dfb2970e'
ORIGINAL='2ec297bac95bcba01046fd0148e97e7e5885c05a6c18827f39f534ba375c1221'

def digest(data):return hashlib.sha256(data).hexdigest()

def main():
    p=argparse.ArgumentParser()
    for name in ('tool','native','original','candidate','report','out'):
        p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();a.out.mkdir()
    assert subprocess.check_output(['git','-C',str(a.tool),'rev-parse','HEAD'],text=True).strip()==PIN
    assert not subprocess.check_output(['git','-C',str(a.tool),'diff','--name-only'],text=True)
    sys.path.insert(0,str(a.tool))
    from native_prelink import macho,backed_offset,unserialize_xml
    old,native,candidate=[x.read_bytes() for x in (a.original,a.native,a.candidate)]
    report=json.loads(a.report.read_text())
    assert digest(old)==ORIGINAL and digest(native)==report['native_sha256']
    assert digest(candidate)==report['candidate_sha256']
    assert set(report['components'])==set(EXPECTED) and not report['codeless_components']
    assert set(report['kernel_interfaces'])==KPI and not report['early_security_initializers']
    segments=macho(candidate)['segments'];original_segments=macho(old)['segments']
    info=next(s for s in segments if s['name']=='__PRELINK_INFO')
    # Legacy arm_vm_init derives static slide bounds from this end address.
    # Check actual output geometry, not just the producer's report.
    assert all(s['va']+s['size']<=info['va'] for s in segments if s['size'] and s is not info), 'PRELINK_INFO must follow all static segments'
    def metadata(data,segments):
        info=next(s for s in segments if s['name']=='__PRELINK_INFO')
        at=backed_offset(segments,info['va'],info['filesize'],len(data))
        return unserialize_xml(data[at:at+info['filesize']])
    original_entries={e['CFBundleIdentifier']:e for e in metadata(old,original_segments)['_PrelinkInfoDictionary']}
    entries={e['CFBundleIdentifier']:e for e in metadata(candidate,segments)['_PrelinkInfoDictionary']}
    selected=set(EXPECTED);pending=list(EXPECTED)
    while pending:
        for dep in original_entries[pending.pop()].get('OSBundleLibraries',{}):
            if dep not in selected:selected.add(dep);pending.append(dep)
    assert selected==set(entries)==set(EXPECTED)|KPI
    assert all(entries[k].get('OSKernelResource') is True for k in KPI)
    proof={}
    for name,version in EXPECTED.items():
        entry=entries[name];original=original_entries[name]
        assert entry['CFBundleVersion']==version and entry['OSBundleRequired']=='Local-Root'
        assert entry['OSBundleLibraries']==original['OSBundleLibraries']
        assert entry['IOKitPersonalities']==original['IOKitPersonalities']
        assert entry.get('OSKernelResource') is not True
        h=backed_offset(segments,entry['_PrelinkExecutableLoadAddr'],32,len(candidate))
        image=macho(candidate,h)
        executable=[s for s in image['segments'] if s['name']=='__TEXT_EXEC' and s['filesize']]
        def is_code(value):return any(s['va']<=value<s['va']+s['filesize'] for s in executable)
        starts=report['module_entrypoints'][name]
        at=backed_offset(segments,entry['_PrelinkKmodInfo']+180,16,len(candidate))
        start,stop=struct.unpack_from('<QQ',candidate,at)
        assert start==starts['start_va'] and stop==starts['stop_va'] and is_code(start) and is_code(stop)
        constructors=[]
        for segment in image['segments']:
            for section in segment['sections']:
                if section['name']!='__mod_init_func':continue
                assert section['size'] and section['size']%8==0
                at=backed_offset(segments,section['va'],section['size'],len(candidate))
                constructors.extend(struct.unpack_from('<'+'Q'*(section['size']//8),candidate,at))
        assert constructors and all(is_code(c) for c in constructors)
        hashes=[]
        for segment in executable:
            at=backed_offset(segments,segment['va'],segment['filesize'],len(candidate))
            hashes.append(digest(candidate[at:at+segment['filesize']]))
        assert len(hashes)==1 and hashes[0]==report['original_executable_sha256'][name]
        proof[name]={'version':version,'constructors':list(map(hex,constructors)),
                     'start':hex(start),'stop':hex(stop),'original_executable_sha256':hashes[0],
                     'original_dependencies_and_personalities_unchanged':True}
    header_index=report['sparse_index']
    at=backed_offset(segments,header_index['va'],header_index['size'],len(candidate))
    headers=list(struct.unpack_from('<2Q',candidate,at))
    assert headers==sorted(entries[n]['_PrelinkExecutableLoadAddr'] for n in EXPECTED)
    result={'original_sha256':digest(old),'native_sha256':digest(native),'candidate_sha256':digest(candidate),
            'dependency_closure':sorted(selected),'modules':proof,'rebased_constructor_and_start_pointers_checked':True,
            'original_execution_bytes_preserved':True,'sparse_header_index_checked':True,
            'legacy_static_slide_extent_covers_all_segments':True,
            'pointer_counts':report['pointer_counts'],'hardware_storage_backends_added':False,
            'complete_cpp_abi_qualified':False,'runtime_initialization_verified':False,'md0_mount_verified':False}
    (a.out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='modules'},indent=2))

if __name__=='__main__':main()
