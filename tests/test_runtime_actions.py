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


QUOTA = {"status": "rejected", "rateLimitType": "five_hour", "overageStatus": "rejected",
         "overageDisabledReason": "out_of_credits", "unifiedRateLimitFallbackAvailable": False}
SESSION = [
    {"type": "queue-operation", "operation": "enqueue", "timestamp": ts(1), "content": "go"},
    {"type": "user", "timestamp": ts(2), "turnOrigin": "human", "turnPosition": {"promptIndex": 1, "turnIndex": 1},
     "message": {"role": "user", "content": "go"}},
    {"type": "assistant", "timestamp": ts(3), "message": {"id": "m1", "model": "claude-x", "usage": {
        "input_tokens": 10, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "output_tokens": 3},
        "content": [{"type": "text", "text": "hi"}]}},
    # D2: 429 -- 런타임이 끼운 API 오류 줄(모형 호출이 아니다)
    {"type": "assistant", "timestamp": ts(4), "isApiErrorMessage": True, "apiErrorStatus": 429, "error": "rate_limit",
     "quotaLimits": QUOTA, "message": {"id": "e1", "model": "<synthetic>", "usage": {"input_tokens": 0, "output_tokens": 0},
                                       "content": [{"type": "text", "text": "API Error: rate limit"}]}},
    {"type": "assistant", "timestamp": ts(5), "message": {"id": "s1", "model": "<synthetic>", "usage": {},
                                                         "content": [{"type": "text", "text": "No response requested."}]}},
    {"type": "queue-operation", "operation": "enqueue", "timestamp": ts(6), "content": "또"},
    {"type": "queue-operation", "operation": "remove", "reason": "absorbed_mid_turn", "timestamp": ts(7)},
    # D4: 압축
    {"type": "system", "subtype": "compact_boundary", "timestamp": ts(8),
     "compactMetadata": {"trigger": "auto", "preTokens": 783484, "postTokens": 7209, "durationMs": 69703}},
    {"type": "system", "subtype": "stop_hook_summary", "timestamp": ts(9), "hookCount": 1, "preventedContinuation": False},
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
        self.assertEqual(len(_of(self.evs, "input.received")), 2)
        self.assertEqual(len(_of(self.evs, "turn.start")), 1)         # 흡수된 입력은 새 차례를 열지 않았다

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
