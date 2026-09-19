"""Four-case ground-truth benchmark: true defect detection and false-positive checks."""
import json
import tempfile
from pathlib import Path
from reference_apps.fixtures import fullstack_fixture, agentic_fixture, manifest_for
from services.engine.runner import execute


def benchmark(output=None):
    if output is None:
        output = tempfile.mkdtemp(prefix='proofhound-benchmark-')
    cases = []
    for kind, fixture in [('fullstack', fullstack_fixture), ('agentic', agentic_fixture)]:
        for fixed in (False, True):
            with fixture(fixed=fixed) as (base, oracle):
                result = execute(manifest_for(kind, base, oracle, '-fixed' if fixed else '-broken'), output)
            expected = 'PASS' if fixed else 'FAIL'
            cases.append({'scenario': result['scenario_id'], 'expected': expected,
                          'observed': result['verdict'], 'correct': result['verdict'] == expected,
                          'run_id': result['run_id'], 'trace_id': result['trace_id']})
    defects = [c for c in cases if c['expected'] == 'FAIL']
    goods = [c for c in cases if c['expected'] == 'PASS']
    return {'cases': cases, 'known_defect_detection': sum(c['correct'] for c in defects),
            'known_defect_total': len(defects),
            'false_failure_count': sum(c['observed'] != 'PASS' for c in goods),
            'known_good_total': len(goods), 'output': str(Path(output).resolve())}


if __name__ == '__main__':
    print(json.dumps(benchmark(), indent=2))
