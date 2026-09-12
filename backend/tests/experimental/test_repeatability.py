"""Synthetic observer fixtures verify diagnostics, never numerical approval."""
import copy
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from backend.app.experimental.contract import DEFAULT, MODEL, canonical, digest, validate_input
from backend.app.experimental.repeatability import capture_failure, difference, observe
from backend.app.experimental.replay import read_record


def result(inputs=None):
    inputs = validate_input(inputs or DEFAULT)
    record = {"format":"opentcad-solver-result", "schemaVersion":1, "model":MODEL,
              "input":inputs, "inputSha256":digest(inputs), "productApproved":False,
              "templateSha256":"a"*64, "solverVersion":"fixture",
              "environment":{"os":"synthetic-fixture"},
              "iv":[[0.,0.],[.4,1e-8]], "xUm":[0.,2.], "potentialV":[0.,.6],
              "equilibriumPotentialV":[0.,.6], "electronsCm3":[1e4,1e16],
              "holesCm3":[1e16,1e4], "netDopingCm3":[-1e16,1e16]}
    return seal(record)


def seal(record):
    record.pop('resultSha256', None); record['resultSha256'] = digest(record)
    return record


class DifferenceTests(unittest.TestCase):
    def test_exact_small_difference_and_out_of_tolerance_are_distinct(self):
        before = result()
        self.assertTrue(difference(before, copy.deepcopy(before))['canonicalEqual'])
        after = copy.deepcopy(before); after['potentialV'][1] += 1e-12; seal(after)
        report = difference(before, after)
        self.assertFalse(report['canonicalEqual'])
        self.assertTrue(report['replay']['numericallyReproduced'])
        self.assertGreater(report['fields']['potentialV']['maxAbsoluteDifference'], 0)
        after['potentialV'][1] += .01; seal(after)
        self.assertFalse(difference(before, after)['replay']['numericallyReproduced'])

    def test_signed_zero_encoding_and_provenance_are_not_hidden(self):
        before = result(); after = copy.deepcopy(before)
        after['iv'][0][1] = -0.; seal(after)
        report = difference(before, after)
        self.assertFalse(report['canonicalEqual'])
        self.assertEqual(report['fields']['iv']['changedLeaves'], 1)
        self.assertEqual(report['fields']['iv']['maxAbsoluteDifference'], 0)
        after['templateSha256'] = 'b'*64; seal(after)
        self.assertTrue(difference(before, after)['replay']['comparisonRejected'])

    def test_lossless_unique_failure_pairs_and_integrity(self):
        before = result(); after = copy.deepcopy(before); after['iv'][1][1] *= 2; seal(after)
        with tempfile.TemporaryDirectory() as temp:
            first = capture_failure(before, after, temp); second = capture_failure(before, after, temp)
            self.assertNotEqual(first, second)
            self.assertEqual((first/'before.json').read_bytes(), canonical(before))
            self.assertEqual(read_record(first/'after.json'), after)
            self.assertTrue((first/'comparison.json').exists())


class ObserverTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_schedule_and_stability_do_not_grant_approval(self):
        seen = []
        async def runner(inputs): seen.append(inputs['intervals']); return result(inputs)
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)/'new'
            report = await observe(directory, cycles=2, runner=runner)
            self.assertEqual(seen, [100,200,400,200]*2)
            self.assertEqual(report['status'], 'observed-stable')
            self.assertEqual(len(report['records']), 8)
            self.assertFalse(report['releaseApproved'])
            self.assertFalse(report['historicalIssueCleared'])
            fingerprint = report.pop('reportSha256'); self.assertEqual(fingerprint, digest(report))
            with self.assertRaises(FileExistsError): await observe(directory, runner=runner)

    async def test_numeric_drift_source_drift_and_incomplete_run_are_preserved(self):
        index = 0
        async def runner(inputs):
            nonlocal index
            record = result(inputs)
            if index == 3: record['iv'][1][1] *= 2
            index += 1
            return seal(record)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = await observe(root/'drift', 1, runner)
            self.assertEqual(report['status'], 'differences-observed')
            self.assertFalse(report['numericallyReproducedWithinEachInput'])
            async def stable(inputs): return result(inputs)
            with patch('backend.app.experimental.repeatability.source_hashes', side_effect=[{'file':'before'},{'file':'after'}]):
                report = await observe(root/'source-drift', 1, stable)
            self.assertFalse(report['sourceStable'])
            self.assertEqual(report['status'], 'differences-observed')
            async def fail(_): raise RuntimeError('private runtime error')
            with self.assertRaises(RuntimeError): await observe(root/'incomplete', 1, fail)
            self.assertTrue((root/'incomplete/failure.json').exists())
            self.assertNotIn('private', (root/'incomplete/failure.json').read_text())

    async def test_invalid_options_do_not_create_output(self):
        with tempfile.TemporaryDirectory() as temp:
            for cycles in (0,51,True):
                with self.assertRaises(ValueError): await observe(Path(temp)/'unused', cycles)
            self.assertFalse((Path(temp)/'unused').exists())
