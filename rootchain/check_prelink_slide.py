"""Exercise the fixed XNU static-slide consumer on actual component geometry."""
from pathlib import Path
import argparse,subprocess,json,sys,struct,hashlib

def body(text,name):
    start=text.index('\n'+name+'(')+1
    at=text.index('{',start);end=at+1;depth=1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]

def main():
    p=argparse.ArgumentParser()
    for name in ('source','tool','candidate','out'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();a.out.mkdir();sys.path.insert(0,str(a.tool))
    from native_prelink import macho,backed_offset,unserialize_xml
    header=(a.source/'osfmk/mach/vm_param.h').read_text()
    routines=(a.source/'osfmk/arm64/machine_routines.c').read_text()
    init=(a.source/'osfmk/arm64/arm_vm_init.c').read_text()
    assert 'vm_kernel_slid_top = vm_prelink_einfo;' in init
    functions='static inline bool\n'+body(header,'vm_is_addr_slid')+'\nvm_offset_t\n'+body(routines,'ml_static_slide')
    fixture=a.out/'actual-slide.c'
    fixture.write_text('#include <stdint.h>\n#include <stdbool.h>\n#include <stdio.h>\n#include <stdlib.h>\n'
        'typedef uint64_t vm_offset_t;static uint64_t vm_kernel_slide,vm_kernel_slid_base,vm_kernel_slid_top;\n'
        '#define VM_KERNEL_STRIP_PTR(x) (x)\n#define VM_KERNEL_IS_SLID(x) vm_is_addr_slid(x)\n'+functions+
        '\nint main(int c,char**v){if(c<5)return 2;vm_kernel_slid_base=strtoull(v[1],0,0);'
        'vm_kernel_slid_top=strtoull(v[2],0,0);vm_kernel_slide=strtoull(v[3],0,0);'
        'for(int i=4;i<c;i++)printf("%llu\\n",(unsigned long long)ml_static_slide(strtoull(v[i],0,0)));}\n')
    binary=a.out/'actual-slide';subprocess.run(['clang','-std=c11','-O1','-Wall','-Wextra','-Werror',str(fixture),'-o',str(binary)],check=True)
    data=a.candidate.read_bytes();segments=macho(data)['segments']
    info=next(s for s in segments if s['name']=='__PRELINK_INFO')
    at=backed_offset(segments,info['va'],info['filesize'],len(data))
    entries=unserialize_xml(data[at:at+info['filesize']])['_PrelinkInfoDictionary']
    low=min(s['va'] for s in segments if s['size'] and s['initprot']&4);top=info['va']+info['size']
    outside=subprocess.check_output([str(binary),hex(low),hex(top),'0',hex(low-1),hex(top)],text=True)
    assert list(map(int,outside.splitlines()))==[0,0], 'Actual consumer must still reject out-of-range addresses'
    results=[]
    for entry in entries:
        if entry['CFBundleIdentifier'] not in ('com.apple.iokit.IOStorageFamily','com.apple.filesystems.hfs.kext'):continue
        at=backed_offset(segments,entry['_PrelinkExecutableLoadAddr'],32,len(data));module=macho(data,at)
        segs=[s for s in module['segments'] if s['size'] and s['name']!='__LINKEDIT']
        args=[str(binary),hex(low),hex(top),'0',*[hex(s['va']) for s in segs]]
        slid=list(map(int,subprocess.check_output(args,text=True).splitlines()))
        at=backed_offset(segments,entry['_PrelinkKmodInfo']+180,16,len(data));start,stop=struct.unpack_from('<QQ',data,at)
        passes=all(any(va<=value<va+s['size'] for s,va in zip(segs,slid) if va) for value in (start,stop))
        results.append({'component':entry['CFBundleIdentifier'],'input_segment_addresses':[hex(s['va']) for s in segs],
            'actual_ml_static_slide_results':list(map(hex,slid)),'start':hex(start),'stop':hex(stop),'post_slide_segment_range_passes':passes})
    result={'candidate_sha256':hashlib.sha256(data).hexdigest(),'actual_xnu_static_slide_functions_used':True,
        'legacy_static_slid_top':hex(top),'components':results,'outside_addresses_still_rejected':True,
        'consumer_functions_sha256':hashlib.sha256(functions.encode()).hexdigest(),'hardware_tested':False}
    (a.out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
    assert len(results)==2 and all(r['post_slide_segment_range_passes'] for r in results),'Actual XNU static slide destroys component segment bounds'
if __name__=='__main__':main()
