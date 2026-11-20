"""Arm64 object check for the DW origin recorder: no FP/SIMD, no new deps.

Fails the build/test if the compiled module (or a unity translation unit that
includes it) uses q/v/d/s registers — the panic path has no FP/SIMD state.
"""
import argparse
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIMD = re.compile(r"\b[qvds][0-9]+\b")


def scan(obj: Path) -> list:
    asm = subprocess.check_output(["llvm-objdump", "-d", str(obj)], text=True).lower()
    bad = []
    for line in asm.splitlines():
        if "\t" not in line:
            continue
        ins = line.split("\t", 1)[-1]
        if SIMD.search(ins):
            bad.append((line.split(":")[0].strip(), ins.strip()))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--unity", type=Path, default=None,
                    help="optional C file that includes K70DwOrigin.c (real build TU)")
    a = ap.parse_args()
    a.out.mkdir(parents=True)
    targets = [(HERE / "K70DwOrigin.c", a.out / "K70DwOrigin.o")]
    if a.unity:
        targets.append((a.unity, a.out / "unity.o"))
    failed = False
    for src, obj in targets:
        cmd = ["clang", "--target=arm64-apple-ios16.0", "-mkernel", "-std=c11", "-O2",
               "-ffreestanding", "-fno-builtin", "-ftrivial-auto-var-init=zero",
               "-Wall", "-Wextra", "-Werror", "-I" + str(HERE), "-c", str(src), "-o", str(obj)]
        subprocess.run(cmd, check=True)
        undef = subprocess.check_output(["llvm-nm", "-u", str(obj)], text=True)
        actual = {ln.split()[-1] for ln in undef.splitlines() if ln.split()}
        if actual:
            print("FAIL  unexpected dependency:", sorted(actual))
            failed = True
        bad = scan(obj)
        if bad:
            print("FAIL  FP/SIMD in", src.name, "count=", len(bad))
            for addr, ins in bad[:10]:
                print("      ", addr, ins)
            failed = True
        else:
            print("PASS  no FP/SIMD in", src.name)
        (a.out / (obj.stem + "-disassembly.txt")).write_text(
            subprocess.check_output(["llvm-objdump", "-d", str(obj)], text=True))
    if failed:
        raise SystemExit(1)
    print("PASS: DW origin object(s) are free of FP/SIMD and new dependencies")


if __name__ == "__main__":
    main()
