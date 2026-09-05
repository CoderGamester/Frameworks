import pathlib
import tempfile
import unittest

import changelog


class PendingChangelogTests(unittest.TestCase):
    def write(self, directory: str, data: bytes) -> pathlib.Path:
        path = pathlib.Path(directory) / "CHANGELOG.md"
        path.write_bytes(data)
        return path

    def test_validate_rejects_unreleased_mixed_with_target_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                directory,
                b"# Changelog\n\n## [Unreleased]\n\n**New**:\n- Draft.\n\n"
                b"## [1.2.3] - 2026-08-04\n\n**Fixed**:\n- Fixed behavior.\n",
            )

            with self.assertRaisesRegex(changelog.ChangelogError, "Unreleased"):
                changelog.validate_pending(path, "1.2.3", "2026-08-04")

    def test_validate_rejects_wrong_date_and_noncanonical_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                directory,
                b"# Changelog\n\n## [1.2.3] - 2026-08-03\n\n### Added\n- Feature.\n",
            )

            with self.assertRaisesRegex(changelog.ChangelogError, "expected 2026-08-04"):
                changelog.validate_pending(path, "1.2.3", "2026-08-04")

            path.write_text(
                "# Changelog\n\n## [1.2.3] - 2026-08-04\n\n### Added\n- Feature.\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(changelog.ChangelogError, "canonical labels"):
                changelog.validate_pending(path, "1.2.3", "2026-08-04")

    def test_validate_rejects_target_when_a_higher_version_exists_later(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                directory,
                b"# Changelog\n\n## [1.2.3] - 2026-08-04\n\n**Fixed**:\n- Pending.\n\n"
                b"## [2.0.0] - 2026-07-01\n\n**New**:\n- Impossible history.\n",
            )

            with self.assertRaisesRegex(changelog.ChangelogError, "not the highest version"):
                changelog.validate_pending(path, "1.2.3", "2026-08-04")

    def test_rewrite_merges_unreleased_and_preserves_bom_crlf_history_and_eof(self):
        with tempfile.TemporaryDirectory() as directory:
            historical = (
                "## [1.2.2] - 2026-07-01\r\n\r\n"
                "**Fixed**:\r\n- Historical bytes stay unchanged.\r\n"
            ).encode()
            original = (
                b"\xef\xbb\xbf# Changelog\r\n\r\n"
                b"## [Unreleased]\r\n\r\n**New**:\r\n- Draft detail.\r\n\r\n"
                b"## [1.2.3] - 2026-08-01\r\n\r\n**Fixed**:\r\n- Old draft.\r\n\r\n"
                + historical
            )
            path = self.write(directory, original)

            changelog.rewrite_pending(
                path,
                "1.2.3",
                "2026-08-04",
                "**New**:\n- Public capability.\n\n**Fixed**:\n- Observable defect.",
            )

            rewritten = path.read_bytes()
            self.assertTrue(rewritten.startswith(b"\xef\xbb\xbf"))
            self.assertNotIn(b"[Unreleased]", rewritten)
            self.assertIn(b"## [1.2.3] - 2026-08-04\r\n", rewritten)
            self.assertTrue(rewritten.endswith(historical))
            self.assertNotIn(b"\n", rewritten.replace(b"\r\n", b""))
            changelog.validate_pending(path, "1.2.3", "2026-08-04")

    def test_rewrite_promotes_unreleased_when_target_version_does_not_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            historical = (
                b"## [1.2.2] - 2026-07-01\r\n\r\n"
                b"**Fixed**:\r\n- Historical bytes stay unchanged.\r\n"
            )
            path = self.write(
                directory,
                b"# Changelog\r\n\r\n## [Unreleased]\r\n\r\n"
                b"**New**:\r\n- Public capability.\r\n\r\n" + historical,
            )

            body = changelog.unreleased_body(path)
            changelog.rewrite_pending(path, "1.3.0", "2026-08-13", body)

            rewritten = path.read_bytes()
            self.assertNotIn(b"[Unreleased]", rewritten)
            self.assertIn(b"## [1.3.0] - 2026-08-13\r\n", rewritten)
            self.assertTrue(rewritten.endswith(historical))
            self.assertNotIn(b"\n", rewritten.replace(b"\r\n", b""))
            changelog.validate_pending(path, "1.3.0", "2026-08-13")

    def test_unreleased_body_rejects_ambiguous_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                directory,
                b"# Changelog\n\n## [Unreleased]\n\n**New**:\n- One.\n\n"
                b"## [Unreleased]\n\n**Fixed**:\n- Two.\n",
            )

            with self.assertRaisesRegex(changelog.ChangelogError, "exactly one"):
                changelog.unreleased_body(path)

    def test_validate_detects_historical_changes_against_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            baseline = self.write(
                directory,
                b"# Changelog\n\n## [1.2.3] - 2026-08-04\n\n**New**:\n- Feature.\n\n"
                b"## [1.2.2] - 2026-07-01\n\n**Fixed**:\n- Original.\n",
            )
            candidate = pathlib.Path(directory) / "candidate.md"
            candidate.write_bytes(baseline.read_bytes().replace(b"Original", b"Rewritten"))

            with self.assertRaisesRegex(changelog.ChangelogError, "historical"):
                changelog.validate_pending(
                    candidate,
                    "1.2.3",
                    "2026-08-04",
                    baseline=baseline,
                )

    def test_validate_accepts_master_baseline_without_pending_version(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = self.write(
                directory,
                b"# Changelog\n\n## [1.2.3] - 2026-08-04\n\n**New**:\n- Feature.\n\n"
                b"## [1.2.2] - 2026-07-01\n\n**Fixed**:\n- Published history.\n",
            )
            baseline = pathlib.Path(directory) / "master.md"
            baseline.write_bytes(
                b"# Changelog\n\n## [1.2.2] - 2026-07-01\n\n**Fixed**:\n- Published history.\n"
            )

            changelog.validate_pending(
                candidate,
                "1.2.3",
                "2026-08-04",
                baseline=baseline,
            )

            changelog.validate_pending(
                candidate,
                "1.2.3",
                "2026-08-04",
                baseline_bytes=baseline.read_bytes(),
            )


if __name__ == "__main__":
    unittest.main()
