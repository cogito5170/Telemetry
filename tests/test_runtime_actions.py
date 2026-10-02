"""CMD-T6 (수집기 결함 D1–D4 · 런타임 자신의 행동) · CMD-T5 (진행 신호 · 흡수된 입력).
원천 꼴은 Sensor docs/MS_HEALTH_INVENTORY.md §1 과 eval/health_inventory.py 가 실기록에서 읽은 키를 따랐다."""
import json
import os
import pathlib
import sys
import tempfile
import unittest

from telemetry.collect import from_cc_jsonl, from_cc_stream
from telemetry.compat import to_sensor_records
from telemetry.event import check
from telemetry.hashing import Hasher

SENSOR = pathlib.Path(__file__).resolve().parents[2] / "Sensor"
KEY = b"k"


def ts(n):
    return f"2026-10-02T00:00:{n:02d}Z"


QUOTA = {"status": "rejected", "rateLimitType": "five_hour", "overageStatus": "rejected", "resetsAt": 1790900000,
         "overageDisabledReason": "out_of_credits", "unifiedRateLimitFallbackAvailable": False}
SESSION = [
    {"type": "queue-operation", "operation": "enqueue", "timestamp": ts(1), "content": "go"},
    {"type": "user", "timestamp": ts(2), "turnOrigin": "human", "turnPosition": {"promptIndex": 1, "turnIndex": 1},
     "message": {"role": "user", "content": "go"}},
    {"type": "assistant", "timestamp": ts(3), "message": {"id": "m1", "model": "claude-x", "usage": {
        "input_tokens": 10, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "output_tokens": 3},
        "content": [{"type": "text", "text": "hi"}]}},
    {"type": "queue-operation", "operation": "enqueue", "timestamp": ts(4), "content": "또"},
    {"type": "queue-operation", "operation": "remove", "reason": "absorbed_mid_turn", "timestamp": ts(5)},
    # D2 · T11: 429 -- 런타임이 끼운 API 오류 줄(모형 호출이 아니다). 차례가 여기서 끝난다(Claude Code StopFailure 계약)
    {"type": "assistant", "timestamp": ts(6), "isApiErrorMessage": True, "apiErrorStatus": 429, "error": "rate_limit",
     "quotaLimits": QUOTA, "message": {"id": "e1", "model": "<synthetic>", "usage": {"input_tokens": 0, "output_tokens": 0},
                                       "content": [{"type": "text", "text": "API Error: rate limit"}]}},
    {"type": "assistant", "timestamp": ts(7), "message": {"id": "s1", "model": "<synthetic>", "usage": {},
                                                         "content": [{"type": "text", "text": "No response requested."}]}},
    # 사람을 기다린 뒤 다음 차례
    {"type": "queue-operation", "operation": "enqueue", "timestamp": ts(40), "content": "다시"},
    {"type": "user", "timestamp": ts(41), "turnOrigin": "human", "turnPosition": {"promptIndex": 2, "turnIndex": 2},
     "message": {"role": "user", "content": "다시"}},
    # D4: 압축
    {"type": "system", "subtype": "compact_boundary", "timestamp": ts(42),
     "compactMetadata": {"trigger": "auto", "preTokens": 783484, "postTokens": 7209, "durationMs": 69703}},
    {"type": "system", "subtype": "stop_hook_summary", "timestamp": ts(43), "hookCount": 1, "preventedContinuation": False},
]
STREAM = [
    {"_t": 0, "line": {"type": "system", "subtype": "init"}},
    {"_t": 10, "line": {"type": "system", "subtype": "status", "status": "requesting"}},
    {"_t": 20, "line": {"type": "stream_event", "event": {"type": "message_start", "message": {"id": "m1", "usage": {}}}}},
    {"_t": 30, "line": {"type": "assistant", "message": {"id": "m1", "content": [
        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "sleep 150"}}]}}},
    {"_t": 3030, "line": {"type": "tool_progress", "elapsed_time_seconds": 3}},
    {"_t": 30030, "line": {"type": "tool_progress", "elapsed_time_seconds": 30, "heartbeat": True}},
    {"_t": 120100, "line": {"type": "user", "tool_use_result": {"interrupted": False, "timedOutAfterMs": 120000},
                            "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": True,
                                                     "content": "Exit code 143\nCommand timed out after 2m 0.0s"}]}}},
    {"_t": 120200, "line": {"type": "system", "subtype": "compact_boundary",
                            "compact_metadata": {"trigger": "manual", "pre_tokens": 5000}}},
    {"_t": 121000, "line": {"type": "result", "subtype": "success", "duration_ms": 121000}},
]


