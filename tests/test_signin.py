"""The sign-in window closes itself once YouTube has a session.

Run: python -m unittest discover tests
"""
import os
import sys
import unittest
from http.cookies import SimpleCookie

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Must precede any app import: it redirects the data roots to a sandbox.
import tests  # noqa: E402,F401

import main  # noqa: E402


def _jar(**pairs):
    out = []
    for name, value in pairs.items():
        c = SimpleCookie()
        c[name] = value
        out.append(c)
    return out


class CookiesProveSession(unittest.TestCase):
    def test_visitor_cookies_are_not_a_session(self):
        self.assertFalse(main.cookies_prove_session(
            _jar(VISITOR_INFO1_LIVE="x", YSC="y", GPS="1")))

    def test_sid_is_a_session(self):
        self.assertTrue(main.cookies_prove_session(_jar(YSC="y", SID="abc")))

    def test_empty_value_does_not_count(self):
        self.assertFalse(main.cookies_prove_session(_jar(SID="")))

    def test_nothing_is_not_a_session(self):
        self.assertFalse(main.cookies_prove_session(None))
        self.assertFalse(main.cookies_prove_session([]))


class FakeWindow:
    def __init__(self, states):
        self.states = iter(states)
        self.current = None
        self.destroyed = False

    def get_current_url(self):
        self.current = next(self.states)
        return self.current[0]

    def get_cookies(self):
        return self.current[1]

    def destroy(self):
        self.destroyed = True


class CloseWhenSignedIn(unittest.TestCase):
    def test_closes_after_sign_in_lands_on_youtube(self):
        w = FakeWindow([
            ("https://www.youtube.com/account", _jar(YSC="y")),
            ("https://accounts.google.com/signin", _jar(SID="g")),
            ("https://www.youtube.com/account", _jar(SID="abc")),
        ])
        main._close_when_signed_in(w, poll_s=0, settle_s=0)
        self.assertTrue(w.destroyed)

    def test_gives_up_quietly_when_the_user_closes_first(self):
        w = FakeWindow([])  # next() raises, as a closed window would
        main._close_when_signed_in(w, poll_s=0, settle_s=0)
        self.assertFalse(w.destroyed)


if __name__ == "__main__":
    unittest.main()
