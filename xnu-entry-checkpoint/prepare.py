#!/usr/bin/env python3
"""Generate the separate instrumented-entry firmware without changing stage06."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
REVIEWED = {
    'prepare.py': '8c58fa739c253ff592da21cd9715323e5da495270781d318a051eee9a662d636',
    'Handoff.c': '1315bf4cfdcbd27eba487dffff72967d58dbcab1fa40ecc4dfa9ac03c4e0e6bd',
    'Handoff.h': '2e6ac66eb23a62d69f452723536027b92768b7881d6b0a22051532bdee76d85e',
    'HandoffCore.c': '6b024ba497626c0508b9990bccca8b1bab76a6ce26d8414ba156ca5ae6628ee7',
    'HandoffCore.h': '6fca802a0f59abe75f1ab7373949799a4a32d4afdd6dd2b2b1defbc96a64044f',
    'seed_image.py': '8a4bf78df843b64b28b2b817304c5215843684b5322f1d7b43d8c49805971d05',
}


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def replace_once(text, before, after):
    if text.count(before) != 1: raise ValueError('Integration anchor changed: ' + before[:80])
    return text.replace(before, after)


def prepare(root, dtb, kernel, payload, blobs_out):
    old = HERE.parent / 'xnu-handoff-probe'
    for name, expected in REVIEWED.items():
        if hashlib.sha256((old / name).read_bytes().replace(b'\r\n', b'\n')).hexdigest() != expected:
            raise ValueError('Reviewed stage06 changed: ' + name)
    builder = module('entry_blob_builder', HERE / 'blobs.py')
    header, proof = builder.build(kernel, blobs_out)
    base = module('stage06_package', old / 'prepare.py')
    report = base.prepare(root, dtb, kernel, payload)
    app = root / 'Platforms/Xiaomi/vermeerProbePkg/Probe'
    text = (app / 'Preflight.c').read_text()
    text = replace_once(text, '#include "Handoff.h"', '#include "Handoff.h"\n#include "Entry.h"')
    text = replace_once(text, 'K70 HANDOFF DATA CHECK - NO JUMP', 'K70 INSTRUMENTED ENTRY - DATA PREFLIGHT')
    text = replace_once(text, 'No disk access; no kernel execution', 'No disk access; instrumented entry follows checks')
    anchor = '                             Payload + 128 + K70_EXPECTED_KERNEL_BYTES, K70_SEED_TRAILER_BYTES);'
    text = replace_once(text, anchor, anchor + '\n  if (!EFI_ERROR(Status))\n    Status = K70EntryCheckpoint(ImageHandle, Destination, EFI_PAGES_TO_SIZE(Pages), Plan.Span);')
    (app / 'Preflight.c').write_text(text, newline='\n')
    handoff = (app / 'Handoff.c').read_text()
    handoff = replace_once(handoff, 'HANDOFF DATA PASS - KERNEL JUMP DISABLED', 'HANDOFF DATA PASS - ENTRY CHECKS FOLLOW')
    handoff = replace_once(handoff, 'Kernel entry transition NOT EXECUTED', 'Entry transition pending validation')
    (app / 'Handoff.c').write_text(handoff, newline='\n')
    for name in ['Entry.c', 'Entry.h', 'EntryCore.c', 'EntryCore.h']:
        shutil.copy2(HERE / name, app / name)
    (app / 'EntryBlobs.h').write_text(header, newline='\n')
    inf = app / 'VermeerProbe.inf'; text = inf.read_text()
    text = replace_once(text, '  HandoffTemplates.h', '  HandoffTemplates.h\n  Entry.c\n  Entry.h\n  EntryCore.c\n  EntryCore.h\n  EntryBlobs.h')
    text = replace_once(text, '  UefiBootServicesTableLib', '  UefiBootServicesTableLib\n  DxeServicesTableLib\n  MemoryAllocationLib\n  CacheMaintenanceLib')
    text += '\n[Protocols]\n  gEfiCpuArchProtocolGuid\n'
    inf.write_text(text, newline='\n')
    report.update(mode='instrumented-kernel-entry-checkpoint', entry=proof,
                  original_cpu_init_executed=False, hardware_tested=False)
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for key in ['uefi', 'dtb', 'kernel', 'payload', 'blobs']: p.add_argument('--' + key, type=Path, required=True)
    a = p.parse_args()
    try: report = prepare(a.uefi.resolve(), a.dtb.resolve(), a.kernel.resolve(), a.payload.resolve(), a.blobs.resolve())
    except (ValueError, OSError) as error: p.exit(1, str(error) + '\n')
    print(json.dumps(report, indent=2))

