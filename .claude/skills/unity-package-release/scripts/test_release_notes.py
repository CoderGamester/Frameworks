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


if __name__ == "__main__":
    unittest.main()
