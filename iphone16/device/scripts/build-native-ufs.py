#!/usr/bin/env python3
"""Build the Darwin22 NativeUfs diagnostic archive from the live C++ recipe."""
import hashlib
import json
import os as _os
from pathlib import Path
import re
import shutil
import struct
import subprocess as sp
import sys
import tempfile

# Switches in the kernel C++ recipe that a C translation unit cannot accept.
CXX_ONLY_SWITCHES = ("-std=gnu++", "-std=c++", "-stdlib=", "-fno-exceptions",
                     "-fno-rtti", "-fno-threadsafe-statics",
                     "-fno-c++-static-destructors", "-fno-objc-arc")

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

# VerifiedRoot kit inside the pinned core checkout.
_kit_root = Path(_os.environ.get("K70_VR_KIT", ""))
kit_include = _kit_root / "include"
kit_src = _kit_root / "src"
kit_adapters = _kit_root / "adapters"

with tempfile.TemporaryDirectory(dir=out) as tmp:
    obj = Path(tmp) / "NativeUfs.o"
    bridge_obj = Path(tmp) / "StorageBridge.o"
    archive = Path(tmp) / "libNativeUfs.a"
    args[args.index(rec["file"])] = str(src)
    args[out_idx] = str(obj)
    # Diagnostic mode: build the full block-device class so the kernel link
    # can report exactly which IOStorageFamily symbols are still unresolved.
    _full = True  # one diagnostic round: full block class, list unresolved symbols

    # VerifiedRoot inputs are validated BEFORE any object is produced: a missing
    # or mis-hashed envelope must fail loudly instead of silently linking a
    # driver that never calls the verifier.
    manifest_os = Path(_os.environ.get("K70_VR_OS_MANIFEST", ""))
    manifest_sys = Path(_os.environ.get("K70_VR_SYS_MANIFEST", ""))
    key_blob = Path(_os.environ.get("K70_VR_KEY_BLOB", ""))
    verified_enabled = _full and all(
        p.is_file() for p in (manifest_os, manifest_sys, key_blob))
    if _full and not verified_enabled:
        raise SystemExit(
            "VerifiedRoot requested but inputs are missing: "
            f"os={manifest_os} sys={manifest_sys} key={key_blob}")
    if verified_enabled:
        for p, want in (
                (manifest_os, _os.environ.get("K70_VR_OS_SHA256", "")),
                (manifest_sys, _os.environ.get("K70_VR_SYS_SHA256", "")),
                (key_blob, _os.environ.get("K70_VR_KEY_SHA256", ""))):
            if not want:
                raise SystemExit(f"missing expected SHA-256 for {p.name}")
            got = hashlib.sha256(p.read_bytes()).hexdigest()
            if got != want:
                raise SystemExit(f"SHA-256 mismatch for {p.name}: {got} != {want}")

    cmd = [clangxx, "-I", str(inc), *args[1:],
           "-I", str(root / ".cache/xnu-work/osfmk"), "-mgeneral-regs-only"]
    if verified_enabled:
        cmd.append("-DNATIVE_VERIFIED_BLOCK=1")
        cmd += ["-I", str(kit_include), "-I", str(src.parent)]
    if _full:
        cmd.append("-DK70_NATIVE_UFS_FULL_BLOCK=1")
    else:
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
    # Bridge translation unit: same recipe, different source/output.
    bridge_src = src.parent / "StorageBridge.cpp"
    if bridge_src.is_file():
        bridge_cmd = list(cmd)
        bridge_cmd[bridge_cmd.index(str(src))] = str(bridge_src)
        bridge_cmd[bridge_cmd.index(str(obj))] = str(bridge_obj)
        with (out / "compile-bridge.log").open("w") as log:
            r2 = sp.run(bridge_cmd, cwd=cwd, stdout=log, stderr=sp.STDOUT)
        if r2.returncode:
            print((out / "compile-bridge.log").read_text(errors="replace"), end="")
            raise SystemExit(r2.returncode)
    # VerifiedRoot: link the two owner-signed envelopes plus the policy table.
    verified_objs = []
    if verified_enabled:
        gen_src = src.parent / "VerifiedPolicy.cpp"
        gen_obj = Path(tmp) / "VerifiedPolicy.o"
        text = gen_src.read_text()
        text = text.replace("VR_OS_MANIFEST", str(manifest_os))
        text = text.replace("VR_SYS_MANIFEST", str(manifest_sys))
        text = text.replace("VR_KEY_BLOB", str(key_blob))
        staged = Path(tmp) / "VerifiedPolicy_gen.cpp"
        staged.write_text(text)
        gen_cmd = list(cmd)
        gen_cmd[gen_cmd.index(str(src))] = str(staged)
        gen_cmd[gen_cmd.index(str(obj))] = str(gen_obj)
        gen_cmd += ["-I", str(src.parent), "-I", str(kit_include)]
        with (out / "compile-policy.log").open("w") as log:
            r3 = sp.run(gen_cmd, cwd=cwd, stdout=log, stderr=sp.STDOUT)
        if r3.returncode:
            print((out / "compile-policy.log").read_text(errors="replace"), end="")
            raise SystemExit(r3.returncode)
        verified_objs.append(str(gen_obj))
        # verifier + xnu crypto adapter
        for name in ("verified_root.c", "xnu_crypto.c"):
            source_path = kit_src / name if name == "verified_root.c" else kit_adapters / name
            if not source_path.is_file():
                raise SystemExit(f"VerifiedRoot kit source missing: {source_path}")
            vobj = Path(tmp) / (name.replace(".c", ".o"))
            vcmd = list(cmd)
            vcmd[vcmd.index(str(src))] = str(source_path)
            vcmd[vcmd.index(str(obj))] = str(vobj)
            vcmd += ["-I", str(kit_include)]
            # The kit verifier is plain C, so the C++ recipe has to drop every
            # C++-only switch (clang rejects -std=gnu++1z for C outright) and
            # name the C dialect explicitly.
            vcmd = [a for a in vcmd
                    if a != "-xc++" and not a.startswith(CXX_ONLY_SWITCHES)]
            vcmd.insert(1, "-xc")
            vcmd.insert(2, "-std=gnu11")
            with (out / ("compile-" + name + ".log")).open("w") as log:
                rv = sp.run(vcmd, cwd=cwd, stdout=log, stderr=sp.STDOUT)
            if rv.returncode:
                print((out / ("compile-" + name + ".log")).read_text(errors="replace"), end="")
                raise SystemExit(rv.returncode)
            verified_objs.append(str(vobj))
    objs = [str(obj)] + ([str(bridge_obj)] if bridge_obj.is_file() else []) + verified_objs
    sp.run(["xcrun", "ar", "rcs", str(archive), *objs], check=True)
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