def _write(d, name, rows, stream=False):
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as f:
        for x in rows:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    return p


def _of(evs, t):
    return [e for e in evs if e["type"] == t]


class JsonlRuntimeActions(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.p = _write(self.d.name, "s.jsonl", SESSION)
        self.evs = from_cc_jsonl(self.p, "x", Hasher(KEY))

    def tearDown(self):
        self.d.cleanup()

    def test_well_formed(self):
        self.assertEqual([check(e) for e in self.evs], [[]] * len(self.evs))

    def test_429_is_an_error_not_a_model_call(self):
        """D2 · D3: <synthetic> 줄은 모형 호출이 아니다 -- 단가표에 없는 '모델' 이 세션 비용을 None 으로 만들지 않는다."""
        calls = _of(self.evs, "llm.response")
        self.assertEqual([e["data"]["call_index"] for e in calls], [0])
        self.assertNotIn("<synthetic>", json.dumps(calls))
        err = _of(self.evs, "llm.error")[0]["data"]
        self.assertEqual((err["http_status"], err["provider_code"], err["error_code"]), (429, "rate_limit", "RATE_LIMITED"))
        rl = _of(self.evs, "provider.rate_limit")[0]["data"]
        self.assertEqual((rl["declared_status"], rl["limit_type"], rl["overage_status"], rl["overage_disabled_reason"],
                          rl["fallback_available"]), ("rejected", "five_hour", "rejected", "out_of_credits", False))
        self.assertIsNone(rl["utilization"])                            # 사용률은 이 줄에 없다 -- 못 봄

    def test_compaction_and_absorbed_input(self):
        c = _of(self.evs, "runtime.compaction")[0]["data"]
        self.assertEqual((c["trigger"], c["pre_tokens"], c["post_tokens"], c["duration_ms"]), ("auto", 783484, 7209, 69703))
        self.assertEqual(_of(self.evs, "input.removed")[0]["data"]["reason"], "absorbed_mid_turn")
        self.assertEqual(len(_of(self.evs, "input.received")), 3)
        self.assertEqual(len(_of(self.evs, "turn.start")), 2)         # 흡수된 입력은 새 차례를 열지 않았다

    def test_turn_ended_by_api_error_is_closed(self):
        """CMD-T11: 429 로 끝난 차례는 그 오류 줄에서 닫힌다(Stop 훅은 돌지 않는다). 사람을 기다린 시간이 차례 중이 아니다."""
        seq = [(e["type"], e["data"].get("marker"), e["data"].get("turn_index"))
               for e in self.evs if e["type"] in ("turn.start", "turn.end")]
        self.assertEqual(seq, [("turn.start", None, 1), ("turn.end", "api_error", None),
                               ("turn.start", None, 2), ("turn.end", "stop_hook_summary", None)])
        end = [e for e in _of(self.evs, "turn.end") if e["data"]["marker"] == "api_error"][0]
        self.assertEqual(end["data"]["error_type"], "rate_limit")
        err = _of(self.evs, "llm.error")[0]
        self.assertLess(err["seq"], end["seq"])                       # 오류 사건 뒤에 차례 끝

    def test_v3_run_record_carries_the_429(self):
        run = [r for r in to_sensor_records(self.evs) if r["kind"] == "run"][0]
        self.assertEqual((run["api_error_status"], run["rate_limit_status"]), ("429", "rejected"))
        self.assertEqual(len([r for r in to_sensor_records(self.evs) if r["kind"] == "model_call"]), 1)


class StreamRuntimeActions(unittest.TestCase):
    def test_progress_timeout_compaction(self):
        with tempfile.TemporaryDirectory() as d:
            evs = from_cc_stream(_write(d, "a.stream.jsonl", STREAM), "s", Hasher(KEY))
        self.assertEqual([check(e) for e in evs], [[]] * len(evs))
        hb = _of(evs, "heartbeat")
        self.assertEqual([(e["data"]["beat"], e["data"]["heartbeat_flag"], e["data"]["reported_elapsed_ms"]) for e in hb],
                         [(0, None, 3000), (1, True, 30000)])
        self.assertIn("heartbeat_flag", hb[0]["unobserved"])           # 표시가 없었다 -- False 로 메우지 않는다
        self.assertEqual(_of(evs, "runtime.status")[0]["data"]["declared_status"], "requesting")
        end = _of(evs, "tool.end")[0]["data"]
        self.assertEqual((end["timed_out"], end["declared_timeout_ms"], end["moved_to_background"]), (True, 120000, False))
        c = _of(evs, "runtime.compaction")[0]
        self.assertEqual((c["data"]["trigger"], c["data"]["pre_tokens"]), ("manual", 5000))
        self.assertIn("post_tokens", c["unobserved"])


class ResetsAt(unittest.TestCase):
    """CMD-T14: 원천 resetsAt(unix 초) -> resets_at_ms. 키가 없으면 못 봄, null 이면 보고된 null."""

    def _stream(self, info):
        rows = [{"_t": 0, "line": {"type": "system", "subtype": "init"}},
                {"_t": 5, "line": {"type": "rate_limit_event", "rate_limit_info": info}}]
        with tempfile.TemporaryDirectory() as d:
            return _of(from_cc_stream(_write(d, "r.stream.jsonl", rows), "s", Hasher(KEY)), "provider.rate_limit")[0]

    def test_stream_seconds_to_ms(self):
        e = self._stream({"status": "allowed_warning", "utilization": 0.8, "resetsAt": 1790913600,
                          "rateLimitType": "five_hour", "isUsingOverage": False, "surpassedThreshold": 0.75})
        self.assertEqual(check(e), [])
        self.assertEqual(e["data"]["resets_at_ms"], 1790913600000)
        self.assertEqual((e["data"]["limit_type"], e["data"]["overage_status"]), ("five_hour", None))
        self.assertIn("overage_status", e["unobserved"])                # 이 줄에는 없었다

    def test_missing_null_and_odd(self):
        self.assertIn("resets_at_ms", self._stream({"status": "allowed"})["unobserved"])
        self.assertIn("resets_at_ms", self._stream({"status": "allowed", "resetsAt": None})["reported_null"])
        self.assertIn("resets_at_ms", self._stream({"status": "allowed", "resetsAt": "soon"})["unobserved"])

    def test_jsonl_quota_limits(self):
        with tempfile.TemporaryDirectory() as d:
            evs = from_cc_jsonl(_write(d, "s.jsonl", SESSION), "x", Hasher(KEY))
        rl = _of(evs, "provider.rate_limit")[0]["data"]
        self.assertEqual(rl["resets_at_ms"], 1790900000 * 1000)


class RateLimitWindows(unittest.TestCase):
    """CMD-T15: rate_limit_info.unifiedWindows -> 창마다 provider.rate_limit_window. 창 이름은 원천 키 그대로,
    값은 원천이 준 것만, 어느 창도 고르지 않는다. 같은 줄의 provider.rate_limit 바로 뒤에 원천 차례대로."""

    # 실기록 claude -p 캡처 셋의 키 꼴(값은 지어냄): 창 둘, 창마다 utilization · resetsAt
    INFO = {"status": "allowed", "resetsAt": 1790913600, "rateLimitType": "five_hour", "isUsingOverage": False,
            "overageStatus": "rejected", "overageDisabledReason": "org_level_disabled",
            "unifiedWindows": {"seven_day": {"utilization": 0.07, "resetsAt": 1791400000},
                               "five_hour": {"utilization": 0.41, "resetsAt": 1790913600}}}

    def _stream(self, info):
        rows = [{"_t": 0, "line": {"type": "system", "subtype": "init"}},
                {"_t": 5, "line": {"type": "rate_limit_event", "rate_limit_info": info}},
                {"_t": 9, "line": {"type": "result", "subtype": "success"}}]
        with tempfile.TemporaryDirectory() as d:
            return from_cc_stream(_write(d, "w.stream.jsonl", rows), "s", Hasher(KEY))

    def test_one_event_per_window_in_source_order(self):
        evs = self._stream(self.INFO)
        self.assertEqual([check(e) for e in evs], [[]] * len(evs))
        ws = _of(evs, "provider.rate_limit_window")
        self.assertEqual([w["data"]["window_name"] for w in ws], ["seven_day", "five_hour"])   # 원천 차례 -- 고르거나 줄 세우지 않는다
        self.assertEqual(ws[0]["data"]["utilization"], 0.07)
        self.assertEqual(ws[0]["data"]["resets_at_ms"], 1791400000 * 1000)
        self.assertEqual({w["at"] for w in ws}, {5})
        rl = _of(evs, "provider.rate_limit")[0]
        self.assertEqual([w["seq"] for w in ws], [rl["seq"] + 1, rl["seq"] + 2])          # 같은 줄의 한도 보고 바로 뒤
        self.assertIn("utilization", rl["unobserved"])           # 이 꼴에는 맨 위 utilization 이 없다 -- 창 값을 끌어올리지 않는다

    def test_missing_null_and_odd_values(self):
        self.assertEqual(_of(self._stream({"status": "allowed"}), "provider.rate_limit_window"), [])
        self.assertEqual(_of(self._stream({"status": "allowed", "unifiedWindows": None}), "provider.rate_limit_window"), [])
        ws = _of(self._stream({"unifiedWindows": {"a": {"utilization": None}, "b": {"utilization": "high", "resetsAt": "x"},
                                                   "c": 3, "d": {"utilization": True}}}), "provider.rate_limit_window")
        self.assertEqual([w["data"]["window_name"] for w in ws], ["a", "b", "c", "d"])
        self.assertIn("utilization", ws[0]["reported_null"])
        self.assertIn("resets_at_ms", ws[0]["unobserved"])
        for w in ws[1:]:
            self.assertEqual(sorted(w["unobserved"]), ["resets_at_ms", "utilization"])

    def test_v3_records_unchanged(self):
        base = dict(self.INFO)
        del base["unifiedWindows"]
        self.assertEqual(to_sensor_records(self._stream(self.INFO)), to_sensor_records(self._stream(base)))


class ToolProgressHeartbeats(unittest.TestCase):
    """CMD-T12: 실제 t11 꼴 -- 두 id 를 다 단다. tool_use_id 는 지어낸 bash-progress-<n>, 진행 중인 Bash 의 id 는 parent_tool_use_id.
    주 에이전트 도구의 진행은 heartbeat 8, 하위 에이전트(Task) 안 도구의 진행은 걸러진다."""

    ROWS = [{"_t": 0, "line": {"type": "system", "subtype": "init"}},
            {"_t": 10, "line": {"type": "stream_event", "event": {"type": "message_start",
                                                                  "message": {"id": "m1", "usage": {}}}}},
            {"_t": 20, "line": {"type": "assistant", "message": {"id": "m1", "content": [
                {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "sleep 150"}},
                {"type": "tool_use", "id": "task1", "name": "Task", "input": {"prompt": "x"}}]}}}]
    # t11 실캡처의 키 꼴(값은 지어냄): 3 · 30 · 33 · 60 · 63 · 90 · 93 · 120 초, 30 초마다 heartbeat 표시
    ROWS += [{"_t": 20 + s * 1000, "line": {
        "type": "tool_progress", "tool_use_id": f"bash-progress-{i}", "parent_tool_use_id": "t1", "tool_name": "Bash",
        "session_id": "sess", "task_id": "task-x", "uuid": f"u{i}", "elapsed_time_seconds": s,
        "heartbeat": True if s % 30 == 0 else None}}
        for i, s in enumerate((3, 30, 33, 60, 63, 90, 93, 120))]
    ROWS += [  # 하위 에이전트: 그 assistant 줄 · 그 안 Bash 의 진행(parent 는 Task 호출) -- 거른다
             {"_t": 122000, "line": {"type": "assistant", "parent_tool_use_id": "task1", "message": {
                 "id": "sub1", "content": [{"type": "tool_use", "id": "st1", "name": "Bash", "input": {"command": "ls"}}]}}},
             {"_t": 123000, "line": {"type": "tool_progress", "tool_use_id": "bash-progress-9", "parent_tool_use_id": "task1",
                                     "tool_name": "Bash", "elapsed_time_seconds": 1}},
             # 이름 없는 진행 줄 -- 맞출 수 없어 남기지 않는다
             {"_t": 123500, "line": {"type": "tool_progress", "tool_use_id": "bash-progress-10", "parent_tool_use_id": "t1",
                                     "elapsed_time_seconds": 121}},
             {"_t": 124000, "line": {"type": "result", "subtype": "success"}}]

    def test_real_shape_main_tool_progress_kept_subagent_filtered(self):
        with tempfile.TemporaryDirectory() as d:
            evs = from_cc_stream(_write(d, "t11.stream.jsonl", self.ROWS), "s", Hasher(KEY))
        self.assertEqual([check(e) for e in evs], [[]] * len(evs))
        hb = _of(evs, "heartbeat")
        self.assertEqual(len(hb), 8)                                   # t11: 8/8
        self.assertEqual([e["data"]["reported_elapsed_ms"] for e in hb], [s * 1000 for s in (3, 30, 33, 60, 63, 90, 93, 120)])
        self.assertEqual(sum(1 for e in hb if e["data"]["heartbeat_flag"] is True), 4)
        self.assertEqual(sum(1 for e in hb if "heartbeat_flag" in e["reported_null"]), 4)   # 원천이 null 로 줬다
        self.assertEqual(len(_of(evs, "llm.response")), 1)             # 하위 에이전트의 모형 호출은 없다
        self.assertEqual(len(_of(evs, "tool.start")), 2)               # 주 에이전트의 Bash · Task 만


