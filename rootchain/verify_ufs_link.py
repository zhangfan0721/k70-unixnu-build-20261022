"""Bind actual iOS16 compile records, fixed UFS source and linked call sites.

No device I/O. This is static qualification, never hardware read success.
"""
from pathlib import Path
import argparse,hashlib,json,subprocess,sys,struct
def check(kernel,evidence,source,out):
    out.mkdir(exist_ok=False)
    records=list(evidence.rglob('IOKitBSDInit.cpo.json'))
    assert len(records)==1
    record=json.loads(records[0].read_text().strip().rstrip(','))
    assert '--target=arm64-apple-ios16.0.0' in record['arguments']
    assert '-mios-version-min=16.0' in record['arguments']
    assert 'XNU_TARGET_OS_IOS' in record['arguments']
    commit,=[p.read_text().strip() for p in evidence.rglob('integration-commit.txt')]
    report_path,=evidence.rglob('iphone16-patch-report.json')
    patch=json.loads(report_path.read_text())
    files={}
    for p in (source/'iphone16/ufs').iterdir():
        if p.suffix not in ('.h','.inc') or p.name.startswith('test_'):continue
        sha=hashlib.sha256(p.read_bytes()).hexdigest()
        assert patch['files']['iokit/bsddev/'+p.name]['after']==sha,p.name
        files[p.name]=sha
    sys.path.insert(0,str(source/'iphone16/ufs'))
    from check_inputs import check as scope_check
    scope=scope_check()
    symbols=subprocess.check_output(['llvm-nm','-n',str(kernel)],text=True)
    assert '_k70_ufs_readonly_qualify' in symbols
    for bad in ('_native_ufs_store_write','_native_ufs_log_write','_native_ufs_export_write'):
        assert bad not in symbols
    for name in ('_IOFindBSDRoot','_k70_ufs_readonly_qualify'):
        assembly=subprocess.check_output(['llvm-objdump','-d','--no-show-raw-insn','--disassemble-symbols='+name,str(kernel)],text=True)
        (out/(name+'.asm')).write_text(assembly)
        if name=='_IOFindBSDRoot':assert '<_k70_ufs_readonly_qualify>' in assembly
        else:assert '<_k70_formal_cpu_trace>' in assembly and '<_boot_progress_stage>' in assembly
    result={'schema':1,'kernel_sha256':hashlib.sha256(kernel.read_bytes()).hexdigest(),
            'kernel_source_commit':commit,'actual_iokit_ios16_record':True,
            'compiled_ufs_source_hashes_match':files,'linked_normal_bsd_entry':True,
            'bounded_readonly_transport':True,'scope':scope,
            'hardware_read_verified':False,'hashes_matched_on_device':False}
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('kernel','evidence','source','out'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();r=check(a.kernel,a.evidence,a.source,a.out)
    print(json.dumps({k:v for k,v in r.items() if k not in ('scope','compiled_ufs_source_hashes_match')},indent=2))
