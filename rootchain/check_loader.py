"""Run the pinned loader's actual parsers on candidate bytes, on the host only."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def check(source, kernel, trust, out):
    if out.exists():
        raise ValueError('Refusing to replace loader evidence')
    text = source.read_text()
    # Preserve the implementation verbatim; only UEFI scalar/library wrappers are replaced.
    declarations = text[text.index('#define WINDOW_SIZE'):text.index('STATIC EFI_HANDLE')]
    parsers = []
    for name in ('ParseKernel', 'ValidTrustCaches'):
        start = text.index('STATIC\n', text.index('\n' + name + ' (') - 25)
        brace = text.index('{', start)
        depth, end = 1, brace + 1
        while depth:
            depth += (text[end] == '{') - (text[end] == '}')
            end += 1
        parsers.append(text[start:end])
    prefix = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
typedef uint8_t UINT8; typedef uint32_t UINT32; typedef uint64_t UINT64;
typedef size_t UINTN; typedef int BOOLEAN; typedef int EFI_STATUS;
#define STATIC static
#define CONST const
#define VOID void
#define TRUE 1
#define FALSE 0
#define EFI_SUCCESS 0
#define EFI_UNSUPPORTED 1
#define EFI_LOAD_ERROR 2
#define SIZE_256MB (256ULL<<20)
#define SIZE_2MB (2ULL<<20)
#define MAX_UINT64 UINT64_MAX
#define EFI_PAGE_MASK 4095
#define ZeroMem(p,n) memset(p,0,n)
#define CompareMem(a,b,n) memcmp(a,b,n)
#define MIN(a,b) ((a)<(b)?(a):(b))
#define MAX(a,b) ((a)>(b)?(a):(b))
static UINT32 U32(const void*p){UINT32 v;memcpy(&v,p,4);return v;}
static UINT64 U64(const void*p){UINT64 v;memcpy(&v,p,8);return v;}
'''
    main = r'''
static UINT8 *readall(const char *path,UINTN *n){
 FILE*f=fopen(path,"rb");assert(f);assert(!fseek(f,0,SEEK_END));
 long size=ftell(f);assert(size>0);*n=(UINTN)size;rewind(f);
 UINT8*p=malloc(*n);assert(p);assert(fread(p,1,*n,f)==*n);fclose(f);return p;
}
int main(int argc,char**argv){
 assert(argc==3);UINTN kn,tn;UINT8*k=readall(argv[1],&kn),*t=readall(argv[2],&tn);KERNEL parsed;
 assert(ParseKernel(k,kn,&parsed)==EFI_SUCCESS);
 assert(ParseKernel(k,31,&parsed)!=EFI_SUCCESS);
 assert(ParseKernel(k,kn,&parsed)==EFI_SUCCESS);
 assert(ValidTrustCaches(t,tn));assert(!ValidTrustCaches(t,7));
 t[0]=0;assert(!ValidTrustCaches(t,tn));
 printf("{\"segments\":%zu,\"virtual_span\":%llu,\"entry\":\"0x%llx\",\"real_parsers_passed\":true,\"negative_inputs_rejected\":true}\n",
 parsed.Count,(unsigned long long)(parsed.End-parsed.Base),(unsigned long long)parsed.Entry);
 free(k);free(t);return 0;
}
'''
    out.mkdir(parents=True)
    fixture = out / 'actual-loader-parsers.c'
    fixture.write_text(prefix + declarations + '\n'.join(parsers) + main)
    executable = out / 'actual-loader-parsers'
    subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror', str(fixture),
                    '-o', str(executable)], check=True)
    proof = json.loads(subprocess.check_output([str(executable), str(kernel), str(trust)], text=True))
    proof.update(loader_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                 kernel_sha256=hashlib.sha256(kernel.read_bytes()).hexdigest(),
                 trust_sha256=hashlib.sha256(trust.read_bytes()).hexdigest(),
                 runtime_qualified=False, device_operations=False)
    (out / 'result.json').write_text(json.dumps(proof, indent=2) + '\n')
    return proof


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'kernel', 'trust', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.source, args.kernel, args.trust, args.out), indent=2))
