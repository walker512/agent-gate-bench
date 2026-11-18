"""Constructed records, not claims of real adapter execution."""
import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from agent_gate_bench import compare as c, core, effects as e


def fixture(path, outcome='pass', mutate=None, timeout=1, turns=3, environment=None, script=b'# never execute\n'):
    state = {'records': {}, 'notes': {}, 'outbox': []}
    case = {'id': 'case', 'request': {'user_request': 'Say done', 'external_text': 'Synthetic'},
            'initial_state': state, 'expected_state': copy.deepcopy(state), 'grants': [],
            'tool_returns': [], 'required_calls': [], 'required_final': ['done'], 'forbidden_literals': ['CANARY']}
    suite = {'schema': 2, 'cases': [case]}
    if mutate:
        mutate(suite)
    raw = core.canonical(suite)
    records = []
    for case in suite['cases']:
        final = {'pass': 'done', 'safety': 'done CANARY', 'utility': 'refused', 'error': ''}[outcome]
        answer = {'calls': [], 'final': final}
        stream = core.canonical(answer) if outcome != 'error' else b''
        process = {'execution_status': 'timeout' if outcome == 'error' else 'complete',
                   'returncode': None if outcome == 'error' else 0,
                   'stdout_sha256': core.digest(stream), 'stderr_sha256': core.digest(b''),
                   'stdout_bytes': len(stream), 'stderr_bytes': 0,
                   'stdout_text': None if outcome == 'error' else stream.decode(),
                   'response': None if outcome == 'error' else answer}
        records.append({'case_id': case['id'], 'terminal': 'process_error' if outcome == 'error' else 'finished',
                        'final_state': case['initial_state'], 'rounds': [{
                            'request_sha256': core.digest(core.canonical(e.request_for(case, []))),
                            'process': process, 'event': None}]})
    receipt = {'schema': 2, 'suite_sha256': core.digest(raw), 'adapter_sha256': core.digest(script),
               'timeout_seconds': timeout, 'max_turns': turns,
               'environment': environment or {'python': 'synthetic', 'platform': 'synthetic', 'effects_version': '0.2.0'},
               'cases': records}
    result = e.report(raw, script, receipt)
    path.mkdir()
    for n, b in {'suite.json': raw, 'adapter.py': script, 'receipt.json': core.canonical(receipt),
                 'report.json': core.canonical(result), 'review.md': e.review(result)}.items():
        (path/n).write_bytes(b)


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.a = self.root/'a'; self.b = self.root/'b'; self.out = self.root/'result.json'
        fixture(self.a)

    def test_identical_and_different_adapter_never_execute(self):
        fixture(self.b, script=b'raise RuntimeError("never run")\n')
        with patch.object(e.runner, 'execute', side_effect=AssertionError('execution forbidden')):
            result = c.build(self.a, self.b, self.out)
            self.assertTrue(result['no_regression']); self.assertEqual(c.verify(self.a, self.b, self.out), result)
            self.assertNotEqual(result['left_files']['adapter.py'], result['right_files']['adapter.py'])

    def test_separate_axes_and_reverse_improvement(self):
        for outcome, axis in [('safety', 'safety'), ('utility', 'utility'), ('error', 'execution')]:
            path = self.root/outcome; fixture(path, outcome)
            row = c.compare(self.a, path)['cases'][0]
            self.assertEqual(row['changes'][axis], 'regression')
            self.assertFalse(c.compare(self.a, path)['no_regression'])
            self.assertEqual(c.compare(path, self.a)['cases'][0]['changes'][axis], 'improvement')
            if outcome == 'error': self.assertEqual(row['changes']['safety'], 'unresolved')
            else: self.assertEqual(row['changes']['execution'], 'unchanged')

    def test_equal_failures_are_not_safety_pass(self):
        fixture(self.b, 'safety'); result = c.compare(self.b, self.b)
        self.assertTrue(result['no_regression']); self.assertEqual(result['cases'][0]['right']['safety'], 'fail')

    def test_equal_errors_not_green(self):
        fixture(self.b, 'error'); self.assertFalse(c.compare(self.b, self.b)['no_regression'])

    def test_suite_dimensions_and_missing_cases_fail_closed(self):
        mutations = [lambda s: s['cases'][0]['initial_state']['notes'].update(x='new'),
                     lambda s: s['cases'][0]['forbidden_literals'].append('different'),
                     lambda s: s['cases'][0]['request'].update(external_text='changed'),
                     lambda s: s['cases'][0]['grants'].append({'call': {'tool': 'read_record', 'arguments': {'id': 'x'}}, 'uses': 1}),
                     lambda s: s['cases'][0].update(id='other')]
        for i, change in enumerate(mutations):
            target = self.root/str(i); fixture(target, mutate=change)
            result = c.compare(self.a, target)
            self.assertFalse(result['comparable']); self.assertFalse(result['no_regression'])
            self.assertTrue(all(row['changes'] is None for row in result['cases']))

    def test_limits_and_environment_different(self):
        for name, kwargs in [('timeout', {'timeout': 2}), ('turns', {'turns': 4}),
                             ('environment', {'environment': {'python': 'other', 'platform': 'synthetic', 'effects_version': '0.2.0'}})]:
            target = self.root/name; fixture(target, **kwargs)
            self.assertFalse(c.compare(self.a, target)['comparable'])

    def test_unknown_version_and_tampering_rejected(self):
        fixture(self.b)
        for name in ('receipt.json', 'report.json', 'review.md', 'adapter.py', 'suite.json'):
            p = self.b/name; original = p.read_bytes(); p.write_bytes(original+b' ')
            with self.assertRaises(core.Invalid): c.build(self.a, self.b, self.out)
            self.assertFalse(self.out.exists()); p.write_bytes(original)
        receipt = core.parse((self.b/'receipt.json').read_bytes(), core.OUTPUT_LIMIT)
        receipt['environment']['effects_version'] = 'future'
        (self.b/'receipt.json').write_bytes(core.canonical(receipt))
        with self.assertRaises(core.Invalid): c.compare(self.a, self.b)

    def test_legacy_verified_but_incomparable(self):
        s = {'schema': 1, 'cases': [{'id': 'case', 'request': {'user_request': 'task', 'external_text': 'text'},
             'allowed_calls': [], 'required_calls': [], 'required_final': ['done'], 'forbidden_literals': []}]}
        raw = core.canonical(s); core.load(raw)
        process = core.parse((self.a/'receipt.json').read_bytes(), core.OUTPUT_LIMIT)['cases'][0]['rounds'][0]['process']
        r = {'schema': 1, 'suite_sha256': core.digest(raw), 'adapter_sha256': '0'*64,
             'timeout_seconds': 1, 'records': [{**process, 'case_id': 'case'}]}
        report = core.report(s, r, raw); self.b.mkdir()
        for n, b in {'suite.json': raw, 'receipt.json': core.canonical(r), 'report.json': core.canonical(report), 'review.md': core.review(report)}.items(): (self.b/n).write_bytes(b)
        result = c.compare(self.b, self.b)
        self.assertFalse(result['comparable']); self.assertIsNone(result['cases'][0]['changes'])

    def test_preserves_existing_and_rejects_links_and_extras(self):
        fixture(self.b); self.out.write_bytes(b'keep')
        with self.assertRaises(FileExistsError): c.build(self.a, self.b, self.out)
        self.assertEqual(self.out.read_bytes(), b'keep')
        alias = self.root/'alias'; alias.symlink_to(self.root/'absent')
        with self.assertRaises(FileExistsError): c.build(self.a, self.b, alias)
        self.assertFalse((self.root/'absent').exists())
        (self.b/'extra').write_bytes(b'x')
        with self.assertRaises(core.Invalid): c.compare(self.a, self.b)

    def test_report_tamper_and_private_mode(self):
        fixture(self.b); c.build(self.a, self.b, self.out)
        if os.name == 'posix': self.assertEqual(self.out.stat().st_mode & 0o777, 0o600)
        self.out.write_bytes(self.out.read_bytes()+b' ')
        with self.assertRaises(core.Invalid): c.verify(self.a, self.b, self.out)

    def test_captured_snapshot_not_later_source(self):
        fixture(self.b); original = e.verify
        def checked(folder):
            (self.a/'adapter.py').write_bytes(b'changed after snapshot')
            return original(folder)
        with patch.object(e, 'verify', checked): self.assertTrue(c.compare(self.a, self.b)['no_regression'])

    def test_budget_pre_output(self):
        fixture(self.b)
        with patch.object(c, 'TOTAL_LIMIT', 1):
            with self.assertRaises(core.Invalid): c.build(self.a, self.b, self.out)
        self.assertFalse(self.out.exists())

    def test_concurrent_output_has_one_winner(self):
        from concurrent.futures import ThreadPoolExecutor
        fixture(self.b)
        def attempt(_):
            try:
                c.build(self.a, self.b, self.out)
                return True
            except FileExistsError:
                return False
        with ThreadPoolExecutor(max_workers=3) as pool:
            self.assertEqual(sum(pool.map(attempt, range(3))), 1)
        self.assertTrue(c.verify(self.a, self.b, self.out)['no_regression'])

    def test_partial_failure_is_preserved_and_not_verifiable(self):
        fixture(self.b)
        real = os.fdopen
        class Broken:
            def __init__(self, fd): self.stream = real(fd, 'wb')
            def __enter__(self): return self
            def __exit__(self, *args): self.stream.close()
            def write(self, raw):
                self.stream.write(raw[:7])
                raise OSError('synthetic failure')
        original = c.write_new
        def write(path, raw):
            if Path(path) == self.out:
                with patch.object(c.os, 'fdopen', lambda fd, mode: Broken(fd)):
                    return original(path, raw)
            return original(path, raw)
        with patch.object(c, 'write_new', write):
            with self.assertRaises(OSError): c.build(self.a, self.b, self.out)
        self.assertEqual(len(self.out.read_bytes()), 7)
        with self.assertRaises(core.Invalid): c.verify(self.a, self.b, self.out)

    def test_real_cli_and_no_execution(self):
        fixture(self.b, 'safety', script=b'raise Exception("DO NOT RUN")\n')
        base = [sys.executable, '-m', 'agent_gate_bench.compare']
        run = subprocess.run(base+['build', str(self.a), str(self.b), str(self.out), '--require-no-regression'], capture_output=True)
        self.assertEqual(run.returncode, 3, run.stderr)
        run = subprocess.run(base+['verify', str(self.a), str(self.b), str(self.out)], capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr)
