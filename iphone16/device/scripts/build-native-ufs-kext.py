#!/usr/bin/env python3
"""Toolchain gate: build the NativeUfs driver as a real kext.

The driver must bind the original IOStorageFamily class instead of shipping a
private copy of IOBlockStorageDevice, so this gate proves three things before
any prelink work starts:

  * the source compiles with the kernel tree's export headers (the iPhoneOS SDK
    ships no Kernel.framework IOKit headers, so the tree's recipe is the only
    way to see IOKit/IOService.h),
  * the link produces a Mach-O kext bundle (filetype 11),
  * IOBlockStorageDevice stays undefined (imported), never defined here.

StorageBridge.cpp is deliberately NOT compiled: its job today is to define the
base class inside the kernel, which is exactly what this gate forbids.
"""
import hashlib
import json
import os as _os
from pathlib import Path
import struct
import subprocess as sp
import sys

if len(sys.argv) != 3:
    raise SystemExit("usage: build-native-ufs-kext.py SOURCE.cpp STORAGE_INCLUDE")

root = Path.cwd()
src = Path(sys.argv[1]).resolve(strict=True)
inc = (root / sys.argv[2]).resolve()

recipe = root / (
    "build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/"
    "iokit/DEVELOPMENT/IOPlatformExpert.cpo.json"
)
if not recipe.is_file():
    raise SystemExit(f"missing {recipe}; run the kernel bootstrap first")
rec = json.loads(recipe.read_text().strip().removesuffix(","))
cwd = Path(rec["directory"]).resolve(strict=True)
if cwd != recipe.parent.resolve():
    raise SystemExit("stale compile recipe")

out = root / "build/native-ufs-kext"
out.mkdir(parents=True, exist_ok=True)
obj = out / "NativeUfs.o"

clangxx = sp.check_output(["xcrun", "--sdk", "iphoneos", "--find", "clang++"], text=True).strip()
args = list(rec["arguments"])
out_idx = args.index("-o") + 1
args[args.index(rec["file"])] = str(src)
args[out_idx] = str(obj)
kit = Path(_os.environ.get("K70_VR_KIT", ""))
kit_include = kit / "include"
cmd = [clangxx, "-I", str(inc), *args[1:],
       "-I", str(root / ".cache/xnu-work/osfmk"), "-mgeneral-regs-only",
       "-DK70_NATIVE_UFS_FULL_BLOCK=1", "-DNATIVE_VERIFIED_BLOCK=1",
       "-I", str(src.parent), "-I", str(kit_include)]
(out / "compile-command.json").write_text(json.dumps(cmd, indent=2) + "\n")
with (out / "compile.log").open("w") as log:
    rc = sp.run(cmd, cwd=cwd, stdout=log, stderr=sp.STDOUT).returncode
if rc:
    print((out / "compile.log").read_text(errors="replace")[-4000:])
    raise SystemExit("kext source did not compile with the kernel export headers")

link_modes = {
    "-kext": ["xcrun", "ld", "-arch", "arm64", "-platform_version", "ios", "16.0", "16.0",
              "-o", str(out / "NativeUfs"), str(obj), "-undefined", "dynamic_lookup", "-kext"],
    "-bundle": ["xcrun", "ld", "-arch", "arm64", "-platform_version", "ios", "16.0", "16.0",
                "-o", str(out / "NativeUfs"), str(obj), "-undefined", "dynamic_lookup", "-bundle"],
}
verdict = None
for name, link_cmd in link_modes.items():
    with (out / ("link" + name + ".log")).open("w") as log:
        rc = sp.run(link_cmd, stdout=log, stderr=sp.STDOUT).returncode
    if rc == 0:
        verdict = name
        break
    print((out / ("link" + name + ".log")).read_text(errors="replace")[-2500:])
if verdict is None:
    raise SystemExit("kext link failed with every linker mode")
print(f"link mode accepted: {verdict}")

data = (out / "NativeUfs").read_bytes()
magic, = struct.unpack_from("<I", data)
if magic != 0xFEEDFACF:
    raise SystemExit("expected an ARM64 Mach-O kext")
filetype, = struct.unpack_from("<I", data, 12)
print(f"Mach-O filetype: {filetype} (11 == kext bundle)")

undef = sp.check_output(["xcrun", "nm", "-u", str(out / "NativeUfs")], text=True)
defined = sp.check_output(["xcrun", "nm", "-gU", str(out / "NativeUfs")], text=True)
undef_names = {line.split()[-1] for line in undef.splitlines() if line.split()}
defined_names = {line.split()[-1] for line in defined.splitlines() if line.split()}
imported_storage = sorted(n for n in undef_names if "IOBlockStorageDevice" in n or "IOStorage" in n or "IOMedia" in n)
defined_storage = sorted(n for n in defined_names if "IOBlockStorageDevice" in n or "IOStorage" in n or "IOMedia" in n)

report = {
    "source": str(src),
    "storage_headers": str(inc),
    "link_mode": verdict,
    "macho_filetype": filetype,
    "kext_sha256": hashlib.sha256(data).hexdigest(),
    "imports_io_storage": imported_storage,
    "defines_io_storage": defined_storage,
    "defines_own_class": sorted(n for n in defined_names if "NativeUfs" in n),
    "import_count": len(undef_names),
    "plea": "IOBlockStorageDevice must appear in imports and never in defines",
}
(out / "result.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))

failures = []
if filetype != 11:
    failures.append(f"filetype {filetype} is not a kext bundle")
if not imported_storage:
    failures.append("no IOStorageFamily imports; the driver is not binding the original class")
if defined_storage:
    failures.append("the kext defines IOStorage names instead of importing them")
if failures:
    print("GATE FAILED: " + "; ".join(failures))
    raise SystemExit(1)
print("GATE OK: kext imports the original IOStorageFamily classes")
