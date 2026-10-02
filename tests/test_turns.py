"""차례 경계 사건(CMD-T2 · BD-47) -- 입력을 받음 · 차례가 열림 · 차례가 끝남 · 끝이 막힘 · 흐름이 닫힘.
L0 는 '차례가 열려 있다' 를 계산하지 않는다(그것은 L1 liveness 의 측정이다). 경계 사건만 원천에서 옮긴다."""
import json
import os
import tempfile
import unittest

from telemetry.catalog import EVENTS, F, check_catalog
from telemetry.collect import from_cc_jsonl, from_cc_stream
from telemetry.event import check

TURN_EVENTS = ("input.received", "turn.start", "turn.end", "turn.continued", "source.closed")


def ts(n):
    return f"2026-10-02T00:00:{n:02d}Z"


SESSION = [
    {"type": "queue-operation", "operation": "enqueue", "timestamp": ts(1), "content": "비밀 프롬프트 글"},
    {"type": "queue-operation", "operation": "dequeue", "timestamp": ts(2)},
    {"type": "user", "timestamp": ts(3), "turnOrigin": "human", "turnPosition": {"promptIndex": 1, "turnIndex": 1},
     "message": {"role": "user", "content": "비밀 프롬프트 글"}},
    {"type": "user", "isMeta": True, "timestamp": ts(4), "message": {"role": "user", "content": "<caveat>"}},
    {"type": "user", "isSidechain": True, "timestamp": ts(4), "message": {"role": "user", "content": "하위"}},
    {"type": "assistant", "timestamp": ts(5), "message": {"id": "m1", "usage": {"output_tokens": 3},
                                                         "content": [{"type": "tool_use", "id": "t1", "name": "Bash",
                                                                      "input": {"command": "ls"}}]}},
    {"type": "user", "timestamp": ts(6), "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "a", "is_error": False}]}},
    {"type": "system", "subtype": "stop_hook_summary", "timestamp": ts(7), "hookCount": 1,
     "preventedContinuation": True},
    {"type": "assistant", "timestamp": ts(8), "message": {"id": "m2", "usage": {"output_tokens": 2},
                                                         "content": [{"type": "text", "text": "끝"}]}},
    {"type": "system", "subtype": "stop_hook_summary", "timestamp": ts(9), "hookCount": 1,
     "preventedContinuation": False},
    {"type": "user", "timestamp": ts(10), "origin": {"kind": "task-notification"},
     "message": {"role": "user", "content": [{"type": "text", "text": "알림"}]}},
]


def _types(evs):
    return [e["type"] for e in evs]


class Catalog(unittest.TestCase):
    def test_turn_events_exist_and_hold_no_interpretation(self):
        for t in TURN_EVENTS:
            self.assertIn(t, EVENTS)
        self.assertEqual(check_catalog(), [])
        for bad in ("turn_stalled", "is_alive", "liveness_state", "idle_ms", "turn_active", "hung"):
            mutated = {"turn.start": dict(EVENTS["turn.start"], **{bad: F("bool", "measured")})}
            self.assertTrue(check_catalog(mutated), bad)
        # '차례가 열려 있다' · '무음 길이' 는 계산값(L1 의 측정)이다 -- L0 칸이 아니다
        fields = {k for t in TURN_EVENTS for k in EVENTS[t]}
        self.assertFalse(fields & {"turn_open", "silence_ms", "activity_at_ms", "terminal_seen", "transport_closed"})


class CCJsonlTurns(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        p = os.path.join(self.d.name, "s.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            for x in SESSION:
                f.write(json.dumps(x, ensure_ascii=False) + "\n")
        self.evs = from_cc_jsonl(p, "x")

    def tearDown(self):
        self.d.cleanup()

    def test_boundaries_in_source_order(self):
        self.assertEqual([check(e) for e in self.evs], [[]] * len(self.evs))
        self.assertEqual(_types(self.evs), ["input.received", "turn.start", "llm.response", "tool.start", "tool.end",
                                            "turn.continued", "llm.response", "turn.end", "turn.start"])
        self.assertEqual([e["seq"] for e in self.evs], list(range(len(self.evs))))

    def test_fields_are_what_the_source_said(self):
        by = {}
        for e in self.evs:
            by.setdefault(e["type"], []).append(e)
        inp = by["input.received"][0]
        self.assertEqual(inp["data"]["input_chars"], len("비밀 프롬프트 글"))
        s1, s2 = by["turn.start"]
        self.assertEqual((s1["data"]["turn_index"], s1["data"]["prompt_index"], s1["data"]["turn_origin"]), (1, 1, "human"))
        self.assertEqual(s2["data"]["turn_origin"], "task-notification")
        self.assertIn("turn_index", s2["unobserved"])              # 원천이 번호를 안 줬다 -- 세어서 메우지 않는다
        self.assertEqual(by["turn.continued"][0]["data"]["marker"], "stop_hook_summary")
        self.assertEqual(by["turn.end"][0]["data"]["stop_hook_count"], 1)
        self.assertNotIn("비밀", json.dumps(self.evs, ensure_ascii=False))   # 입력 글은 길이만

    def test_no_close_without_a_close_marker(self):
        """Claude Code JSONL 에는 흐름이 닫혔다는 표시가 없다. 파일 끝은 닫힘이 아니다(아직 쓰이는 중일 수 있다)."""
        self.assertNotIn("source.closed", _types(self.evs))


class ResumeBoundary(unittest.TestCase):
    """CMD-T13: 재개 뒤 첫 user 줄은 isMeta + turnPosition(turnOrigin "system") 이다(Sensor 세션 실기록 탐침, 02:13).
    런타임이 선언한 차례 경계라 turn.start 를 낸다. 입력은 아니다 -- input.received 는 enqueue 둘 그대로."""

    ROWS = [
        {"type": "assistant", "timestamp": ts(1), "isApiErrorMessage": True, "apiErrorStatus": 429, "error": "rate_limit",
         "message": {"id": "e1", "model": "<synthetic>", "content": []}},
        {"type": "queue-operation", "operation": "enqueue", "timestamp": ts(40)},
        {"type": "queue-operation", "operation": "enqueue", "timestamp": ts(41), "content": "다시 해"},
        {"type": "queue-operation", "operation": "dequeue", "timestamp": ts(42)},
        {"type": "user", "isMeta": True, "timestamp": ts(43), "turnOrigin": "system",
         "turnPosition": {"promptIndex": 7, "turnIndex": 9},
         "message": {"role": "user", "content": [{"type": "text", "text": "비밀 재개 글"}]}},
        {"type": "attachment", "timestamp": ts(44), "attachment": {}},
        {"type": "assistant", "timestamp": ts(45), "message": {"id": "m9", "model": "claude-x", "usage": {"output_tokens": 1},
                                                              "content": [{"type": "thinking"}]}},
        # 경계 선언이 없는 isMeta 줄(로컬 명령 안내 등)은 여전히 아무것도 아니다
        {"type": "user", "isMeta": True, "timestamp": ts(46), "message": {"role": "user", "content": "<caveat>"}},
    ]

    def test_meta_line_with_declared_position_opens_turn_but_is_not_input(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                for x in self.ROWS:
                    f.write(json.dumps(x, ensure_ascii=False) + "\n")
            evs = from_cc_jsonl(p, "x")
        self.assertEqual([check(e) for e in evs], [[]] * len(evs))
        self.assertEqual([e["type"] for e in evs if e["type"] in TURN_EVENTS],
                         ["turn.end", "input.received", "input.received", "turn.start"])
        st = [e for e in evs if e["type"] == "turn.start"][0]
        self.assertEqual((st["data"]["turn_origin"], st["data"]["turn_index"], st["data"]["prompt_index"]), ("system", 9, 7))
        resp = [e for e in evs if e["type"] == "llm.response"][0]
        self.assertLess(st["seq"], resp["seq"])                       # 경계가 응답 앞에
        self.assertNotIn("비밀", json.dumps(evs, ensure_ascii=False))


class CCStreamTurns(unittest.TestCase):
    def _run(self, rows):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.stream.jsonl")
            with open(p, "w") as f:
                for x in rows:
                    f.write(json.dumps(x) + "\n")
            return from_cc_stream(p, "s")

    ROWS = [{"_t": 0, "line": {"type": "system", "subtype": "init"}},
            {"_t": 100, "line": {"type": "stream_event", "event": {"type": "message_start",
                                                                   "message": {"id": "m1", "usage": {}}}}},
            {"_t": 500, "line": {"type": "result", "subtype": "success", "duration_ms": 500}}]

    def test_init_result_and_closure_row(self):
        evs = self._run(self.ROWS + [{"_t": 510, "closed": True, "returncode": 0}])
        self.assertEqual([check(e) for e in evs], [[]] * len(evs))
        self.assertEqual(_types(evs), ["turn.start", "llm.response", "run.end", "turn.end", "source.closed"])
        self.assertEqual((evs[-1]["at"], evs[-1]["data"]["exit_code"]), (510, 0))
        self.assertEqual(evs[3]["data"]["marker"], "result")

    def test_eof_without_closure_row_is_not_closure(self):
        self.assertNotIn("source.closed", _types(self._run(self.ROWS)))

    def test_cut_stream_has_start_but_no_end(self):
        """결과 줄 전에 끊긴 기록: 차례 시작만 있다. 끝을 지어내지 않는다 -- L1 이 '끝 신호 없음' 을 본다."""
        evs = self._run(self.ROWS[:2])
        self.assertEqual(_types(evs), ["turn.start", "llm.response"])


if __name__ == "__main__":
    unittest.main()
