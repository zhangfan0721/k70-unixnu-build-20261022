#!/usr/bin/env python3
"""Run fixed isolated checkpoint groups and verify complete revision-bound evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

GROUPS={
    'lightweight':['uefi-probe','xnu-preflight','xnu-handoff-probe','xnu-entry-checkpoint','xnu-bootstrap-checkpoint','tools'],
    'memory':['xnu-mmu-checkpoint','xnu-c-entry-checkpoint','xnu-c-prologue-checkpoint'],
    'call':['xnu-first-call-checkpoint','xnu-exception-checkpoint'],
    'counter':['xnu-counter-checkpoint'],
    'irq':['xnu-timer-irq-checkpoint'],
}
BASELINE_COUNTS=dict(zip(
    ['uefi-probe','xnu-preflight','xnu-handoff-probe','xnu-entry-checkpoint','xnu-bootstrap-checkpoint','tools',
     'xnu-mmu-checkpoint','xnu-c-entry-checkpoint','xnu-c-prologue-checkpoint','xnu-first-call-checkpoint','xnu-exception-checkpoint','xnu-counter-checkpoint'],
    [12,35,13,17,10,16,26,18,24,27,20,20]))

def check_commit(commit):
    if not isinstance(commit,str) or not re.fullmatch('[0-9a-f]{40}',commit):raise ValueError('Expected exact integration commit')

def test_count(raw):
    text=raw.decode('utf-8')
    counts=re.findall(r'^Ran (\d+) tests? in [\d.]+s\s*$',text,re.M)
    if len(counts)!=1 or not text.rstrip().endswith('\nOK') or int(counts[0])<=0:
        raise ValueError('Expected one positive unittest summary without skips or failures')
    return int(counts[0])

def run_group(group,repo,evidence,commit,*,executor=subprocess.run):
    check_commit(commit)
    if group not in GROUPS:raise ValueError('Unknown fixed checkpoint group')
    repo=Path(repo).resolve();evidence=Path(evidence).resolve();evidence.mkdir(parents=True,exist_ok=True)
    if (evidence/'group-report.json').exists():raise ValueError('Refusing to overwrite a group report')
    suites=[]
    for suite in GROUPS[group]:
        path=evidence/(suite+'.log');env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',K70_QA_OUT=str(evidence/'qa'/suite))
        with path.open('w',encoding='utf-8',newline='\n') as log:
            try:
                process=executor([sys.executable,'-m','unittest','discover','-s',str(repo/suite),'-v'],cwd=repo,env=env,stdout=log,stderr=subprocess.STDOUT)
                code=process.returncode
            except OSError as error:
                log.write('Could not execute checkpoint suite: '+str(error)+'\n');code=-1
        raw=path.read_bytes();count=0;valid=False
        try:count=test_count(raw);valid=count==BASELINE_COUNTS.get(suite,count)
        except (ValueError,UnicodeError):pass
        suites.append(dict(suite=suite,log=path.name,log_sha256=hashlib.sha256(raw).hexdigest(),tests=count,
            returncode=code,passed=code==0 and valid))
    report=dict(schema=1,group=group,integration_commit=commit,passed=all(x['passed'] for x in suites),suites=suites)
    (evidence/'group-report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report

def verify_groups(root,commit):
    check_commit(commit);root=Path(root).resolve()
    expected={root/group/'group-report.json' for group in GROUPS}
    reports=set(root.rglob('group-report.json'))
    if reports!=expected:raise ValueError('Missing, duplicate or unexpected group reports')
    prior=new=0;seen=[]
    for group,names in GROUPS.items():
        folder=root/group;path=folder/'group-report.json'
        if folder.is_symlink() or path.is_symlink():raise ValueError('Linked test evidence')
        report=json.loads(path.read_text(encoding='utf-8'))
        if report.get('schema')!=1 or report.get('group')!=group or report.get('integration_commit')!=commit or report.get('passed') is not True:
            raise ValueError('Wrong revision/group or failed gate')
        items=report.get('suites',[])
        if [x.get('suite') for x in items]!=names:raise ValueError('Missing, duplicate or reordered suite coverage')
        for item in items:
            suite=item['suite'];name=suite+'.log'
            if item.get('log')!=name:raise ValueError('Unsafe or wrong log path')
            log=folder/name
            if log.is_symlink() or not log.is_file():raise ValueError('Missing or linked suite log')
            raw=log.read_bytes();count=test_count(raw)
            if item.get('passed') is not True or type(item.get('returncode')) is not int or item['returncode']!=0 or type(item.get('tests')) is not int or item['tests']!=count or item.get('log_sha256')!=hashlib.sha256(raw).hexdigest():
                raise ValueError('Suite result/count/log hash differs')
            if suite in BASELINE_COUNTS:
                if count!=BASELINE_COUNTS[suite]:raise ValueError('Prior test count changed')
                prior+=count
            else:new+=count
            seen.append(suite)
    if prior!=238 or len(seen)!=len(set(seen)) or set(seen)!=(set(BASELINE_COUNTS)|{'xnu-timer-irq-checkpoint'}):
        raise ValueError('Incomplete prior/new coverage')
    return dict(integration_commit=commit,groups=len(GROUPS),prior_tests=prior,new_tests=new,total_tests=prior+new,all_passed=True)

def main():
    cli=argparse.ArgumentParser(description=__doc__);sub=cli.add_subparsers(dest='mode',required=True)
    run=sub.add_parser('run');run.add_argument('--group',choices=GROUPS,required=True);run.add_argument('--repo',type=Path,required=True);run.add_argument('--evidence',type=Path,required=True);run.add_argument('--commit',required=True)
    verify=sub.add_parser('verify');verify.add_argument('--root',type=Path,required=True);verify.add_argument('--commit',required=True)
    args=cli.parse_args()
    try:
        if args.mode=='run':
            actual=subprocess.check_output(['git','-C',str(args.repo),'rev-parse','HEAD'],text=True).strip()
            if actual!=args.commit:raise ValueError('Checkout does not match expected integration commit')
            report=run_group(args.group,args.repo,args.evidence,args.commit)
        else:report=verify_groups(args.root,args.commit)
    except (ValueError,OSError,UnicodeError,KeyError,TypeError) as error:cli.exit(1,str(error)+'\n')
    print(json.dumps(report,indent=2))
    if args.mode=='run' and not report['passed']:raise SystemExit(1)

if __name__=='__main__':main()
