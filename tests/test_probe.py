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


class PreToolUseProbe(unittest.TestCase):
    """eval/pretooluse_probe.py -- 그 tool_use 줄이 있나 · 같은 바이트를 L0 로 거둔 값. 글 · 훅 입력 값은 내지 않는다."""

    def test_sees_line_and_l0_open_start_without_text(self):
        rows = [{"type": "user", "timestamp": "2026-10-02T00:00:01Z", "turnOrigin": "human", "turnPosition": {"turnIndex": 1},
                 "message": {"role": "user", "content": "비밀 질문"}},
                {"type": "assistant", "timestamp": "2026-10-02T00:00:02Z", "message": {
                    "id": "m1", "role": "assistant", "model": "claude-x", "usage": {"input_tokens": 1, "output_tokens": 1},
                    "content": [{"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "echo 비밀"}}]}}]
        with tempfile.TemporaryDirectory() as d:
            p, out = os.path.join(d, "s.jsonl"), os.path.join(d, "o.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            hook = {"hook_event_name": "PreToolUse", "tool_use_id": "toolu_1", "tool_name": "Bash", "transcript_path": p,
                    "tool_input": {"command": "echo 비밀"}, "session_id": "s"}
            env = dict(os.environ, T19_OUT=out, T19_TELEMETRY=ROOT, T19_DELAY_S="0")
            r = subprocess.run([sys.executable, os.path.join(ROOT, "eval", "pretooluse_probe.py")],
                               input=json.dumps(hook, ensure_ascii=False), capture_output=True, text=True, env=env)
            self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)       # 훅이 도구를 막지 않는다
            with open(out, encoding="utf-8") as f:
                text = f.read()
        self.assertNotIn("비밀", text)
        row = json.loads(text)
        self.assertEqual((row["at_hook"]["use"], row["at_hook"]["result"]), (True, False))
        self.assertEqual(row["at_hook"]["l0"], {"this_start": True, "starts": 1, "open_starts": 1})
        self.assertIn("tool_input", row["keys"])                               # 키 이름만


if __name__ == "__main__":
    unittest.main()
