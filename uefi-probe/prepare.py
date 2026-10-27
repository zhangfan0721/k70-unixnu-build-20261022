#!/usr/bin/env python3
"""Generate an isolated, storage-free probe package from a pinned K70 port.

Adapted from mansar1337/UniXNU-vermeer tools/prepare_uefi_probe.py,
revision d4dbb3683023a17bb468b9774f52c87f3060e739.
SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

INPUTS = {
    "Platforms/Xiaomi/vermeerPkg/vermeer.dsc": "526a0ec3932fc3267541019b4923ae3a983c38b3dbd3f64c1faa097eeb6ba4a3",
    "Platforms/Xiaomi/vermeerPkg/vermeer.fdf": "94836fa533d968a09a17ff68e8e5cb8d8603f04e0d9c7a1524e0ee7ff4839aef",
    "Platforms/Xiaomi/vermeerPkg/DeviceBuild.py": "2e9df2d0d0cb5922c7a20c4958944b72ac4b0b580852589454cdc8356eac8ee0",
    "Platforms/Xiaomi/vermeerPkg/Include/DXE.inc": "e9c41e0f37cf2059a256bf0d884d40b97f9a0d82676a55724b8449554ee82156",
    "Platforms/Xiaomi/vermeerPkg/Include/APRIORI.inc": "690356033943627e27f2e9247594f040887109af7351b5c55892191ee423ec7e",
    "Resources/Configs/vermeer.toml": "dd50cbf859b5529fa2ca3420e257b701e50c8c624b5aad8446bd4b443026f5eb",
}
DTB_SHA = "fcd9bd27b37fd0f46b887be6f6e4e4b84f2b00a13c9152e46e076b532711d5c6"
REMOVE = (
    "UniXNUPkg/", "DarwinBootPkg/", "UniXNULib|", "VermeerChineseUi",
    'os.path.join(os.environ.get("UNIXNU_ROOT"',
    "DiskIoDxe.inf", "PartitionDxe.inf", "Fat.inf", "EnglishDxe.inf",
    "UFSDxe.inf", "SdccDxe.inf", "UsbMassStorageDxe.inf",
)


def generate(root, dtb):
    source = root / "Platforms/Xiaomi/vermeerPkg"
    destination = root / "Platforms/Xiaomi/vermeerProbePkg"
    config = root / "Resources/Configs/vermeerProbe.toml"
    tree = root / "Resources/DTBs/vermeerProbe.dtb"
    for target in [destination, config, tree]:
        if target.exists():
            raise ValueError(f"Refusing to overwrite existing output: {target}")
    for relative, expected in INPUTS.items():
        content = (root / relative).read_bytes().replace(b"\r\n", b"\n")
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError(f"Source hash mismatch: {relative}")
    blob = dtb.read_bytes()
    if hashlib.sha256(blob).hexdigest() != DTB_SHA:
        raise ValueError("Source hash mismatch: K70 DTB")

    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__"))
    for file in destination.rglob("*"):
        if file.suffix.lower() not in (".dsc", ".fdf", ".inf", ".dec", ".py", ".inc"):
            continue
        text = file.read_text().replace("vermeerPkg", "vermeerProbePkg")
        text = "\n".join(line for line in text.splitlines() if not any(item in line for item in REMOVE)) + "\n"
        if file.name == "DeviceBuild.py":
            text = text.replace("vermeerProbePkg/vermeer.dsc", "vermeerProbePkg/vermeerProbe.dsc")
            text = text.replace('"PRODUCT_NAME", "vermeer"', '"PRODUCT_NAME", "vermeerProbe"')
        if file.name == "vermeer.dsc":
            text = re.sub(r"(PLATFORM_NAME\s*=\s*)Vermeer\b", r"\1VermeerProbe", text)
            text = text.replace("vermeerProbePkg/vermeer.fdf", "vermeerProbePkg/vermeerProbe.fdf")
            text = re.sub(r"(VERMEER_VENDOR_HW\s*=\s*)1\b", r"\g<1>0", text)
            text = re.sub(r"(VERMEER_CHINESE_UI\s*=\s*)1\b", r"\g<1>0", text)
            text += "\n[LibraryClasses]\n  PlatformBootOptionsLib|vermeerProbePkg/Probe/ProbeBootOptions.inf\n\n[Components]\n  vermeerProbePkg/Probe/VermeerProbe.inf\n"
        if file.name == "vermeer.fdf":
            text = text.replace("  !include Include/RAW.inc", "  INF vermeerProbePkg/Probe/VermeerProbe.inf")
        file.write_text(text, newline="\n")
    (destination / "vermeer.dsc").rename(destination / "vermeerProbe.dsc")
    (destination / "vermeer.fdf").rename(destination / "vermeerProbe.fdf")
    probe = destination / "Probe"
    probe.mkdir()
    here = Path(__file__).resolve().parent
    for name in ["VermeerProbe.c", "VermeerProbe.inf"]:
        shutil.copy2(here / name, probe / name)
    (probe / "ProbeBootOptions.inf").write_text("""[Defines]
  INF_VERSION = 0x00010005
  BASE_NAME = ProbeBootOptions
  FILE_GUID = F4368684-A7B4-470B-B208-9C90EFD35B35
  MODULE_TYPE = DXE_DRIVER
  LIBRARY_CLASS = PlatformBootOptionsLib|DXE_DRIVER
[Sources]
  ProbeBootOptions.c
[Packages]
  MdePkg/MdePkg.dec
  SiliciumPkg/SiliciumPkg.dec
[LibraryClasses]
  MemoryAllocationLib
""", newline="\n")
    (probe / "ProbeBootOptions.c").write_text("""#include <Uefi.h>
#include <Library/MemoryAllocationLib.h>
#include <Library/PlatformBootOptionsLib.h>
STATIC EFI_GUID mProbeGuid = {0x4E746B99, 0x462F, 0x4C10, {0x8A,0x77,0xC3,0xF8,0x3E,0x5D,0x4F,0x72}};
VOID GetPlatformBootOptions (EFI_PLATFORM_BOOT_OPTION **Options, UINT8 *Count) {
  *Options = AllocateZeroPool (sizeof (**Options));
  *Count = 0;
  if (*Options == NULL) { return; }
  (*Options)[0].AppName = L"Vermeer hardware probe";
  (*Options)[0].AppGuid = &mProbeGuid;
  (*Options)[0].LoadAttribute = LOAD_OPTION_ACTIVE;
  *Count = 1;
}
""", newline="\n")
    config.parent.mkdir(parents=True, exist_ok=True)
    tree.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / "Resources/Configs/vermeer.toml", config)
    tree.write_bytes(blob)
    return {"package": "vermeerProbePkg", "input_hashes": INPUTS, "input_dtb_sha256": DTB_SHA,
            "vendor_hw": False, "storage_modules": False, "os_loader": False,
            "hardware_tested": False, "ram_scope": "firmware-exposed map; not total installed RAM"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uefi", required=True, type=Path)
    parser.add_argument("--dtb", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = generate(args.uefi.resolve(), args.dtb.resolve())
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
