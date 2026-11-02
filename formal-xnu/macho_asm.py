"""Preserve multi-instruction inline assembly on both Darwin and ELF assemblers."""
import hashlib
from pathlib import Path
import re

# Only the initial adjacent C string literals of an asm statement, never C code
# or constraints. Darwin AArch64 treats ';' as a comment, unlike the ELF target.
ASM_STRINGS=re.compile(r'(__asm__\s+volatile\s*\(\s*)((?:"(?:\\.|[^"\\])*"\s*)+)',re.S)
ARMCPU_SHA='3c87b3bd617be5582a6a24ff797c359497ee9feaa702ee883ecee4270db21c9f'


def normalize_inline_asm(text):
    return ASM_STRINGS.sub(lambda m:m[1]+m[2].replace(';',r'\n\t'),text)


def instrument_armcpu(text):
    # Formal BUILD COPY only. Every original condition, register access and
    # return value remains intact; traces perform no new MMIO accesses.
    declaration='extern "C" void k70_formal_cpu_trace(const char *, uint64_t);\n'
    anchor='extern "C" void rtclock_intr (unsigned int);'
    if text.count(anchor)!=1:raise ValueError('CPU trace declaration anchor changed')
    text=text.replace(anchor,declaration+anchor)
    for name,signature in [('mapGic','void'),('initDistributor','void'),
                           ('wakeRedistributor','bool local'),('prepareGic','void'),
                           ('start','IOService *provider')]:
        anchor='bool ArmCpu::'+name+' ('+signature+')\n{'
        if text.count(anchor)!=1:raise ValueError('CPU trace function changed: '+name)
        begin=text.index(anchor)+len(anchor);end=begin;depth=1
        while depth:
            depth+=(text[end]=='{')-(text[end]=='}');end+=1
        body=text[begin:end-1]
        failure=0
        def trace_return(match):
            nonlocal failure
            if match[1]=='false':
                failure+=1
                label='FAIL '+name+' #'+str(failure)
            else:label=name+' passed'
            return 'k70_formal_cpu_trace("'+label+'", '+('1' if match[1]=='true' else '0')+'); '+match[0]
        body=re.sub(r'return (false|true);',trace_return,body)
        text=text[:begin]+'\n  k70_formal_cpu_trace("'+name+' enter", 0);'+body+text[end-1:]
    for anchor,line in [
        ('  return IOCPU::probe (provider, score);','  k70_formal_cpu_trace("CPU probe accepted", id);\n'),
        ('  armcpu_registered = 1;','\n  k70_formal_cpu_trace("CPU registered", physical);'),
        ('  armcpu_gic_ready = 1;','\n  k70_formal_cpu_trace("GIC enabled", 1);')]:
        if text.count(anchor)!=1:raise ValueError('CPU trace checkpoint changed')
        text=text.replace(anchor,line+anchor if 'probe' in anchor else anchor+line)
    anchor='    if (counter () - started > frequency / 10) {\n'
    if text.count(anchor)!=1:raise ValueError('GIC wait timeout anchor changed')
    text=text.replace(anchor,anchor+
        '      k70_formal_cpu_trace("FAIL waitClear timeout", (static_cast<uint64_t>(offset) << 32) | mask);\n')
    return text


def prepare_armcpu_source(source, out):
    text=Path(source).read_text()
    if hashlib.sha256(text.encode()).hexdigest()!=ARMCPU_SHA:
        raise ValueError('Unexpected pinned ArmCpu source')
    before='"msr icc_sgi1r_el1, %0; isb; mrs %1, cntvct_el0" : "=r" (tb) : "r" (sgi)'
    after='"msr icc_sgi1r_el1, %1; isb; mrs %0, cntvct_el0" : "=r" (tb) : "r" (sgi)'
    if text.count(before)!=1: raise ValueError('Unexpected SGI measurement operands')
    fixed=normalize_inline_asm(instrument_armcpu(text.replace(before,after)))
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    target=out/'ArmCpu.cpp';target.write_text(fixed)
    (out/'normalization.json').write_text(__import__('json').dumps(dict(
        source_sha256=ARMCPU_SHA,effective_sha256=hashlib.sha256(fixed.encode()).hexdigest(),
        scope='instruction separators, SGI operands and formal CPU lifecycle traces; native register policy unchanged'),indent=2)+'\n')
    return target
