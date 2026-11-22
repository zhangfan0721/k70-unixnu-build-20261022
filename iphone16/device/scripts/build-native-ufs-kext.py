#!/usr/bin/env python3
"""Toolchain gate: build the NativeUfs driver as a real kext and report its
full offline link picture.

The driver must bind the original IOStorageFamily class instead of shipping a
private copy of IOBlockStorageDevice, so this gate proves:

  * the source compiles with the kernel tree's export headers (the iPhoneOS SDK
    ships no Kernel.framework IOKit headers),
  * the link produces a Mach-O kext bundle (filetype 11),
  * the base class stays undefined (imported) and is never defined here,
  * the C++ constructor table and the kmod entry points are landable: every
    __mod_init_func slot points inside the kext's own executable segments.

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
kit = Path(_os.environ.get("K70_VR_KIT", ""))
args = list(rec["arguments"])
out_idx = args.index("-o") + 1
args[args.index(rec["file"])] = str(src)
args[out_idx] = str(obj)
cmd = [clangxx, "-I", str(inc), *args[1:],
       "-I", str(root / ".cache/xnu-work/osfmk"), "-mgeneral-regs-only",
       "-DK70_NATIVE_UFS_FULL_BLOCK=1", "-DNATIVE_VERIFIED_BLOCK=1",
       "-I", str(src.parent), "-I", str(kit / "include")]
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

kext = out / "NativeUfs"
data = kext.read_bytes()
magic, = struct.unpack_from("<I", data)
if magic != 0xFEEDFACF:
    raise SystemExit("expected an ARM64 Mach-O kext")
filetype, = struct.unpack_from("<I", data, 12)
print(f"Mach-O filetype: {filetype} (11 == kext bundle)")

# --- Mach-O structure: segments, sections, load commands -------------------
ncmds, = struct.unpack_from("<I", data, 16)
at, segs, sects, cmds = 32, [], [], {}
for _ in range(ncmds):
    cmd_id, size = struct.unpack_from("<II", data, at)
    cmds[hex(cmd_id)] = cmds.get(hex(cmd_id), 0) + 1
    if cmd_id == 0x19:
        segname = data[at + 8:at + 24].rstrip(b"\0").decode()
        va, vsize, fo, fsize = struct.unpack_from("<QQQQ", data, at + 24)
        nsects, = struct.unpack_from("<I", data, at + 64)
        segs.append({"name": segname, "va": va, "vsize": vsize, "fileoff": fo, "filesize": fsize})
        so = at + 72
        for _ in range(nsects):
            sname = data[so:so + 16].rstrip(b"\0").decode()
            addr, sz, offs = struct.unpack_from("<QQI", data, so + 32)
            sects.append({"seg": segname, "name": sname, "addr": addr, "size": sz, "offset": offs})
            so += 80
    at += size

def section(name):
    return next((s for s in sects if s["name"] == name), None)

exec_ranges = [(s["va"], s["va"] + s["vsize"]) for s in segs
               if s["name"] in ("__TEXT", "__TEXT_EXEC") and s["vsize"]]

def in_exec(va):
    return any(lo <= va < hi for lo, hi in exec_ranges)

init_section = section("__mod_init_func")
init_entries = []
if init_section and init_section["size"]:
    n = init_section["size"] // 8
    init_entries = [struct.unpack_from("<Q", data, init_section["offset"] + i * 8)[0] for i in range(n)]
kmod_info = section("__kmod_info")

# --- symbol tables --------------------------------------------------------
undef = sp.check_output(["xcrun", "nm", "-u", str(kext)], text=True)
defined = sp.check_output(["xcrun", "nm", "-gU", str(kext)], text=True)
undef_names = {line.split()[-1] for line in undef.splitlines() if line.split()}
defined_names = {line.split()[-1] for line in defined.splitlines() if line.split()}

BASE = "__ZN20IOBlockStorageDevice"
BASE_VT = "__ZTV20IOBlockStorageDevice"
BASE_TI = "__ZTI20IOBlockStorageDevice"
imports_base = sorted(n for n in undef_names if n.startswith(BASE) or n.startswith(BASE_VT) or n.startswith(BASE_TI))
defines_base = sorted(n for n in defined_names if n.startswith(BASE) or n.startswith(BASE_VT) or n.startswith(BASE_TI))

REQUIRED_IMPORTS = [
    "__ZN20IOBlockStorageDevice10gMetaClassE",
    "__ZN20IOBlockStorageDeviceC2EPK11OSMetaClass",
    "__ZN20IOBlockStorageDeviceD2Ev",
    "__ZTV20IOBlockStorageDevice",
    "__ZN20IOBlockStorageDevice4initEP12OSDictionary",
    "__ZN20IOBlockStorageDevice13setPropertiesEP8OSObject",
    "__ZNK20IOBlockStorageDevice11getPropertyEPK8OSSymbol",
    "__ZN20IOBlockStorageDevice7doUnmapEP26IOBlockStorageDeviceExtentjj",
    "__ZN20IOBlockStorageDevice13doSetPriorityEP26IOBlockStorageDeviceExtentjh",
    "__ZN20IOBlockStorageDevice20doGetProvisionStatusEyyPjP35IOBlockStorageProvisionDeviceExtenty",
    "__ZN20IOBlockStorageDevice11requestIdleEv",
]
missing_imports = [s for s in REQUIRED_IMPORTS if s not in undef_names]

def provider(symbol):
    if symbol.startswith(BASE) or symbol.startswith(BASE_VT) or symbol.startswith(BASE_TI):
        return "com.apple.iokit.IOStorageFamily"
    if symbol.startswith("__ZN11IOMemoryDescriptor") or symbol.startswith("__ZN9IOService") \
            or symbol.startswith("__ZN8OSObject") or symbol.startswith("__ZN9OSMetaClass") \
            or symbol.startswith("__ZN7OSArray") or symbol.startswith("__ZN11OSDictionary") \
            or symbol.startswith("__ZN8OSSymbol") or symbol.startswith("__ZN7OSNumber") \
            or symbol.startswith("__ZN9OSBoolean") or symbol.startswith("__ZN8OSString") \
            or symbol.startswith("__ZN7OSData") or symbol.startswith("__ZN9IOService"):
        return "com.apple.kpi.iokit / com.apple.kpi.libkern"
    if symbol.startswith("__ZN6IOLock") or symbol.startswith("_IOLock") or symbol.startswith("_kalloc") \
            or symbol.startswith("_kfree") or symbol.startswith("_IOSleep") or symbol.startswith("_IOLog") \
            or symbol.startswith("_panic") or symbol.startswith("_clock_get_uptime") \
            or symbol.startswith("_PE_") or symbol.startswith("_ml_") or symbol.startswith("_kprintf"):
        return "com.apple.kpi.libkern / com.apple.kpi.mach"
    return "com.apple.kpi.unsupported?" 

reloc_table = [{"symbol": s, "kind": "undefined(import)", "provider": provider(s)} for s in sorted(undef_names)]

# --- raw link dumps for the evidence record ------------------------------
for tool, argv in (("nm-m.txt", ["nm", "-m"]), ("otool-l.txt", ["otool", "-l"]),
                   ("otool-rv.txt", ["otool", "-rv"])):
    with (out / tool).open("w") as fh:
        sp.run(["xcrun"] + argv + [str(kext)], stdout=fh, stderr=sp.STDOUT)

report = {
    "source": str(src),
    "link_mode": verdict,
    "macho_filetype": filetype,
    "kext_sha256": hashlib.sha256(data).hexdigest(),
    "kext_bytes": len(data),
    "load_commands": cmds,
    "segments": segs,
    "sections": sorted((s["seg"] + "," + s["name"], s["addr"], s["size"]) for s in sects),
    "imports_io_storage": imports_base,
    "required_imports_missing": missing_imports,
    "defines_io_storage": defines_base,
    "undefined_total": len(undef_names),
    "defined_total": len(defined_names),
    "mod_init_entries": [hex(v) for v in init_entries],
    "mod_init_all_inside_exec": all(in_exec(v) for v in init_entries),
    "kmod_info_section": bool(kmod_info),
    "relocations": reloc_table,
    "plea": "base class must be imported only; __mod_init_func slots must land in our own exec segments",
}
(out / "result.json").write_text(json.dumps(report, indent=2) + "\n")
evidence = _os.environ.get("GITHUB_WORKSPACE")
if evidence:
    dst = Path(evidence) / "evidence/kext"
    dst.mkdir(parents=True, exist_ok=True)
    for f in ("result.json", "nm-m.txt", "otool-l.txt", "otool-rv.txt", "NativeUfs"):
        if (out / f).is_file():
            (dst / f).write_bytes((out / f).read_bytes())
print(json.dumps({k: report[k] for k in ("link_mode", "macho_filetype", "kext_sha256",
      "undefined_total", "defined_total", "mod_init_entries", "mod_init_all_inside_exec",
      "kmod_info_section")}, indent=2))
print("imports:", len(imports_base), "defines:", len(defines_base))

failures = []
if filetype != 11:
    failures.append(f"filetype {filetype} is not a kext bundle")
if not imports_base:
    failures.append("no IOBlockStorageDevice imports; the driver is not binding the original class")
if missing_imports:
    failures.append("missing required base-class imports: " + ", ".join(missing_imports))
if defines_base:
    failures.append("the kext defines the base class instead of importing it")
if not init_entries:
    failures.append("no __mod_init_func slots; C++ meta classes would never initialise")
if not report["mod_init_all_inside_exec"]:
    failures.append("a __mod_init_func slot points outside the kext's own code")
if failures:
    print("GATE FAILED: " + "; ".join(failures))
    raise SystemExit(1)
print("GATE OK: original class imported, constructor table lands inside the kext")
