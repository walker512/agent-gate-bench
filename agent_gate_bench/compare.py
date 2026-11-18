"""Offline comparison of internally verified recorded runs; never executes adapters."""
import argparse
import os
from pathlib import Path
import sys
import tempfile
from . import core, effects

PROPOSAL_FILES = {'suite.json', 'receipt.json', 'report.json', 'review.md'}
TOTAL_LIMIT = 64 * 1024 * 1024


def snapshot(folder):
    root = Path(folder)
    if root.is_symlink() or not root.is_dir():
        raise core.Invalid('Regular bundle directory required.')
    names = {p.name for p in root.iterdir()}
    if names not in (PROPOSAL_FILES, effects.FILES):
        raise core.Invalid('Exact supported bundle file set required.')
    data = {}
    for name in sorted(names):
        limit = core.INPUT_LIMIT if name in ('suite.json', 'adapter.py') else core.OUTPUT_LIMIT
        data[name] = core.read(root / name, limit)
        if sum(map(len, data.values())) > TOTAL_LIMIT:
            raise core.Invalid('Bundle exceeds comparison snapshot limit.')
    # Verify precisely the bytes captured above, not a later reread of the source.
    with tempfile.TemporaryDirectory(prefix='agent-gate-compare-') as temporary:
        target = Path(temporary)
        for name, raw in data.items():
            write_new(target / name, raw)
        parsed = core.parse(data['suite.json'])
        if type(parsed) is not dict:
            raise core.Invalid('Suite object required.')
        schema = parsed.get('schema')
        if type(schema) is not int or schema not in (1, 2):
            raise core.Invalid('Unsupported comparison schema.')
        if schema == 2 and names == effects.FILES:
            result = effects.verify(target)
        elif schema == 1 and names == PROPOSAL_FILES:
            result = core.verify(target)
        else:
            raise core.Invalid('Bundle schema/file set mismatch.')
    return {'schema': schema, 'data': data, 'result': result,
            'receipt': core.parse(data['receipt.json'], core.OUTPUT_LIMIT)}


def write_new(path, raw):
    if len(raw) > core.OUTPUT_LIMIT:
        raise core.Invalid('Comparison output exceeds file limit.')
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)


def transition(left, right):
    if 'incomplete' in (left, right):
        return 'unresolved'
    if left == right:
        return 'unchanged'
    return 'regression' if right == 'fail' else 'improvement'


def compare(left, right):
    a, b = snapshot(left), snapshot(right)
    reasons = []
    if a['schema'] != 2 or b['schema'] != 2:
        reasons.append('missing_effects_initial_state_grants_and_environment')
    if a['data']['suite.json'] != b['data']['suite.json']:
        reasons.append('suite_bytes_differ')
    if a['schema'] == b['schema'] == 2:
        for field in ('timeout_seconds', 'max_turns', 'environment'):
            if core.canonical(a['receipt'][field]) != core.canonical(b['receipt'][field]):
                reasons.append(field + '_differs')
    ra = {x['case_id']: x for x in a['result']['results']}
    rb = {x['case_id']: x for x in b['result']['results']}
    rows = []
    for case_id in sorted(ra.keys() | rb.keys()):
        why = reasons[:]
        if case_id not in ra or case_id not in rb:
            why.append('case_missing')
        row = {'case_id': case_id, 'comparable': not why, 'reasons': why,
               'left': ra.get(case_id), 'right': rb.get(case_id), 'changes': None}
        if not why:
            x, y = ra[case_id], rb[case_id]
            row['changes'] = {
                'safety': transition(x['safety'], y['safety']),
                'utility': transition(x['utility'], y['utility']),
                'execution': transition('pass' if x['terminal'] == 'finished' else 'fail',
                                        'pass' if y['terminal'] == 'finished' else 'fail'),
                'execution_terminals_equal': x['terminal'] == y['terminal']}
        rows.append(row)
    no_regression = all(row['comparable'] and
                        row['left']['terminal'] == row['right']['terminal'] == 'finished' and
                        all(row['changes'][k] not in ('regression', 'unresolved') for k in ('safety', 'utility', 'execution'))
                        for row in rows)
    return {'schema': 'agent-gate-comparison/1', 'comparable': not reasons,
            'reasons': reasons, 'no_regression': no_regression, 'cases': rows,
            'left_files': {n: core.digest(v) for n, v in sorted(a['data'].items())},
            'right_files': {n: core.digest(v) for n, v in sorted(b['data'].items())},
            'scope': 'Recorded synthetic effects only. Internal consistency is not authenticated execution or real-agent safety. Equal failures can satisfy no-regression; this is not a safety-pass gate.'}


def build(left, right, output):
    result = compare(left, right)
    raw = core.canonical(result)
    write_new(output, raw)
    return result


def verify(left, right, output):
    result = compare(left, right)
    if core.read(output, core.OUTPUT_LIMIT) != core.canonical(result):
        raise core.Invalid('Comparison differs from verified input recomputation.')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('build', 'verify'):
        p = sub.add_parser(command)
        p.add_argument('left'); p.add_argument('right'); p.add_argument('report')
        p.add_argument('--require-no-regression', action='store_true')
    args = parser.parse_args()
    try:
        result = (build if args.command == 'build' else verify)(args.left, args.right, args.report)
        print(core.canonical(result).decode(), end='')
        return 3 if args.require_no_regression and not result['no_regression'] else 0
    except (core.Invalid, OSError, ValueError, TypeError, AttributeError):
        print('Invalid or inaccessible comparison evidence.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
