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


def prepare_armcpu_source(source, out):
    text=Path(source).read_text()
    if hashlib.sha256(text.encode()).hexdigest()!=ARMCPU_SHA:
        raise ValueError('Unexpected pinned ArmCpu source')
    before='"msr icc_sgi1r_el1, %0; isb; mrs %1, cntvct_el0" : "=r" (tb) : "r" (sgi)'
    after='"msr icc_sgi1r_el1, %1; isb; mrs %0, cntvct_el0" : "=r" (tb) : "r" (sgi)'
    if text.count(before)!=1: raise ValueError('Unexpected SGI measurement operands')
    fixed=normalize_inline_asm(text.replace(before,after))
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    target=out/'ArmCpu.cpp';target.write_text(fixed)
    (out/'normalization.json').write_text(__import__('json').dumps(dict(
        source_sha256=ARMCPU_SHA,effective_sha256=hashlib.sha256(fixed.encode()).hexdigest(),
        scope='instruction separators and SGI input/output operands; native register policy unchanged'),indent=2)+'\n')
    return target
