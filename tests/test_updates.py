"""Tests for app.version and app.updates. No network is touched.

What matters here is what the user is told. Announcing an update that does not
exist, or one they cannot act on, is worse than saying nothing -- so the
comparison is tested harder than the fetching is.

Run: python -m unittest discover tests
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tests  # noqa: E402,F401

from app import updates, version  # noqa: E402


class Parsing(unittest.TestCase):
    def test_plain_and_tagged_forms_agree(self):
        for text in ("1.4.1", "v1.4.1", "V1.4.1"):
            self.assertEqual(version.as_tuple(text), (1, 4, 1))

    def test_short_versions_are_padded(self):
        self.assertEqual(version.as_tuple("2"), (2, 0, 0))
        self.assertEqual(version.as_tuple("2.1"), (2, 1, 0))

    def test_a_suffix_is_tolerated(self):
        """Tags are written by hand, so 1.5.0-beta must not crash the check."""
        self.assertEqual(version.as_tuple("v1.5.0-beta"), (1, 5, 0))

    def test_nonsense_is_none_rather_than_an_exception(self):
        for text in ("", "latest", "vNext", "..", "v.1"):
            self.assertIsNone(version.as_tuple(text), text)

    def test_our_own_constant_parses(self):
        self.assertIsNotNone(version.as_tuple())


class WindowsMetadata(unittest.TestCase):
    """version_info.txt spells the version a fourth time.

    PyInstaller reads it at build time and cannot read it from Python, so it can
    only be kept in step by checking. A mismatch is invisible until someone opens
    the properties of a shipped exe and sees the wrong number.
    """

    def setUp(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "version_info.txt"), encoding="utf-8") as f:
            self.text = f.read()

    def test_the_resource_matches_the_module(self):
        major, minor, patch = version.as_tuple()
        self.assertIn(f"filevers=({major}, {minor}, {patch}, 0)", self.text)
        self.assertIn(f"prodvers=({major}, {minor}, {patch}, 0)", self.text)
        self.assertIn(f'"FileVersion", "{major}.{minor}.{patch}.0"', self.text)
        self.assertIn(f'"ProductVersion", "{major}.{minor}.{patch}.0"', self.text)


class Comparison(unittest.TestCase):
    def test_a_later_version_is_newer(self):
        for candidate in ("1.4.2", "1.5.0", "2.0.0", "v1.10.0"):
            self.assertTrue(version.is_newer(candidate, "1.4.1"), candidate)

    def test_the_same_version_is_not_newer(self):
        self.assertFalse(version.is_newer("1.4.1", "1.4.1"))
        self.assertFalse(version.is_newer("v1.4.1", "1.4.1"))

    def test_an_older_version_is_not_newer(self):
        for candidate in ("1.4.0", "1.3.9", "0.9.9"):
            self.assertFalse(version.is_newer(candidate, "1.4.1"), candidate)

    def test_ten_beats_nine(self):
        """String comparison would get this wrong, and eventually it will matter."""
        self.assertTrue(version.is_newer("1.10.0", "1.9.0"))

    def test_an_unparseable_tag_is_never_newer(self):
        """Better silent than pointing at a release nobody can identify."""
        self.assertFalse(version.is_newer("latest", "1.4.1"))
        self.assertFalse(version.is_newer("1.5.0", "garbage"))


class Checking(unittest.TestCase):
    def setUp(self):
        updates._result.update({"checked": False, "available": False, "latest": None})

    def _fetch(self, payload):
        return mock.patch.object(updates, "_fetch", return_value=payload)

    def test_a_newer_release_is_reported(self):
        with self._fetch({"tag_name": "v1.5.0", "html_url": "https://example/1.5.0"}):
            r = updates.check(current="1.4.1", force=True)
        self.assertTrue(r["available"])
        self.assertEqual(r["latest"], "1.5.0")
        self.assertEqual(r["url"], "https://example/1.5.0")

    def test_the_current_release_is_not_reported(self):
        with self._fetch({"tag_name": "v1.4.1"}):
            self.assertFalse(updates.check(current="1.4.1", force=True)["available"])

    def test_a_prerelease_is_ignored(self):
        """Not something to point an ordinary user at."""
        with self._fetch({"tag_name": "v2.0.0", "prerelease": True}):
            self.assertFalse(updates.check(current="1.4.1", force=True)["available"])

    def test_a_draft_is_ignored(self):
        with self._fetch({"tag_name": "v2.0.0", "draft": True}):
            self.assertFalse(updates.check(current="1.4.1", force=True)["available"])

    def test_being_offline_is_not_an_error(self):
        with mock.patch.object(updates, "_fetch", side_effect=OSError("no network")):
            r = updates.check(current="1.4.1", force=True)
        self.assertFalse(r["available"])
        self.assertFalse(r["checked"])

    def test_a_recent_check_is_not_repeated(self):
        """One request a day. The thing being watched moves every few weeks."""
        import time
        with mock.patch.object(updates, "_fetch") as fetch:
            updates.check(current="1.4.1", last_checked=time.time())
        fetch.assert_not_called()

    def test_a_stale_check_is_repeated(self):
        import time
        with self._fetch({"tag_name": "v1.5.0"}) as fetch:
            updates.check(current="1.4.1",
                          last_checked=time.time() - updates.CHECK_INTERVAL - 1)
        fetch.assert_called_once()

    def test_the_timestamp_is_handed_back_for_persisting(self):
        seen = []
        with self._fetch({"tag_name": "v1.4.1"}):
            updates.check(current="1.4.1", force=True, save_cb=seen.append)
        self.assertEqual(len(seen), 1)

    def test_a_failing_save_does_not_break_the_check(self):
        def boom(_ts):
            raise OSError("read-only disk")
        with self._fetch({"tag_name": "v1.5.0"}):
            self.assertTrue(
                updates.check(current="1.4.1", force=True, save_cb=boom)["available"])


class Route(unittest.TestCase):
    def setUp(self):
        from app import server as srv
        self.srv = srv
        self.c = srv.app.test_client()
        if os.path.exists(srv.CONFIG_PATH):
            os.unlink(srv.CONFIG_PATH)

    def test_the_route_answers_without_checking(self):
        with mock.patch.object(updates, "_fetch") as fetch:
            r = self.c.get("/api/update")
        self.assertEqual(r.status_code, 200)
        fetch.assert_not_called()

    def test_turning_it_off_is_honoured_by_the_route(self):
        self.c.post("/api/config", json={"update_check": False})
        body = self.c.get("/api/update").get_json()
        self.assertTrue(body["disabled"])
        self.assertFalse(body["available"])

    def test_it_is_on_unless_turned_off(self):
        self.assertTrue(self.c.get("/api/config").get_json()["update_check"])


if __name__ == "__main__":
    unittest.main()
