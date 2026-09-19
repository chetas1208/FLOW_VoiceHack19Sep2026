"""Run an owner-authored, data-only QA manifest from the command line."""
import argparse
import json
import os
import sys
from pathlib import Path
from services.engine.runner import execute
from services.graph.graph import Graph


def main(argv=None):
    parser=argparse.ArgumentParser(description='Execute an owner-authorized HTTP QA manifest')
    parser.add_argument('manifest',help='Path to JSON manifest')
    parser.add_argument('--output',default='.local-runs')
    parser.add_argument('--otlp-endpoint',default=os.getenv('QA_OTLP_TRACES_ENDPOINT'))
    parser.add_argument('--fail-on-verdict',action='store_true',help='Exit nonzero for application FAIL/INCONCLUSIVE')
    args=parser.parse_args(argv)
    manifest=json.loads(Path(args.manifest).read_text())
    output=Path(args.output)
    result=execute(manifest,output,args.otlp_endpoint,Graph(output/'graph.sqlite3'))
    print(json.dumps(result,indent=2))
    if result['verdict']=='INFRA_ERROR':return 2
    if args.fail_on_verdict and result['verdict']!='PASS':return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
