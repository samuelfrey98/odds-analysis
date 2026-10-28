from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta
from io import StringIO
import json
import os
from pathlib import Path
import random
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from odds_analysis.cli import main
from odds_analysis.replay import render_replay, replay, write_replay
from odds_analysis.simulation import generate, write_simulation

ROOT = Path(__file__).resolve().parents[1]


class SimulationTests(unittest.TestCase):
    def test_authored_scenarios_produce_known_behavior(self):
        with TemporaryDirectory() as directory:
            bundle = write_simulation(generate(), Path(directory) / "bundle")
            summary, reports = replay(bundle)
        statuses = [next(c.status for c in report.comparisons if c.player == "Alex Example")
                    for report in reports]
        self.assertEqual(statuses, ["within_threshold", "gap", "insufficient_references", "gap",
                                    "different_line", "insufficient_references", "reference_disagreement", "within_threshold"])
        self.assertTrue(summary["passed"])
        self.assertEqual(summary["comparison_checks_passed"], 24)
        self.assertEqual(summary["diagnostic_checks_passed"], 8)

    def test_seeded_prices_vary_without_changing_scenario_expectations(self):
        first, second = generate(42), generate(43)
        self.assertNotEqual(first.frames[0].quotes, second.frames[0].quotes)
        self.assertEqual([f.expected for f in first.frames], [f.expected for f in second.frames])
        self.assertEqual(generate(42), first)

    def test_multiple_seeds_preserve_the_scenario_contract(self):
        with TemporaryDirectory() as directory:
            for seed in (0, 1, 19, 2026, 2**32-1):
                with self.subTest(seed=seed):
                    bundle = write_simulation(generate(seed), Path(directory) / str(seed))
                    self.assertTrue(replay(bundle)[0]["passed"])

    def test_generator_does_not_change_global_random_state(self):
        before = random.getstate()
        generate(42)
        self.assertEqual(random.getstate(), before)

    def test_lag_and_staleness_have_real_source_timestamps(self):
        sim = generate()
        delayed = next(q for q in sim.frames[1].quotes if q.player == "Alex Example" and q.book == "Target")
        self.assertEqual(sim.frames[1].as_of-delayed.observed_at, timedelta(seconds=30))
        stale = [q for q in sim.frames[2].quotes if q.player == "Alex Example" and q.book in ("Reference B", "Reference C")]
        self.assertTrue(all(sim.frames[2].as_of-q.observed_at == timedelta(seconds=60) for q in stale))

    def test_start_is_explicit_normalized_and_not_the_current_clock(self):
        sim = generate(start="2031-02-03T07:00:00-05:00")
        self.assertEqual(sim.start.isoformat(), "2031-02-03T12:00:00+00:00")
        self.assertEqual(sim.frames[-1].as_of-sim.start, timedelta(seconds=210))

    def test_invalid_seed_or_naive_start_is_rejected(self):
        for seed in (-1, True, 1.5, 2**32):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                generate(seed)
        with self.assertRaises(ValueError):
            generate(start="2030-01-15T12:00:00")

    def test_bytes_and_replay_are_independent_of_output_location(self):
        with TemporaryDirectory() as directory:
            first = write_simulation(generate(), Path(directory) / "first")
            second = write_simulation(generate(), Path(directory) / "second")
            first_files = {str(p.relative_to(first)): p.read_bytes() for p in first.rglob('*') if p.is_file()}
            second_files = {str(p.relative_to(second)): p.read_bytes() for p in second.rglob('*') if p.is_file()}
            self.assertEqual(first_files, second_files)
            self.assertEqual(replay(first), replay(second))


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.bundle = write_simulation(generate(), Path(self.directory.name) / "bundle")
        self.manifest_path = self.bundle / "simulation.json"
        self.manifest = json.loads(self.manifest_path.read_text())

    def save_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def test_future_frame_changes_cannot_change_earlier_results(self):
        original, reports = replay(self.bundle)
        frame = self.bundle / "snapshots" / "07.csv"
        lines = frame.read_text().splitlines()
        for index, line in enumerate(lines):
            if ',Alex Example,' in line and ',Target,' in line:
                lines[index] = line.rsplit(',', 1)[0] + ',300'
        frame.write_text('\n'.join(lines)+'\n', encoding="utf-8")
        changed, new_reports = replay(self.bundle)
        self.assertEqual(original["frames"][:-1], changed["frames"][:-1])
        self.assertEqual(reports[:-1], new_reports[:-1])
        self.assertFalse(changed["passed"])
        self.assertEqual(changed["frames"][-1]["checks"][0]["actual"], "gap")

    def test_missing_target_is_not_carried_forward_from_prior_snapshot(self):
        path = self.bundle / "snapshots" / "03.csv"
        lines = [line for line in path.read_text().splitlines()
                 if not (',Alex Example,' in line and ',Target,' in line)]
        path.write_text('\n'.join(lines)+'\n', encoding="utf-8")
        summary, _ = replay(self.bundle)
        check = next(c for c in summary["frames"][3]["checks"] if c['player'] == 'Alex Example')
        self.assertIsNone(check["actual"])
        self.assertFalse(check["passed"])

    def test_unexpected_comparisons_are_failures(self):
        self.manifest["frames"][0]["expected"].pop()
        self.save_manifest()
        summary, _ = replay(self.bundle)
        extra = next(c for c in summary["frames"][0]["checks"] if c['expected'] is None)
        self.assertFalse(extra["passed"])
        self.assertFalse(summary["passed"])

    def test_diagnostic_expectations_are_checked_separately(self):
        self.manifest['frames'][2]['expected_issue_codes'] = []
        self.save_manifest()
        summary, _ = replay(self.bundle)
        self.assertEqual(summary['comparison_checks_passed'], 24)
        self.assertEqual(summary['diagnostic_checks_passed'], 7)
        self.assertFalse(summary['passed'])

    def test_source_hash_changes_when_snapshot_changes(self):
        original, _ = replay(self.bundle)
        path = self.bundle / 'snapshots' / '00.csv'
        path.write_text(path.read_text()+'\n', encoding='utf-8')
        changed, _ = replay(self.bundle)
        self.assertNotEqual(original['frames'][0]['snapshot_sha256'], changed['frames'][0]['snapshot_sha256'])
        self.assertTrue(changed['passed'])

    def test_replay_rejects_path_traversal_and_absolute_paths(self):
        for filename in ('../outside.csv', '/tmp/outside.csv'):
            with self.subTest(filename=filename):
                self.manifest['frames'][0]['csv'] = filename
                self.save_manifest()
                with self.assertRaises(ValueError):
                    replay(self.bundle)

    def test_replay_rejects_symlinks_to_outside_bundle(self):
        outside = Path(self.directory.name) / 'outside.csv'
        outside.write_text('should-not-be-read', encoding='utf-8')
        link = self.bundle / 'snapshots' / 'outside.csv'
        link.symlink_to(outside)
        self.manifest['frames'][0]['csv'] = 'snapshots/outside.csv'
        self.save_manifest()
        with self.assertRaises(ValueError):
            replay(self.bundle)

    def test_manifest_validates_versions_policy_expectations_and_time_order(self):
        mutations = [lambda m: m.update(schema_version=2), lambda m: m.update(schema_version=True),
                     lambda m: m.update(frames=[]), lambda m: m.update(policy=list(m['policy'])),
                     lambda m: m['policy'].update(max_age_seconds=float('nan')),
                     lambda m: m['frames'][0]['expected'][0].update(status='always-win'),
                     lambda m: m['frames'][1].update(as_of=m['frames'][0]['as_of']),
                     lambda m: m['frames'][0]['expected'].append(m['frames'][0]['expected'][0])]
        original = self.manifest_path.read_text()
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                manifest = json.loads(original)
                mutate(manifest)
                self.manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
                with self.assertRaises(ValueError):
                    replay(self.bundle)

    def test_duplicate_manifest_keys_are_rejected(self):
        self.manifest_path.write_text('{"schema_version":1,"schema_version":1}', encoding='utf-8')
        with self.assertRaises(ValueError):
            replay(self.bundle)

    def test_report_files_and_relative_detail_links_are_complete(self):
        summary, reports = replay(self.bundle)
        output = write_replay(summary, reports, self.bundle/'replay')
        self.assertTrue((output/'summary.json').is_file())
        self.assertEqual(len(list((output/'frames').glob('*.md'))), 8)
        self.assertIn('[Detailed market report](frames/00.md)', (output/'summary.md').read_text())
        with self.assertRaises(FileExistsError):
            write_replay(summary, reports, output)

    def test_checked_in_summary_matches_default_replay(self):
        summary, _ = replay(self.bundle)
        self.assertEqual((ROOT/'examples'/'replay-report.md').read_text(), render_replay(summary, detail_links=False))


