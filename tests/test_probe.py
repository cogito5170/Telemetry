"""eval/shape_probe.py -- 꼴만 낸다(글 없음), 그 줄에서 난 L0 사건을 나란히."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Probe(unittest.TestCase):
    def test_shapes_without_text(self):
        rows = [{"type": "queue-operation", "operation": "enqueue", "timestamp": "2026-10-02T00:00:01Z", "content": "비밀"},
                {"type": "user", "timestamp": "2026-10-02T00:00:02Z", "turnOrigin": "human",
                 "turnPosition": {"turnIndex": 1}, "message": {"role": "user", "content": "비밀 질문"}},
                {"type": "user", "isMeta": True, "timestamp": "2026-10-02T00:00:03Z",
                 "message": {"role": "user", "content": [{"type": "text", "text": "비밀 메타"}]}}]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            out = subprocess.run([sys.executable, os.path.join(ROOT, "eval", "shape_probe.py"), p, "--lines", "0", "9"],
                                 capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn("비밀", out.stdout)
        lines = [json.loads(x) for x in out.stdout.splitlines()]
        self.assertEqual([x["l0_events"] for x in lines], [["input.received"], ["turn.start"], []])
        self.assertEqual((lines[1]["content"], lines[2]["flags"], lines[2]["content"]), ("str(5)", ["isMeta"], ["text"]))


if __name__ == "__main__":
    unittest.main()
