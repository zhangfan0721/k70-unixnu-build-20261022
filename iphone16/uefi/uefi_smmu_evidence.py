"""Install bounded, read-only SEC evidence into a generated firmware BUILD COPY.

Pinned yyx2025/uefi-vermeer da38b23cc7b3b3716cf7c72c42866bd73c978dd3.
Does not build, boot, flash, probe a device, or change the existing cleanup.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
LIBRARY = 'Silicon/Qualcomm/QcomPkg/Library/ArmSmmuDetachLib/ArmSmmuDetachLib.c'
LIBRARY_INF = 'Silicon/Qualcomm/QcomPkg/Library/ArmSmmuDetachLib/ArmSmmuDetachLib.inf'
SEC = 'Silicon/Silicium/SiliciumPkg/Sec/Sec.c'
PLATFORM = 'Silicon/Qualcomm/KailuaPkg/Library/PlatformSecLib/PlatformSec.c'
SMMU_IO = 'Silicon/Qualcomm/QcomPkg/Library/ArmSmmuDetachLib/SmmuIo.c'
FORMAL_DSC = 'Platforms/Xiaomi/vermeerFormalPkg/vermeerFormal.dsc'
INPUTS = {
    LIBRARY: '430e6b079f6702e0a66f1f080b371af9efc941ba939ce168bacac6b3c07a16cf',
    LIBRARY_INF: 'd3179c3f9dcc9b6e40e0c8df541f5584dcb59a48cd5d1e504a48a5ad5909795b',
    SEC: '98fc2f2ef462774bca5435bf2e9a9e12a69857ef04582d9290f733d95afb7df1',
    PLATFORM: '3c728c48c4b53b195c7c1bef8f87718880e0aaa18b32d6cff94a4cab1de7cb51',
    SMMU_IO: 'a3fb9c73013a3e02a9ec1187b4af350a70f55c24bb0d62115f5b5243c97fd5f9',
}

BEGIN = '/* K70 UEFI SMMU evidence BEGIN */\n'
END = '/* K70 UEFI SMMU evidence END */\n'
CALL = '  ArmSmmuDetachAll (SkipStreams, SkipStreamCount);'
BEFORE = '  UefiSmmuEvidenceBefore (SmmuRegion.Address, SmmuRegion.Length);\n'
AFTER = '\n  UefiSmmuEvidenceAfter (SmmuRegion.Address, SmmuRegion.Length);'

# Existing DEBUG/SerialPort rendering only. Capture never logs; SEC emits the
# saved pair after SerialPortInitialize AND PrintFirmwareVersion (which clears
# the framebuffer). No console calls or delays alter the cleanup interval.
GLUE = r'''
#include <Library/IoLib.h>
#include <Library/DebugLib.h>
#include "UefiSmmuEvidence.h"

STATIC UEFI_SMMU_SNAPSHOT mUefiSmmuSnapshots[2];
STATIC UINT64 mUefiSmmuPairId;
STATIC UINT64 mUefiSmmuSequence;
STATIC BOOLEAN mUefiSmmuPrinted;

STATIC UINT32
UefiSmmuEvidenceRead32 (VOID *Context, UINTN Address)
{
  (VOID)Context;
  return MmioRead32 (Address);
}

STATIC VOID
UefiSmmuEvidenceBefore (UINT64 Base, UINT64 Bytes)
{
  mUefiSmmuPairId = GetPerformanceCounter ();
  ++mUefiSmmuSequence;
  mUefiSmmuPrinted = FALSE;
  UefiSmmuCapture (&mUefiSmmuSnapshots[0], Base, Bytes,
    mUefiSmmuPairId, mUefiSmmuPairId, UefiSmmuEvidenceRead32, NULL);
}

STATIC VOID
UefiSmmuEvidenceAfter (UINT64 Base, UINT64 Bytes)
{
  UefiSmmuCapture (&mUefiSmmuSnapshots[1], Base, Bytes,
    mUefiSmmuPairId, GetPerformanceCounter (), UefiSmmuEvidenceRead32, NULL);
}

STATIC VOID
UefiSmmuEvidencePrintSnapshot (CONST CHAR8 *Phase, CONST UEFI_SMMU_SNAPSHOT *Snapshot)
{
  STATIC CONST CHAR8 *CONST BankNames[UEFI_SMMU_BANK_WORDS] = {
    "SCTLR", "TTBR0L", "TTBR0H", "TTBR1L", "TTBR1H", "TCR", "FSR", "CBAR", "CBA2R"
  };
  UINT32 i;

  DEBUG ((EFI_D_WARN, "UEFI %a build=@BUILD_TAG@\n", Phase));
  DEBUG ((EFI_D_WARN, "UEFI %a pair=%016lx\n", Phase, Snapshot->PairId));
  DEBUG ((EFI_D_WARN, "UEFI %a sequence=%016lx\n", Phase, mUefiSmmuSequence));
  DEBUG ((EFI_D_WARN, "UEFI %a counter=%016lx\n", Phase, Snapshot->Counter));
  DEBUG ((EFI_D_WARN, "UEFI %a status=%016lx\n", Phase, (UINT64)Snapshot->Status));
  DEBUG ((EFI_D_WARN, "UEFI %a base=%016lx\n", Phase, Snapshot->Base));
  DEBUG ((EFI_D_WARN, "UEFI %a resource=%016lx\n", Phase, Snapshot->ResourceBytes));
  DEBUG ((EFI_D_WARN, "UEFI %a window=%016lx\n", Phase, Snapshot->WindowBytes));
  for (i = 0; i < 3; ++i) {
    DEBUG ((EFI_D_WARN, "UEFI %a ID%u=%016lx\n", Phase, i, (UINT64)Snapshot->Id[i]));
  }
  if (Snapshot->Status != UefiSmmuCaptured) {
    // Status 2: invalid resource, no reads. Status 3: unknown IDs, ID reads
    // only. This refusal concerns evidence; original cleanup still ran.
    return;
  }
  DEBUG ((EFI_D_WARN, "UEFI %a CR0=%016lx\n", Phase, (UINT64)Snapshot->Cr0));
  for (i = 0; i < UEFI_SMMU_BANK_WORDS; ++i) {
    DEBUG ((EFI_D_WARN, "UEFI %a %a@%016lx=%016lx\n", Phase,
      BankNames[i], (UINT64)UefiSmmuBankOffsets[i], (UINT64)Snapshot->Bank69[i]));
  }
  for (i = 0; i < Snapshot->RouteCount; ++i) {
    CONST UEFI_SMMU_ROUTE *Route = &Snapshot->Routes[i];
    DEBUG ((EFI_D_WARN, "UEFI %a slot=%016lx\n", Phase, (UINT64)Route->Slot));
    DEBUG ((EFI_D_WARN, "UEFI %a SMR=%016lx S2CR=%016lx\n", Phase,
      (UINT64)Route->Smr, (UINT64)Route->S2cr));
  }
  DEBUG ((EFI_D_WARN, "UEFI %a valid=%016lx\n", Phase, (UINT64)Snapshot->RouteCount));
  DEBUG ((EFI_D_WARN, "UEFI %a SID60=%016lx\n", Phase, (UINT64)Snapshot->Sid60Matches));
  DEBUG ((EFI_D_WARN, "UEFI %a bank69refs=%016lx\n", Phase, (UINT64)Snapshot->Bank69References));
}

// Exported to the SEC module, which already links ArmSmmuDetachLib through
// Kailua PlatformSecLib. The call is after serial init and framebuffer clear.
VOID
ArmSmmuEvidencePrint (VOID)
{
  if (mUefiSmmuPrinted) {
    return;
  }
  mUefiSmmuPrinted = TRUE;
  UefiSmmuEvidencePrintSnapshot ("PRE", &mUefiSmmuSnapshots[0]);
  UefiSmmuEvidencePrintSnapshot ("POST", &mUefiSmmuSnapshots[1]);
}
'''


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Unexpected pinned UEFI anchor: '+before[:90])
    return text.replace(before, after, 1)


def remove_library_instrumentation(text):
    """Restore entire pinned source, including every original cleanup byte."""
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise ValueError('Missing unique UEFI evidence block')
    start = text.index(BEGIN)
    finish = text.index(END, start)+len(END)
    text = text[:start]+text[finish:]
    return replace_once(text, BEFORE+CALL+AFTER, CALL)


def install(root, build_tag='k70-smmu-evidence-v1'):
    root = Path(root).resolve()
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,64}', build_tag):
        raise ValueError('UEFI build tag must be 1..64 plain ASCII identifier characters')
    if not (root/FORMAL_DSC).is_file():
        raise ValueError('Refusing source tree: generate vermeerFormalPkg in a BUILD COPY first')
    sources = {}
    for relative, expected in INPUTS.items():
        text = (root/relative).read_text(encoding='utf-8')
        if digest(text) != expected:
            raise ValueError('Pinned UEFI source mismatch: '+relative)
        sources[relative] = text
    header = root/Path(LIBRARY).parent/'UefiSmmuEvidence.h'
    if header.exists():
        raise ValueError('Refusing to overwrite installed UEFI evidence header')

    original = sources[LIBRARY]
    library = replace_once(original, '#include "SmmuV2.h"\n',
        '#include "SmmuV2.h"\n'+BEGIN+GLUE.replace('@BUILD_TAG@', build_tag)+END)
    library = replace_once(library, CALL, BEFORE+CALL+AFTER)
    restored = remove_library_instrumentation(library)
    if restored != original:
        raise ValueError('UEFI original cleanup changed')
    sec = replace_once(sources[SEC], '#include "Sec.h"\n',
        '#include "Sec.h"\n\n// Deferred output from the existing Kailua SEC cleanup library.\n'
        'extern VOID ArmSmmuEvidencePrint (VOID);\n')
    sec = replace_once(sec, '  PrintFirmwareVersion ();\n',
        '  PrintFirmwareVersion ();\n\n'
        '  // Both snapshots are retained; serial is ready and framebuffer clear is complete.\n'
        '  ArmSmmuEvidencePrint ();\n')
    inf = replace_once(sources[LIBRARY_INF], '[LibraryClasses]\n', '[LibraryClasses]\n  DebugLib\n')
    # All hashes and all anchors are checked before the first mutation.
    for relative, text in ((LIBRARY, library), (LIBRARY_INF, inf), (SEC, sec)):
        (root/relative).write_text(text, encoding='utf-8', newline='\n')
    header.write_bytes((HERE/'UefiSmmuEvidence.h').read_bytes())
    return {
        'schema': 'k70-uefi-smmu-evidence-v1',
        'build_tag': build_tag,
        'source_revision': 'da38b23cc7b3b3716cf7c72c42866bd73c978dd3',
        'cleanup_original_sha256': digest(original),
        'cleanup_restored_sha256': digest(restored),
        'input_sha256': INPUTS.copy(),
        'output_sha256': {relative:digest(text) for relative, text in
                          ((LIBRARY, library), (LIBRARY_INF, inf), (SEC, sec))},
        'header_sha256': hashlib.sha256(header.read_bytes()).hexdigest(),
        'capture': 'immediately before/after existing ArmSmmuDetachAll; fixed RAM pair',
        'emission': 'existing DEBUG after SerialPortInitialize and PrintFirmwareVersion',
        'resource_base': '0x15000000',
        'capture_window_bytes': '0xd0000',
        'expected_ids': ['0x4c017e69', '0x60000046', '0x00005111'],
        'unknown_layout': 'evidence declined after three ID reads; original cleanup unchanged',
        'debug_build_required': True,
        'hardware_tested': False,
        'smmu_writes_added': False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--build-tag', default='k70-smmu-evidence-v1')
    args = parser.parse_args()
    print(json.dumps(install(args.root, args.build_tag), indent=2))


if __name__ == '__main__':
    main()
