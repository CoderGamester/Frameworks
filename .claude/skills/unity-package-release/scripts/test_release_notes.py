import unittest
from types import SimpleNamespace

import release


class ReleaseNotesTests(unittest.TestCase):
    def test_notes_match_normalizes_transport_newlines_only(self):
        self.assertTrue(release.notes_match("**New**:\r\n- Feature.\r\n", "**New**:\n- Feature."))
        self.assertFalse(release.notes_match("**New**:\n- Feature A.\n", "**New**:\n- Feature B."))

    def test_open_pr_with_stale_body_resolves_to_sync_phase(self):
        facts = {
            "release": None,
            "pointer_current": False,
            "tag_sha": None,
            "master_version": "1.2.2",
            "open_pr": {"number": 19, "url": "https://example.test/pr/19"},
            "pr_notes_current": False,
            "closed_unmerged": [],
        }

        phase, _ = release.resolve_phase(SimpleNamespace(version="1.2.3"), facts)

        self.assertEqual("P2_SYNC_NOTES", phase)

    def test_release_pr_metadata_accepts_exact_standard(self):
        release.validate_release_pr_metadata(
            "1.2.3", "**New**:\n- Feature.", "Release 1.2.3", "**New**:\r\n- Feature.\r\n"
        )

    def test_release_pr_metadata_rejects_title_or_embellished_body(self):
        with self.assertRaisesRegex(release.Fail, "title"):
            release.validate_release_pr_metadata(
                "1.2.3", "**New**:\n- Feature.", "v1.2.3", "**New**:\n- Feature."
            )
        with self.assertRaisesRegex(release.Fail, "body"):
            release.validate_release_pr_metadata(
                "1.2.3",
                "**New**:\n- Feature.",
                "Release 1.2.3",
                "## Summary\n\n**New**:\n- Feature.",
            )

    def test_manifest_version_replacement_preserves_bytes(self):
        original = b'\xef\xbb\xbf{\r\n  "name": "example",\r\n  "version": "1.2.2"\r\n}\r\n'
        replaced = release.replace_manifest_version_bytes(original, "1.2.3")

        self.assertEqual(
            b'\xef\xbb\xbf{\r\n  "name": "example",\r\n  "version": "1.2.3"\r\n}\r\n',
            replaced,
        )

    def test_completion_action_is_postmerge_and_rebuilds_missing_tarball(self):
        self.assertEqual("halt", release.completion_action("P2_AWAIT_MERGE", False))
        self.assertEqual("pack", release.completion_action("P3_TAG", False))
        self.assertEqual("tag", release.completion_action("P3_TAG", True))
        self.assertEqual("publish", release.completion_action("P4_RELEASE", True))
        self.assertEqual("bump-host", release.completion_action("P6_HOST_BUMP", False))
        self.assertEqual("done", release.completion_action("P7_DONE", False))

    def test_isolated_pack_ignores_only_other_package_status_changes(self):
        pkg = SimpleNamespace(folder="com.gamelovers.mobileservices")
        release.assert_pack_side_effects(
            pkg,
            "",
            "",
            " M Packages/com.gamelovers.uiservice",
            " M Packages/com.gamelovers.uiservice\n M Packages/com.gamelovers.gamedata",
            isolated=True,
        )
        with self.assertRaisesRegex(release.Fail, "host after-only"):
            release.assert_pack_side_effects(
                pkg,
                "",
                "",
                "",
                " M Packages/manifest.json",
                isolated=True,
            )

    def test_exact_path_guard_rejects_extra_staged_file(self):
        with self.assertRaisesRegex(release.Fail, "unexpected.txt"):
            release.assert_exact_paths(
                ["CHANGELOG.md", "package.json", "unexpected.txt"],
                ["CHANGELOG.md", "package.json"],
                "fixture",
            )

    def test_porcelain_path_accepts_preserved_and_stripped_leading_status_space(self):
        self.assertEqual("CHANGELOG.md", release.porcelain_path(" M CHANGELOG.md"))
        self.assertEqual("CHANGELOG.md", release.porcelain_path("M CHANGELOG.md"))
        self.assertEqual("new.md", release.porcelain_path("R  old.md -> new.md"))
        self.assertEqual("new.md", release.porcelain_path("R old.md -> new.md"))


if __name__ == "__main__":
    unittest.main()