@unittest.skipUnless((SENSOR / "llmsensor").is_dir(), "옆에 ../Sensor 가 없다")
class SensorSeesTheFixes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(SENSOR))

    def test_same_records_and_limited_state(self):
        """얼린 Sensor 수집기 출력(tests/golden/actions_*.json, D1 · D2 고친 뒤 · 지우기 전)과 같고, State 가 429 를 본다."""
        from llmsensor.state import StateEngine, from_telemetry
        g = pathlib.Path(__file__).resolve().parent / "golden"
        key = lambda r: (r["kind"], r.get("tool_index", r.get("call_index", -1)))
        with tempfile.TemporaryDirectory() as d:
            ours = to_sensor_records(from_cc_jsonl(_write(d, "s.jsonl", SESSION), "x", Hasher(KEY)))
            stream = to_sensor_records(from_cc_stream(_write(d, "a.stream.jsonl", STREAM), "s", Hasher(KEY)))
        for got, name in ((ours, "actions_cc_jsonl"), (stream, "actions_cc_stream")):
            want = json.loads((g / f"{name}.json").read_text(encoding="utf-8"))
            self.assertEqual(sorted(got, key=key), sorted(want, key=key), name)
        E = StateEngine().ingest_all(from_telemetry(ours))
        st = {n: s.value for (_, n), s in E.current.items()}
        self.assertEqual(st.get("rate_limit_state"), "LIMITED")                # 전에는 UNKNOWN
        self.assertNotEqual(st.get("runtime_reliability"), "NO_FAILURE_OBSERVED")   # 전에는 거절이 있는데 '실패 없음'


if __name__ == "__main__":
    unittest.main()
