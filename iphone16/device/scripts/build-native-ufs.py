#!/usr/bin/env python3
"""Build the Darwin22 NativeUfs diagnostic archive from the live C++ recipe."""
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess as sp
import sys
import tempfile

if len(sys.argv) != 3:
    raise SystemExit("usage: build-native-ufs.py SOURCE.cpp STORAGE_INCLUDE")

root = Path.cwd()
src = Path(sys.argv[1]).resolve(strict=True)
inc = (root / sys.argv[2]).resolve()

# Stage the public IOStorageFamily headers when the tree has not produced them yet.
if not (inc / "IOKit/storage/IOBlockStorageDevice.h").is_file():
    refer = Path(__file__).resolve().parent.parent / "drivers/IOStorageFamily"
    if not refer.is_dir():
        raise SystemExit(f"missing IOStorageFamily source under {refer}")
    (inc / "IOKit/storage").mkdir(parents=True, exist_ok=True)
    for header in refer.glob("*.h"):
        shutil.copyfile(header, inc / "IOKit/storage" / header.name)
    sdk = sp.check_output(["xcrun", "--sdk", "macosx", "--show-sdk-path"], text=True).strip()
    shutil.copyfile(Path(sdk) / "usr/include/TargetConditionals.h", inc / "TargetConditionals.h")

recipe = root / (
    "build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/"
    "iokit/DEVELOPMENT/IOPlatformExpert.cpo.json"
)
if not recipe.is_file():
    raise SystemExit(f"missing {recipe}; run the C++ bootstrap in a fresh output tree")
rec = json.loads(recipe.read_text().strip().removesuffix(","))
cwd = Path(rec["directory"]).resolve(strict=True)
if cwd != recipe.parent.resolve():
    raise SystemExit(f"stale compile recipe: {cwd}")

args = list(rec["arguments"])
required = {"-xc++", "-c", "-mkernel", "-fapple-kext", "-mios-version-min=16.0"}
if not required.issubset(args) or not any(
    re.fullmatch(r"--target=arm64-apple-ios16(?:\.0){0,2}", a) for a in args
):
    raise SystemExit("expected the ARM64 iOS 16 kernel C++ recipe")
if args.count(rec["file"]) != 1 or args.count("-o") != 1:
    raise SystemExit("unexpected source/output arguments in compile recipe")

out_idx = args.index("-o") + 1
if args[out_idx] != rec["output"]:
    raise SystemExit("compile recipe output does not match its record")
for a in args[1:]:
    if a.startswith(("@", "-M", "-serialize-diagnostics", "--serialize-diagnostics")):
        raise SystemExit(f"review new compiler side-output argument: {a}")

clangxx = sp.check_output(["xcrun", "--sdk", "iphoneos", "--find", "clang++"], text=True).strip()
if Path(clangxx).parent.resolve() != Path(args[0]).parent.resolve():
    raise SystemExit("xcrun and the recipe point to different Xcode toolchains")

out = root / "build/native-ufs"
out.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(dir=out) as tmp:
    obj = Path(tmp) / "NativeUfs.o"
    archive = Path(tmp) / "libNativeUfs.a"
    args[args.index(rec["file"])] = str(src)
    args[out_idx] = str(obj)
    # Diagnostic mode: build the full block-device class so the kernel link
    # can report exactly which IOStorageFamily symbols are still unresolved.
    import os as _os
    _full = True  # one diagnostic round: full block class, list unresolved symbols
    cmd = [clangxx, "-I", str(inc), *args[1:],
           "-I", str(root / ".cache/xnu-work/osfmk"), "-mgeneral-regs-only"]
    if not _full:
        cmd.append("-DK70_NATIVE_UFS_PROBE_ONLY=1")
    (out / "compile-command.json").write_text(json.dumps(cmd, indent=2) + "\n")
    with (out / "compile.log").open("w") as log:
        result = sp.run(cmd, cwd=cwd, stdout=log, stderr=sp.STDOUT)
    if result.returncode:
        print((out / "compile.log").read_text(errors="replace"), end="")
        raise SystemExit(result.returncode)
    data = obj.read_bytes()
    if struct.unpack_from("<4I", data) != (0xFEEDFACF, 0x0100000C, 0, 1):
        raise SystemExit("expected an ARM64 Mach-O relocatable object")
    off, deployment = 32, None
    for _ in range(struct.unpack_from("<I", data, 16)[0]):
        kind, size = struct.unpack_from("<II", data, off)
        if size < 8 or off + size > len(data):
            raise SystemExit("malformed Mach-O load command")
        if kind == 0x32:
            deployment = struct.unpack_from("<II", data, off + 8)
        off += size
    if deployment != (2, 0x100000):
        raise SystemExit(f"expected iOS 16.0 deployment, got {deployment}")
    sp.run(["xcrun", "ar", "rcs", str(archive), str(obj)], check=True)
    nm = sp.check_output(["xcrun", "nm", "-gU", str(archive)], text=True)
    symbols = {line.split()[-1] for line in nm.splitlines() if line.split()}
    expected = {"__ZN9NativeUfs5startEP9IOService", "_native_ufs_probe_calls"}
    if missing := expected - symbols:
        raise SystemExit(f"archive missing defined symbols: {sorted(missing)}")
    if _full:
        undef = sp.check_output(["xcrun", "nm", "-u", str(obj)], text=True)
        (out / "undefined-symbols.txt").write_text(undef)
    obj.replace(out / obj.name)
    archive.replace(out / archive.name)

print(out / "libNativeUfs.a")
