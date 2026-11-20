#!/usr/bin/env python3
"""Generate a bounded virtual timer interrupt over the pinned stage15 package."""
import argparse
import importlib.util
import json
from pathlib import Path
import tempfile

HERE=Path(__file__).resolve().parent

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result

def change(text,before,after):
    if text.count(before)!=1:raise ValueError('Reviewed anchor changed: '+before[:80])
    return text.replace(before,after)

def prepare(root,dtb,kernel,payload,blobs_out):
    builder=module('timer_irq_builder',HERE/'blobs.py');builder.reviewed_sources()
    previous=module('timer_irq_previous',HERE.parent/'xnu-counter-checkpoint/prepare.py')
    with tempfile.TemporaryDirectory(prefix='stage15-generator-') as tmp:
        report=previous.prepare(root,dtb,kernel,payload,Path(tmp)/'blobs')
    header,proof=builder.build(kernel,blobs_out)
    app=root/'Platforms/Xiaomi/vermeerProbePkg/Probe';text=(app/'Entry.c').read_text()
    for before,after in [
        ('K70 STAGE15 COUNTER PROGRESSION CHECKPOINT','K70 STAGE16 VIRTUAL TIMER IRQ CHECKPOINT'),
        ('Three ordered samples; stop before deeper C init','One IRQ27; same-PC ERET; stop before deeper C init'),
        ('8 colors + 23=1: physical + virtual counts; no timer programming','IRQ27 + same-PC ERET; 23=1 only after configuration restored'),
        ('CNTFRQ is firmware metadata; no absolute calibration or IRQ','31 GP restored; 27 stable GP checked after return; no scheduler'),
        ('05 ESR,06 ELR,07 rawFAR,08 SP,09 LR,0A SPSel','05 IAR,06 IRQ-ELR,07 IRQ-SPSR,08 SP0,09 LR,0A IRQ-count'),
        ('0B/0C freq pre/post;0D/0E/0F physical samples,10 delta','0B freq,0C start,0D compare,0E IRQ-count,0F returned-count'),
        (r'11/12/13 virtual samples,14 delta;15/16 loop4096/8192\n17 samples3,18 rawSPSR on exception,19 TCR\n1A TTBR0,1B TTBR1,1C MAIR,1D flags,1E headerbase\n1F x0,20 FP,21 frame1,22 timerWrites0,23 verified1',
         r'10/11 timerCTL IRQ/disabled,12 EOI,13 EOI-mode,14 returned1\n15/16/17 SP1 pre/IRQ/post,18 GP-mask,19 polls\n1A GICR,1B/1C/1D GICD pre/armed/restored\n1E/1F/20 CPU-group pre/armed/restored,21 restored1,22 frame1,23 verified1')]:
        text=change(text,before,after)
    (app/'Entry.c').write_text(text,newline='\n');(app/'EntryBlobs.h').write_text(header,newline='\n')
    text=(app/'Preflight.c').read_text()
    text=change(text,'K70 STAGE15 COUNTER - PREFLIGHT','K70 STAGE16 TIMER IRQ - PREFLIGHT')
    (app/'Preflight.c').write_text(text,newline='\n')
    report.update(mode='virtual-timer-irq-checkpoint',entry=proof,counter_read_only=False,
        controlled_brk_probe=False,expected_exception_capture=False,expected_irq=True,
        eret_or_resume_executed=True,hardware_tested=False)
    report['display']=dict(console_row_pixels=36,spacer_lines=40,context_start_row=1440,record_start_row=704,
        record_last_row=1384,record_words=36,columns=2,record_schema='virtual-timer-irq-v1',console_cursor_explicitly_reset=True)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['uefi','dtb','kernel','payload','blobs']:p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args()
    try:r=prepare(a.uefi.resolve(),a.dtb.resolve(),a.kernel.resolve(),a.payload.resolve(),a.blobs.resolve())
    except (ValueError,OSError) as e:p.exit(1,str(e)+'\n')
    print(json.dumps(r,indent=2))
