"""Install the diagnostic patch into the pinned source-device recipe only."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from prepare import HERE, kernel_patch, replace_once

DEVICE_REF = 'd4dbb3683023a17bb468b9774f52c87f3060e739'
PREPARER_SHA = 'cddb4858c243ef317cc6c6f141c775e8615b6808b85dce6c487389976a2798ac'
HOOK = '''    # Source-only diagnostic backend; no full-monitor/root prerequisites change.
    bundle = Path(__file__).resolve().parent / "k70-formal-diag"
    manifest = __import__('json').loads((bundle / "manifest.json").read_text())
    patch = bundle / "zzzz-k70-formal-diag.patch"
    if hashlib.sha256(patch.read_bytes()).hexdigest() != manifest['patch_sha256']:
        raise ValueError('Diagnostic patch identity mismatch')
    shutil.copy2(patch, local / patch.name)
    script = tree / "scripts/build-xnu-4k-baseline.sh"
    text = script.read_text()
    original = upstream / "scripts/build-xnu-4k-baseline.sh"
    if script.is_symlink() or script.read_bytes() != original.read_bytes():
        raise ValueError('Expected original build-tree script copy')
    anchor = 'for LATE_PATCH in "$ROOT/patches/xnu/zzz-boot-progress.patch"'
    if text.count(anchor) != 1:
        raise ValueError('Late patch reversal anchor changed')
    script.write_text(text.replace(anchor,
        'for LATE_PATCH in "$ROOT/patches/xnu/zzzz-k70-formal-diag.patch" "$ROOT/patches/xnu/zzz-boot-progress.patch"'))
'''


def install(device, uefi):
    actual = subprocess.check_output(['git','-C',str(device),'rev-parse','HEAD'],text=True).strip()
    if actual != DEVICE_REF:
        raise ValueError('Unexpected source-device revision')
    preparer=device/'tools/prepare_kernel_patches.py'
    data=preparer.read_bytes()
    if hashlib.sha256(data).hexdigest() != PREPARER_SHA:
        raise ValueError('Pinned preparer has changed')
    target=device/'tools/k70-formal-diag'
    if target.exists():
        raise ValueError('Refusing to overwrite a diagnostic installation')
    font=uefi/'Silicon/Silicium/SiliciumPkg/Library/FrameBufferSerialPortLib/Font.h'
    if hashlib.sha256(font.read_bytes()).hexdigest() != 'd2a3687db67b069f4e34a961e17fd28b0242986e3fa8dd8a7545cab70834fa8e':
        raise ValueError('Unexpected pinned font')
    patch=kernel_patch(font.read_text())
    # Inherit the already reviewed DT panic-region fix, without the USB backend.
    fixed=HERE.parent/'xnu-debug/bundle/device-files'
    changes=json.loads((HERE.parent/'xnu-debug/bundle/device-fixes.json').read_text())
    for name, hashes in changes['files'].items():
        if hashlib.sha256((device/name).read_bytes()).hexdigest() != hashes['before_sha256']:
            raise ValueError('Unexpected source-device input: '+name)
        if hashlib.sha256((fixed/name).read_bytes()).hexdigest() != hashes['after_sha256']:
            raise ValueError('Unexpected preserved fix: '+name)
    modified=replace_once(data.decode(),'    (local / PATCH).write_bytes(patched)\n',
        '    (local / PATCH).write_bytes(patched)\n'+HOOK)
    target.mkdir()
    (target/'zzzz-k70-formal-diag.patch').write_text(patch)
    manifest={'source_device':actual,'patch_sha256':hashlib.sha256(patch.encode()).hexdigest(),
              'observer_source':'peter8889/UniXNU-ishtar@89a54c0132b180212a4e8bf2fddf04c78347a2dd',
              'scope':'source-only boot observer; no root, crypto, storage or GIC implementation changes',
              'hardware_tested':False}
    (target/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    preparer.write_text(modified)
    for name in changes['files']:
        shutil.copy2(fixed/name,device/name)
    return manifest


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device',type=Path,required=True)
    parser.add_argument('--uefi',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(install(args.device.resolve(),args.uefi.resolve()),indent=2))
