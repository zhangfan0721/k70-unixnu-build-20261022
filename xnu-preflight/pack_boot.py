#!/usr/bin/env python3
"""Pack pinned UEFI + a checked, no-jump kernel envelope in boot v0."""
import argparse
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import zlib

from payload import verify_payload

PAGE = 4096
RAMDISK_ADDRESS = 0xAA000000


def verify_image(data, combined, tree, payload):
    if len(data) < PAGE or data[:8] != b"ANDROID!":
        raise ValueError("Not a complete Android boot image")
    ks, ka, rs, ra, ss, _, tags, page, version, _ = struct.unpack_from("<10I", data, 8)
    if (ka, ra, ss, tags, page, version) != (0x8000, RAMDISK_ADDRESS, 0, 0x1E00000, PAGE, 0):
        raise ValueError("Unexpected boot header or load addresses")
    if not ks or ks > len(data) - PAGE or rs != len(payload) or not rs:
        raise ValueError("Invalid kernel/ramdisk sizes")
    ram_at = PAGE * (1 + (ks + PAGE - 1) // PAGE)
    end = ram_at + rs
    file_end = ((end + PAGE - 1) // PAGE) * PAGE
    if end > len(data) or file_end != len(data):
        raise ValueError("Truncated or extended boot image")
    if any(data[PAGE + ks:ram_at]) or any(data[end:file_end]):
        raise ValueError("Nonzero boot section padding")
    kernel = data[PAGE:PAGE + ks]
    try:
        decoder = zlib.decompressobj(31)
        unpacked = decoder.decompress(kernel, len(combined) + 1)
    except zlib.error as error:
        raise ValueError("Invalid firmware gzip stream") from error
    if not decoder.eof or decoder.unconsumed_tail or unpacked != combined or decoder.unused_data != tree:
        raise ValueError("Firmware/shim/DTB bytes differ from the verified input")
    if data[ram_at:end] != payload:
        raise ValueError("Ramdisk differs from the verified envelope")
    return {"header_version": version, "page_size": page, "kernel_bytes": ks,
            "kernel_address": hex(ka), "tags_address": hex(tags),
            "kernel_sha256": hashlib.sha256(kernel).hexdigest(),
            "ramdisk_bytes": rs, "ramdisk_address": hex(ra),
            "ramdisk_sha256": hashlib.sha256(payload).hexdigest()}


def pack(fd_path, uefi, dtb_path, payload_path, out):
    payload = payload_path.read_bytes()
    payload_report = verify_payload(payload)
    spec = importlib.util.spec_from_file_location("pinned_vermeer_pack", uefi / "tools/vermeer-zh/pack_boot.py")
    original = importlib.util.module_from_spec(spec); spec.loader.exec_module(original)
    fd = fd_path.read_bytes()
    if len(fd) != 0x300000:
        raise ValueError("Unexpected firmware FD size")
    original.verify_dtb(dtb_path)
    tree = dtb_path.read_bytes()
    with tempfile.TemporaryDirectory(prefix="k70-preflight-pack-") as folder:
        scratch = Path(folder)
        shim = original.compile_shim(uefi, scratch, "clang", "llvm-objcopy", "llvm-nm")
        combined = shim + fd
        kernel = gzip.compress(combined, mtime=0) + tree
        kernel_file = scratch / "Image.gz-dtb"; kernel_file.write_bytes(kernel)
        ramdisk_file = scratch / "ramdisk"; ramdisk_file.write_bytes(payload)
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, str(uefi / "Resources/Scripts/mkbootimg.py"),
                        "--kernel", str(kernel_file), "--ramdisk", str(ramdisk_file),
                        "--base", "0", "--kernel_offset", "0x8000",
                        "--ramdisk_offset", hex(RAMDISK_ADDRESS), "--tags_offset", "0x1e00000",
                        "--pagesize", str(PAGE), "--header_version", "0", "-o", str(out)], check=True)
        image = out.read_bytes()
        report = verify_image(image, combined, tree, payload)
    report.update({"fd_sha256": hashlib.sha256(fd).hexdigest(), "dtb_sha256": hashlib.sha256(tree).hexdigest(),
                   "shim_bytes": len(shim), "fd_base": "0xa7100000", "fd_size": "0x300000",
                   "image_bytes": len(image), "image_sha256": hashlib.sha256(image).hexdigest(),
                   "payload": payload_report, "kernel_executed": False, "hardware_tested": False})
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ["fd", "uefi", "dtb", "payload", "out", "report"]:
        p.add_argument("--" + name, required=True, type=Path)
    a = p.parse_args()
    report = pack(a.fd.resolve(), a.uefi.resolve(), a.dtb.resolve(), a.payload.resolve(), a.out.resolve())
    a.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
