#!/usr/bin/env python3
"""Generate an isolated no-jump app and a pinned kernel ramdisk."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil

from payload import make_payload, verify_payload, expected_header

HERE = Path(__file__).resolve().parent


def prepare(root, dtb, kernel, payload_path):
    if payload_path.exists():
        raise ValueError("Refusing to overwrite existing payload")
    blob, payload_report = make_payload(kernel.read_bytes())
    verify_payload(blob)
    spec = importlib.util.spec_from_file_location("k70_bounded_probe", HERE.parent / "uefi-probe/prepare.py")
    base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
    report = base.generate(root, dtb)
    package = root / "Platforms/Xiaomi/vermeerProbePkg"
    app = package / "Probe"
    for name in ["Preflight.c", "MachoCore.c", "MachoCore.h"]:
        shutil.copy2(HERE / name, app / name)
    shutil.copy2(HERE / "Preflight.inf", app / "VermeerProbe.inf")
    (app / "ExpectedPayload.h").write_text(expected_header(payload_report), encoding="utf-8", newline="\n")
    dsc = package / "vermeerProbe.dsc"
    text = dsc.read_text(encoding="utf-8")
    component = "  vermeerProbePkg/Probe/VermeerProbe.inf"
    if text.count(component) != 1:
        raise ValueError("Unexpected generated app component")
    # Global no-secureboot profile intentionally binds BaseCryptLibNull. Override
    # SHA support only for this app; do not change platform security settings.
    text = text.replace(component, component + """ {
    <LibraryClasses>
      BaseCryptLib|OpensslPkg/Library/BaseCryptLib/BaseCryptLib.inf
      OpensslLib|OpensslPkg/Library/OpensslLib/OpensslLib.inf
      IntrinsicLib|CryptoPkg/Library/IntrinsicLib/IntrinsicLib.inf
      RngLib|MdePkg/Library/BaseRngLibNull/BaseRngLibNull.inf
  }""")
    dsc.write_text(text, encoding="utf-8", newline="\n")
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path.write_bytes(blob)
    report.update({"mode": "xnu-materialize-no-jump", "payload": payload_report,
                   "payload_bytes": len(blob), "kernel_executed": False,
                   "boot_args_built": False, "adt_handoff_built": False})
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ["uefi", "dtb", "kernel", "payload"]:
        p.add_argument("--" + name, required=True, type=Path)
    a = p.parse_args()
    try:
        report = prepare(a.uefi.resolve(), a.dtb.resolve(), a.kernel.resolve(), a.payload.resolve())
    except (ValueError, OSError) as error:
        p.exit(1, str(error) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
