"""eval/capture_stream.py -- 줄마다 {"_t", "line"}, 끝에 닫힘 줄. 그 캡처에서 L0 가 source.closed 를 낸다."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from telemetry.collect import from_cc_stream

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Capture(unittest.TestCase):
    def test_rows_and_closure(self):
        prog = ("import json; print(json.dumps({'type': 'system', 'subtype': 'init'})); print('not json'); "
                "print(json.dumps({'type': 'result', 'subtype': 'success'})); raise SystemExit(3)")
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "c.stream.jsonl")
            p = subprocess.run([sys.executable, os.path.join(ROOT, "eval", "capture_stream.py"), out, "--cwd", d,
                                "--clean-env", "--", sys.executable, "-c", prog], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            rows = [json.loads(x) for x in open(out, encoding="utf-8")]
            evs = from_cc_stream(out, "c")
        self.assertEqual([("line" in r, "raw" in r, r.get("closed")) for r in rows],
                         [(True, False, None), (False, True, None), (True, False, None), (False, False, True)])
        self.assertEqual(rows[-1]["returncode"], 3)
        self.assertTrue(all(a["_t"] <= b["_t"] for a, b in zip(rows, rows[1:])))
        closed = [e for e in evs if e["type"] == "source.closed"]
        self.assertEqual([e["data"]["exit_code"] for e in closed], [3])


if __name__ == "__main__":
    unittest.main()
