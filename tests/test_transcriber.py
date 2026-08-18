"""Pure-function tests for app.transcriber — no whisper, no ffmpeg, no network.

Run: python -m unittest discover tests
"""
import os
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Must precede any app import: it redirects the data roots to a sandbox.
# `unittest discover tests` imports these as top-level modules, so the
# package __init__ does not run on its own.
import tests  # noqa: E402,F401

from app import transcriber as tr


def _write_srt(path, blocks):
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(blocks))


def _write_wav(path, seconds, rate=16000):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))


class ParseSrt(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="y2obi_t_")

    def tearDown(self):
        for n in os.listdir(self.dir):
            os.unlink(os.path.join(self.dir, n))
        os.rmdir(self.dir)

    def _parse(self, text):
        p = os.path.join(self.dir, "a.srt")
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return tr._parse_srt(p)

    def test_basic_cues(self):
        cues = self._parse(
            "1\n00:00:01,500 --> 00:00:03,000\nhello there\n\n"
            "2\n00:01:00,000 --> 00:01:02,250\nsecond line\n\n"
        )
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0], {"start": 1500, "end": 3000, "text": "hello there"})
        self.assertEqual(cues[1]["start"], 60000)
        self.assertEqual(cues[1]["end"], 62250)

    def test_multiline_cue_is_joined(self):
        cues = self._parse("1\n00:00:00,000 --> 00:00:02,000\nline one\nline two\n\n")
        self.assertEqual(cues[0]["text"], "line one line two")

    def test_dot_separator_and_hours(self):
        cues = self._parse("1\n01:02:03.040 --> 01:02:04.000\nx\n\n")
        self.assertEqual(cues[0]["start"], (3600 + 120 + 3) * 1000 + 40)

    def test_empty_and_malformed_are_skipped(self):
        cues = self._parse("garbage\n1\nnot a timestamp\ntext\n\n")
        self.assertEqual(cues, [])


class MergeParts(unittest.TestCase):
    def test_offsets_are_applied(self):
        parts = [(0.0, [{"start": 0, "end": 1000, "text": "a"}]),
                 (600.0, [{"start": 0, "end": 1000, "text": "b"}])]
        out = tr._merge_parts(parts, 8.0)
        self.assertEqual([c["start"] for c in out], [0, 600000])

    def test_cue_fully_inside_covered_ground_is_dropped(self):
        parts = [(0.0, [{"start": 0, "end": 10000, "text": "a"}]),
                 (5.0, [{"start": 0, "end": 3000, "text": "a"},      # 5000-8000, covered
                        {"start": 6000, "end": 9000, "text": "b"}])]  # 11000-14000, new
        out = tr._merge_parts(parts, 8.0)
        self.assertEqual([c["text"] for c in out], ["a", "b"])

    def test_straddling_cue_kept_when_mostly_new(self):
        # covered to 10000; cue 8000-20000 is 10/12 new -> kept
        parts = [(0.0, [{"start": 0, "end": 10000, "text": "a"}]),
                 (0.0, [{"start": 8000, "end": 20000, "text": "long sentence"}])]
        out = tr._merge_parts(parts, 8.0)
        self.assertEqual([c["text"] for c in out], ["a", "long sentence"])

    def test_straddling_cue_dropped_when_mostly_overlap(self):
        # covered to 10000; cue 2000-11000 is 1/9 new -> dropped as a re-transcription
        parts = [(0.0, [{"start": 0, "end": 10000, "text": "a"}]),
                 (0.0, [{"start": 2000, "end": 11000, "text": "a again"}])]
        out = tr._merge_parts(parts, 8.0)
        self.assertEqual([c["text"] for c in out], ["a"])

    def test_empty(self):
        self.assertEqual(tr._merge_parts([], 8.0), [])


