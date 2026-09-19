#!/usr/bin/env python3
"""Generate an evidence-based local acceptance report. No implied deploy success."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]


def check_command(name,argv,timeout=90,env=None):
    try:
        process=subprocess.run(argv,cwd=ROOT,capture_output=True,text=True,
                               timeout=timeout,env=env,check=False)
        lines=(process.stdout+'\n'+process.stderr).strip().splitlines()
        return {'status':'PASS' if process.returncode==0 else 'FAIL',
                'returncode':process.returncode,'output_tail':lines[-12:]}
    except (OSError,subprocess.TimeoutExpired) as exc:
        return {'status':'BLOCKED','reason':type(exc).__name__}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='reports/local-acceptance.json')
    args=parser.parse_args()
    tests=check_command('tests',[sys.executable,'-m','pytest','-q'],timeout=120)
    schemas=check_command('schemas',[sys.executable,'scripts/validate_contracts.py'],timeout=30)
    demo=check_command('demo',[sys.executable,'scripts/demo.py',
                               '--output','.local-runs/acceptance-demo'],timeout=45)
    ui_demo=check_command('ui_demo',[sys.executable,'-m','scripts.ui_demo'],timeout=75)
    rust=({'status':'UNVERIFIED','reason':'Cargo unavailable in this runtime'} if not shutil.which('cargo')
          else check_command('rust',['cargo','run','--manifest-path','integrations/hacp/Cargo.toml'],timeout=180))
    docker=({'status':'UNVERIFIED','reason':'Docker unavailable in this runtime'} if not shutil.which('docker')
            else check_command('docker-config',['docker','compose','-f','infra/otel/compose.yaml','config','--quiet'],
                               env={**os.environ,'QA_DOCKER_UID':str(os.getuid()),'QA_DOCKER_GID':str(os.getgid())},timeout=45))
    record={
        'generated_at':datetime.now(timezone.utc).isoformat(),
        'scope':'local universal-UI developer engine, not production acceptance',
        'checks':{'python_tests':tests,'json_schemas':schemas,'reference_demo':demo, 'universal_ui_demo':ui_demo,
                  'hacp_rust_lifecycle':rust,'docker_compose_config':docker},
        'manual_blockers':[
            'Production-grade container isolation, tenancy and security review',
            'Actual Docker Collector deployment and persistent volume permissions',
            'External HACP/Claude/Codex agent launch and protocol interoperability',
            'Complete A2A conformance and remote agents',
            'Native Chromium network verification (fixture relay is not native browser networking)',
            'Real Appium/mobile and desktop driver validation on supported hardware',
            'Third-party application pilots, realistic detection benchmark and human calibration',
            'Hosted deployment, observability SLOs, load tests and operational review',
        ],
    }
    record['local_checks_passed']=all(x['status']=='PASS' for x in (tests,schemas,demo,ui_demo))
    record['production_release_approved']=False
    path=ROOT/args.output
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({'report':str(path),'local_checks_passed':record['local_checks_passed'],
                      'production_release_approved':False,
                      'check_statuses':{k:v['status'] for k,v in record['checks'].items()}},indent=2))
    return 0 if record['local_checks_passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
