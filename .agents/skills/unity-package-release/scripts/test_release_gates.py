"""Unit fixtures for the G18 fan-out gate and the audit fetch-once helper.

Both exist because of a recorded incident: a workflow installed into six package repositories
before any of them had run it, and a published tarball downloaded four times in one sweep.
"""
import pathlib
import tempfile
import unittest

import release

REF_A = "a" * 40
REF_B = "b" * 40


def workflow_with(ref):
    return f"jobs:\n  preflight:\n    steps:\n      - uses: actions/checkout@v7\n        with:\n          ref: {ref}\n"


class FanOutGate(unittest.TestCase):
    def test_single_target_needs_no_proof(self):
        release.assert_fan_out_proven(["services"], REF_A, set())

    def test_fan_out_refused_without_a_green_run(self):
        with self.assertRaisesRegex(release.Fail, "G18"):
            release.assert_fan_out_proven(["services", "statechart"], REF_A, set())

    def test_every_package_refused_without_a_green_run(self):
        with self.assertRaisesRegex(release.Fail, "G18"):
            release.assert_fan_out_proven(list(release.ALL_PACKAGES), REF_A, {REF_B})

    def test_fan_out_allowed_once_a_repository_proved_the_ref(self):
        release.assert_fan_out_proven(["services", "statechart"], REF_A, {REF_A})

    def test_proven_refs_ignore_failed_runs_and_other_refs(self):
        runs = {"workflow_runs": [
            {"conclusion": "success", "head_sha": "s1"},
            {"conclusion": "failure", "head_sha": "s2"},
        ]}
        bodies = {"s1": workflow_with(REF_A), "s2": workflow_with(REF_B)}
        self.assertEqual(release.proven_tooling_refs(runs, bodies.get), {REF_A})

    def test_a_run_whose_workflow_pins_nothing_proves_nothing(self):
        runs = {"workflow_runs": [{"conclusion": "success", "head_sha": "s1"}]}
        self.assertEqual(release.proven_tooling_refs(runs, lambda sha: "jobs: {}\n"), set())


class FetchOnce(unittest.TestCase):
    def test_a_cached_tarball_is_reused(self):
        with tempfile.TemporaryDirectory() as scratch:
            workdir = pathlib.Path(scratch) / "audit"
            workdir.mkdir()
            (workdir / "pkg-1.0.0.tgz").write_bytes(b"cached")
            calls = []
            found = release.release_asset(workdir, lambda: calls.append(1))
            self.assertEqual(found.name, "pkg-1.0.0.tgz")
            self.assertEqual(calls, [], "a cached asset must not be downloaded again")

    def test_an_absent_tarball_is_downloaded_once(self):
        with tempfile.TemporaryDirectory() as scratch:
            workdir = pathlib.Path(scratch) / "audit"
            calls = []

            def download():
                calls.append(1)
                (workdir / "pkg-1.0.0.tgz").write_bytes(b"fetched")

            found = release.release_asset(workdir, download)
            self.assertEqual(found.name, "pkg-1.0.0.tgz")
            self.assertEqual(calls, [1])

    def test_a_download_that_produces_nothing_reports_no_asset(self):
        with tempfile.TemporaryDirectory() as scratch:
            workdir = pathlib.Path(scratch) / "audit"
            self.assertIsNone(release.release_asset(workdir, lambda: None))


if __name__ == "__main__":
    unittest.main()