class DetectLoops(unittest.TestCase):
    def test_run_at_threshold_is_reported(self):
        cues = [{"text": "thanks for watching"} for _ in range(5)]
        self.assertEqual(tr._detect_loops(cues), [("thanks for watching", 5)])

    def test_shorter_run_is_ignored(self):
        cues = [{"text": "hi"} for _ in range(4)]
        self.assertEqual(tr._detect_loops(cues), [])

    def test_comparison_ignores_case_and_padding(self):
        cues = [{"text": " Hi "}, {"text": "hi"}, {"text": "HI"},
                {"text": "hi"}, {"text": "hi"}]
        self.assertEqual(tr._detect_loops(cues), [("hi", 5)])

    def test_run_broken_by_other_text(self):
        cues = [{"text": "a"}] * 3 + [{"text": "b"}] + [{"text": "a"}] * 3
        self.assertEqual(tr._detect_loops(cues), [])


class FmtTs(unittest.TestCase):
    def test_srt_format(self):
        self.assertEqual(tr._fmt_ts(0), "00:00:00,000")
        self.assertEqual(tr._fmt_ts(1500), "00:00:01,500")
        self.assertEqual(tr._fmt_ts(3661001), "01:01:01,001")

    def test_negative_clamps_to_zero(self):
        self.assertEqual(tr._fmt_ts(-5), "00:00:00,000")


class WavHelpers(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="y2obi_t_")
        self.src = os.path.join(self.dir, "a.wav")
        _write_wav(self.src, 10.0)

    def tearDown(self):
        for n in os.listdir(self.dir):
            os.unlink(os.path.join(self.dir, n))
        os.rmdir(self.dir)

    def test_duration(self):
        self.assertAlmostEqual(tr.wav_duration(self.src), 10.0, places=3)

    def test_duration_of_non_wav_is_zero(self):
        bad = os.path.join(self.dir, "bad.wav")
        with open(bad, "wb") as f:
            f.write(b"not a wav")
        self.assertEqual(tr.wav_duration(bad), 0.0)

    def test_slice_length_and_format(self):
        dst = os.path.join(self.dir, "chunk.wav")
        tr._slice_wav(self.src, dst, 4.0, 3.0)
        self.assertAlmostEqual(tr.wav_duration(dst), 3.0, places=3)
        with wave.open(dst, "rb") as w:
            self.assertEqual(w.getframerate(), 16000)
            self.assertEqual(w.getnchannels(), 1)
            self.assertEqual(w.getsampwidth(), 2)

    def test_slice_past_end_is_clamped(self):
        dst = os.path.join(self.dir, "chunk.wav")
        tr._slice_wav(self.src, dst, 8.0, 30.0)
        self.assertAlmostEqual(tr.wav_duration(dst), 2.0, places=3)

    def test_zero_duration_means_to_end(self):
        dst = os.path.join(self.dir, "chunk.wav")
        tr._slice_wav(self.src, dst, 6.0, 0)
        self.assertAlmostEqual(tr.wav_duration(dst), 4.0, places=3)


class WriteOutputs(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="y2obi_t_")

    def tearDown(self):
        for n in os.listdir(self.dir):
            os.unlink(os.path.join(self.dir, n))
        os.rmdir(self.dir)

    def test_txt_and_srt_roundtrip(self):
        cues = [{"start": 0, "end": 1500, "text": "one"},
                {"start": 1500, "end": 3000, "text": "two"}]
        txt, srt = tr.write_outputs(cues, os.path.join(self.dir, "out"))
        with open(txt, encoding="utf-8") as f:
            self.assertEqual(f.read().split("\n")[:2], ["one", "two"])
        self.assertEqual(tr._parse_srt(srt), cues)


class ModelCatalogue(unittest.TestCase):
    def test_ui_models_exist_and_are_labelled(self):
        for name in tr.UI_MODELS:
            self.assertIn(name, tr.MODELS)
            self.assertIn(name, tr.MODEL_LABELS)

    def test_default_model_is_offered(self):
        self.assertIn(tr.DEFAULT_MODEL, tr.UI_MODELS)

    def test_chunking_constants_leave_forward_progress(self):
        self.assertGreater(tr.CHUNK_SEC - tr.OVERLAP_SEC, 0)


if __name__ == "__main__":
    unittest.main()
