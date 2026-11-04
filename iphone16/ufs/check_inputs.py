"""Fail closed on inherited write paths, private inputs, or scope expansion."""
from pathlib import Path
import hashlib
import json
import re
HERE=Path(__file__).resolve().parent
def check():
    files={p.name:p for p in HERE.iterdir() if p.suffix in ('.h','.inc') and not p.name.startswith('test_')}
    # Inspect the actual transitive include set, not preserved, uninstantiated
    # planners/writers that this diagnostic candidate never includes.
    compiled={}
    def include(name):
        if name in compiled:return
        text=files[name].read_text();compiled[name]=text
        for dependency in re.findall(r'^\s*#\s*include\s+"([^"]+)"',text,re.M):
            if dependency in files:include(dependency)
    include('K70UfsTransport.inc')
    text='\n'.join(compiled.values())
    code=re.sub(r'/\*.*?\*/|//[^\n]*','',text,flags=re.S)
    for word in ('hostWrite4k','hostSyncCache','smmuBypassStream','native_ufs_store_',
                 'native_ufs_log_','native_ufs_export_','verified_root','hostStoreOpen','hostLogOpen'):
        if word in code:raise ValueError('Forbidden compiled implementation: '+word)
    commands=(HERE/'ReadOnlyCommands.inc').read_text()
    if commands.count('K70UfsPolicy::command(lun,cdb,cdbLength,direction,dataBytes)')!=1:
        raise ValueError('Missing SCSI policy gate')
    if commands.count('if (direction == 1) return kIOReturnNotPermitted;')!=1:
        raise ValueError('Missing data-out rejection at submit boundary')
    if 'hostScsi (0xd0' in code:raise ValueError('Unexpected power-state command')
    offsets=set(int(x,16) for x in re.findall(r'hostWrite\s*\(\s*(0x[0-9a-f]+)',code))
    if offsets!={0x20,0x24,0x50,0x54,0x58,0x60}:raise ValueError('Controller write-set changed')
    # The reusable HC command writer remains compiled but unreachable from
    # hostBringUp's unconditional diagnostic stop. There is no SMMU writer.
    stores=re.findall(r'write32\s*\(([^;]+)\);',code)
    if stores!=['gHost.hc, offset, value']:raise ValueError('Physical store target changed: '+str(stores))
    if {'K70Smmu.h','SmmuTakeover.h'}&compiled.keys():raise ValueError('Diagnostic includes SMMU planner/writer')
    transport=compiled['K70UfsTransport.inc']
    bringup=transport[transport.index('static bool hostBringUp'):transport.index('\n}\n}',transport.index('static bool hostBringUp'))+2]
    bringup=re.sub(r'/\*.*?\*/|//[^\n]*','',bringup,flags=re.S)
    for word in ('hostStopQueue','hostStartQueue','k70Configure','k70Plan','hostWrite','write32',
                 'IOBufferMemoryDescriptor::','IOLockAlloc','hostNop','hostQueryRead'):
        if word in bringup:raise ValueError('Diagnostic path takes over/configures hardware: '+word)
    if (bringup.count('read32(')!=1 or
        'k70CollectSmmuEvidence(gSmmuEvidence,gHost.smmu,k70ReadTranslation,' not in bringup or
        '[](unsigned o){return read32(gHost.smmu,o);}' not in bringup or
        bringup.count('mapPhys(')!=1 or
        'mapPhys(0x15000000ULL,0xd0000,gHost.smmuMap)' not in bringup or
        'return true' in bringup or not bringup.rstrip().endswith('return false;\n}')):
        raise ValueError('Missing translation-gated snapshot/unconditional diagnostic stop')
    if 'k70DmaDescriptors(' not in commands:raise ValueError('Missing preserved DMA submission gate')
    return {'scope':'read-only mapped SMMU evidence; unconditional stop before controller takeover','storage_writes':False,
            'smmu_configuration_writes':False,'controller_takeover':False,
            'smmu_write_scope':'none in compiled diagnostic path',
            'hardware_dma_isolation':False,'persistent_log':False,
            'root_authentication_changed':False,'hardware_tested':False,
            'compiled_files':sorted(compiled),
            'files':{n:hashlib.sha256(p.read_bytes()).hexdigest() for n,p in sorted(files.items())}}
if __name__=='__main__':print(json.dumps(check(),indent=2))