class DemoCliTests(unittest.TestCase):
    def test_malformed_snapshot_returns_input_error_without_traceback(self):
        with TemporaryDirectory() as directory:
            bundle = write_simulation(generate(), Path(directory) / 'bundle')
            path = bundle / 'snapshots' / '00.csv'
            path.write_text(path.read_text().splitlines()[0] + '\n"unterminated', encoding='utf-8')
            with redirect_stderr(StringIO()) as stderr:
                self.assertEqual(main(['replay', str(bundle)]), 2)
            self.assertNotIn('Traceback', stderr.getvalue())
            self.assertFalse((bundle / 'replay').exists())

    def test_one_command_demo_works_without_api_credentials(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {'ODDS_API_KEY':'never-write-this'}):
            output = Path(directory)/'demo'
            stdout = StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(main(['demo','--output',str(output)]),0)
            self.assertIn('24/24 comparison checks', stdout.getvalue())
            for path in output.rglob('*'):
                if path.is_file():
                    self.assertNotIn('never-write-this',path.read_text())

    def test_generate_then_replay_commands(self):
        with TemporaryDirectory() as directory, redirect_stdout(StringIO()):
            bundle=Path(directory)/'bundle'
            output=Path(directory)/'replay'
            self.assertEqual(main(['simulate','--seed','7','--output',str(bundle)]),0)
            self.assertEqual(main(['replay',str(bundle),'--output',str(output)]),0)

    def test_cli_returns_failure_and_writes_report_for_mismatched_expectation(self):
        with TemporaryDirectory() as directory:
            bundle=write_simulation(generate(),Path(directory)/'bundle')
            path=bundle/'simulation.json'
            manifest=json.loads(path.read_text())
            manifest['frames'][0]['expected'][0]['status']='gap'
            path.write_text(json.dumps(manifest),encoding='utf-8')
            with redirect_stdout(StringIO()):
                self.assertEqual(main(['replay',str(bundle)]),1)
            self.assertIn('FAIL',(bundle/'replay'/'summary.md').read_text())

    def test_cli_input_errors_and_existing_outputs_return_two(self):
        with TemporaryDirectory() as directory:
            output=Path(directory)/'existing'
            output.mkdir()
            marker=output/'keep.txt'
            marker.write_text('keep',encoding='utf-8')
            for args in (['demo','--output',str(output)], ['demo','--seed','-1','--output',str(output)],
                         ['replay',str(output)], ['simulate','--start','no-date','--output',str(output)]):
                with self.subTest(args=args), redirect_stderr(StringIO()) as stderr:
                    self.assertEqual(main(args),2)
                    self.assertNotIn('Traceback',stderr.getvalue())
            self.assertEqual(marker.read_text(),'keep')
