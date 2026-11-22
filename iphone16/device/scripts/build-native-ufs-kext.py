#!/usr/bin/env python3
"""Toolchain gate: build the NativeUfs driver as a real kext.

The driver must bind the original IOStorageFamily class instead of shipping a
private copy of IOBlockStorageDevice, so this gate proves three things before
any prelink work starts:

  * the source compiles against the SDK's own IOKit storage headers,
  * the link produces a Mach-O kext bundle (filetype 11),
  * IOBlockStorageDevice stays undefined (imported), never defined here.
"""
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

sdk = sp.check_output(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"], text=True).strip()
kernel_fw = Path(sdk) / "System/Library/Frameworks/Kernel.framework"
vendored = Path(__file__).resolve().parent.parent / "drivers/IOStorageFamily"
storage_headers = kernel_fw / "Headers"
if not (storage_headers / "IOKit/storage/IOBlockStorageDevice.h").is_file():
    if not vendored.is_dir():
        raise SystemExit(f"no IOStorageFamily headers under {storage_headers} or {vendored}")
    storage_headers = vendored
print(f"storage headers: {storage_headers}")

out = root / "build/native-ufs-kext"
out.mkdir(parents=True, exist_ok=True)

clangxx = sp.check_output(["xcrun", "--sdk", "iphoneos", "--find", "clang++"], text=True).strip()
obj = out / "NativeUfs.o"
compile_cmd = [
    clangxx, "-target", "arm64-apple-ios16.0", "-isysroot", sdk,
    "-mkernel", "-fapple-kext", "-fno-exceptions", "-fno-rtti", "-fno-threadsafe-statics",
    "-std=gnu++17", "-O2", "-g", "-c",
    "-DKERNEL=1", "-DKERNEL_PRIVATE=1", "-DNDEBUG=1",
    "-I" + str(storage_headers), "-I" + str(inc),
    "-I" + str(root / ".cache/xnu-work/osfmk"), "-I" + str(src.parent),
    "-I" + str(kernel_fw / "PrivateHeaders"),
    str(src), "-o", str(obj),
]
(out / "compile-command.json").write_text(json.dumps(compile_cmd, indent=2) + "\n")
with (out / "compile.log").open("w") as log:
    rc = sp.run(compile_cmd, stdout=log, stderr=sp.STDOUT).returncode
if rc:
    print((out / "compile.log").read_text(errors="replace"))
    raise SystemExit("kext source did not compile against the SDK headers")

link_base = [
    "xcrun", "ld", "-arch", "arm64", "-platform_version", "ios", "16.0", "16.0",
    "-o", str(out / "NativeUfs"), str(obj), "-undefined", "dynamic_lookup",
]
attempts = {"-kext": link_base + ["-kext"], "-bundle": ["xcrun", "ld"] + link_base[2:] + ["-bundle"]}
verdict = None
for name, cmd in attempts.items():
    with (out / ("link" + name + ".log")).open("w") as log:
        rc = sp.run(cmd, stdout=log, stderr=sp.STDOUT).returncode
    if rc == 0:
        verdict = name
        break
    print((out / ("link" + name + ".log")).read_text(errors="replace")[-2000:])
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
    "storage_headers": str(storage_headers),
    "link_mode": verdict,
    "macho_filetype": filetype,
    "kext_sha256": __import__("hashlib").sha256(data).hexdigest(),
    "imports_io_storage": imported_storage,
    "defines_io_storage": defined_storage,
    "defines_own_class": sorted(n for n in defined_names if "NativeUfs" in n),
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
