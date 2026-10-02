"""BD-50 대조 장부(eval/l0_check.py) -- '서로 다른 기록' 을 파일이 아니라 기록 식별자로 센다."""
import importlib.util
import json
import pathlib
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("l0_check", pathlib.Path(__file__).resolve().parents[1] / "eval" / "l0_check.py")
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)


class Corpus(unittest.TestCase):
    def test_same_session_twice_is_one_recording(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = pathlib.Path(d, "a.jsonl"), pathlib.Path(d, "b.jsonl")
            a.write_text(json.dumps({"sessionId": "s1"}) + "\n")
            b.write_text(json.dumps({"sessionId": "s1"}) + "\n" + json.dumps({"type": "x"}) + "\n")
            self.assertEqual(L.recording_id("cc_jsonl", a), L.recording_id("cc_jsonl", b))
            self.assertNotEqual(L.content_hash(a), L.content_hash(b))
            self.assertNotIn("s1", L.recording_id("cc_jsonl", a))          # 식별자도 해시로만

    def test_bd50_needs_three_recordings_all_same_per_source(self):
        row = lambda s, r, same=True: {"source": s, "recording": r, "same": same}
        rows = [row("sweagent", x) for x in "abc"] + [row("cc_jsonl", "a"), row("cc_jsonl", "a")]
        s = L.summary(rows)
        self.assertTrue(s["sweagent"]["meets_bd50"])
        self.assertFalse(s["cc_jsonl"]["meets_bd50"])                     # 두 번 쟀어도 기록은 하나
        self.assertFalse(s["all_sources_meet_bd50"])
        s = L.summary(rows + [row("sweagent", "d", False)])
        self.assertFalse(s["sweagent"]["meets_bd50"])                     # 하나라도 다르면 아니다


if __name__ == "__main__":
    unittest.main()
