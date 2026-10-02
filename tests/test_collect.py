import json
import os
import pathlib
import sys
import tempfile
import unittest

from telemetry.collect import from_cc_jsonl, from_cc_stream, from_sweagent
from telemetry.compat import to_sensor_records
from telemetry.event import check
from telemetry.hashing import Hasher
from tests.fixtures import COST, SESSION, write_session, write_stream, write_traj

SENSOR = pathlib.Path(__file__).resolve().parents[2] / "Sensor"
KEY = b"fixed-key-for-tests"


def _of(evs, type):
    return [e for e in evs if e["type"] == type]


class CCJsonl(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.p = os.path.join(self.d.name, "s.jsonl")
        write_session(self.p, SESSION, COST)
        self.evs = from_cc_jsonl(self.p, "x", Hasher(KEY))

    def tearDown(self):
        self.d.cleanup()

    def test_every_event_is_well_formed(self):
        self.assertEqual([check(e) for e in self.evs], [[]] * len(self.evs))
        self.assertEqual([e["seq"] for e in self.evs], list(range(len(self.evs))))

    def test_facts_not_judgements(self):
        ends = _of(self.evs, "tool.end")
        self.assertEqual([e["data"]["is_error"] for e in ends], [True, True, False, False, False])
        # Read 는 문구를 모른다 -> 못 봄. 인용한 문구는 시간 초과가 아니다(D1 거짓 양성). 구조화 칸이 있으면 시간 초과(D1 거짓 음성)
        self.assertEqual([e["data"]["timed_out"] for e in ends], [False, True, None, False, True])
        bg = ends[4]["data"]
        self.assertEqual((bg["declared_timeout_ms"], bg["moved_to_background"], bg["background_task_ref"]),
                         (600000, True, "bg42"))
        self.assertIn("moved_to_background", ends[1]["unobserved"])      # 칸이 없었다 -- '안 옮겼다' 가 아니다
        self.assertEqual(ends[0]["data"]["reported_duration_ms"], 1500)
        self.assertIn("interrupted", ends[1]["reported_null"])                       # 원천이 null 로 줬다
        self.assertIn("interrupted", ends[2]["unobserved"])

    def test_start_without_end_is_kept(self):
        """결과가 안 온 도구: tool.start 는 있고 tool.end 는 없다. 지어내지 않는다 -- 그 빈자리가 liveness 의 증거다."""
        starts = {e["data"]["tool_index"] for e in _of(self.evs, "tool.start")}
        ends = {e["data"]["tool_index"] for e in _of(self.evs, "tool.end")}
        self.assertEqual(starts - ends, {5})

    def test_targets_are_hashed(self):
        heads = [e["data"]["tool_head"] for e in _of(self.evs, "tool.start")]
        self.assertEqual(heads[0], "Bash:make")                       # cd 를 건너뛴 맨 프로그램 이름
        self.assertTrue(heads[2].startswith("Read:#"))
        self.assertNotIn("secret", str(self.evs))                    # 경로 글은 원장에 없다

    def test_sidechain_excluded_and_snapshot_is_a_snapshot(self):
        self.assertFalse([e for e in _of(self.evs, "llm.response") if str(e["data"]["response_id"]).startswith("side")])
        snap = _of(self.evs, "run.snapshot")
        self.assertEqual(len(snap), 1)
        self.assertEqual((snap[0]["data"]["cost_usd"], snap[0]["data"]["reported_input_tokens"]), (0.12, 3000))
        self.assertIsNotNone(snap[0]["at"])
        self.assertFalse(_of(self.evs, "run.end"))                   # 끝을 보지 못했다

    def test_reported_null_usage(self):
        txt = [e for e in _of(self.evs, "llm.response") if e["data"]["stop_reason"] == "end_turn"][0]
        self.assertIn("cache_read_input_tokens", txt["reported_null"])
        self.assertEqual(txt["data"]["thinking_duration_ms"], 40)


class CCStream(unittest.TestCase):
    def test_stream(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.stream.jsonl")
            write_stream(p)
            evs = from_cc_stream(p, "s", Hasher(KEY))
        self.assertEqual([check(e) for e in evs], [[]] * len(evs))
        m = _of(evs, "llm.response")
        self.assertEqual(len(m), 1)                                   # 하위 에이전트 줄은 뺐다
        m = m[0]["data"]
        self.assertEqual((m["output_tokens"], m["thinking_tokens"], m["stream_chunks"], m["first_chunk_ms"],
                          m["stream_thinking_estimate"], m["stop_reason"], m["cache_creation_1h_input_tokens"]),
                         (30, 12, 2, 50, 42, "tool_use", 400))
        rl = _of(evs, "provider.rate_limit")[0]
        self.assertEqual((rl["at"], rl["data"]["declared_status"], rl["data"]["utilization"]), (220, "allowed_warning", 0.81))
        self.assertEqual(len(_of(evs, "provider.rate_limit")), 2)    # 사건마다 따로 -- 마지막 값으로 덮지 않는다
        lim = _of(evs, "runtime.limits")
        self.assertEqual([e["data"]["autocompact_threshold"] for e in lim], [160000, None])
        self.assertIn("max_output_tokens", lim[1]["reported_null"])
        end = _of(evs, "run.end")[0]
        self.assertIn("api_error_status", end["reported_null"])      # null 로 줬다 = 오류 보고 없음
        self.assertIn("ttft_ms", end["unobserved"])                   # 키가 없었다 = 못 봄
        self.assertEqual(end["data"]["permission_denials"], 2)


class SweAgent(unittest.TestCase):
    def test_traj(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.traj.gz")
            write_traj(p)
            evs = from_sweagent(p, "w", Hasher(KEY))
        self.assertEqual([check(e) for e in evs], [[]] * len(evs))
        self.assertTrue(all(e["at"] is None and e["time_base"] is None for e in evs))     # 시각이 없다 -- 순서는 seq
        names = [e["data"]["tool_name"] for e in _of(evs, "tool.start")]
        self.assertEqual(names[0], "ls")
        self.assertTrue(names[1].startswith("#"))                     # 경로는 해시
        ends = _of(evs, "tool.end")
        self.assertTrue(all("is_error" in e["unobserved"] for e in ends))   # 오류 깃발이 없는 원천 -- '성공' 이 아니다
        end = _of(evs, "run.end")[0]
        self.assertEqual((end["data"]["terminal_reason"], end["data"]["tokens_sent"]), ("submitted", 1000))
        self.assertIn("tokens_received", end["reported_null"])


GOLDEN = pathlib.Path(__file__).resolve().parent / "golden"


def golden(name):
    return json.loads((GOLDEN / f"{name}.json").read_text(encoding="utf-8"))


def _key(r):
    return (r["kind"], r["tool_index"] if r["kind"] == "tool_call" else r.get("call_index", -1))


class GoldenEquivalence(unittest.TestCase):
    """L0 원장에서 되지은 꼴 v3 레코드가 **지우기 전 Sensor 수집기의 출력**과 같다(CMD-T9).
    tests/golden/*.json 은 Sensor 수집기(Sensor f6f02fc)가 같은 고정 자료 · 같은 열쇠로 낸 것을 얼린 것이다.
    이제 비교할 '원래 수집기' 가 없으므로 이 파일들이 그 자리를 맡는다 -- 고치지 말 것(바꾸려면 까닭을 적고 새 판으로)."""

    def _same(self, ours, name):
        self.assertEqual(sorted(ours, key=_key), sorted(golden(name), key=_key))

    def test_cc_jsonl(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.jsonl")
            write_session(p, SESSION, COST)
            self._same(to_sensor_records(from_cc_jsonl(p, "x", Hasher(KEY))), "cc_jsonl_cost")
            write_session(p, SESSION)                                 # cost-state 없음 -> run 레코드 없음
            self._same(to_sensor_records(from_cc_jsonl(p, "x", Hasher(KEY))), "cc_jsonl_nocost")

    def test_cc_stream(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.stream.jsonl")
            write_stream(p)
            self._same(to_sensor_records(from_cc_stream(p, "s", Hasher(KEY))), "cc_stream")

    def test_sweagent(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.traj.gz")
            write_traj(p)
            self._same(to_sensor_records(from_sweagent(p, "w", Hasher(KEY))), "sweagent")


@unittest.skipUnless((SENSOR / "llmsensor").is_dir(), "옆에 ../Sensor 가 없다")
class SensorSitsOnL0(unittest.TestCase):
    """Sensor 의 이음매(llmsensor.telemetry.collect)와 State 층이 L0 위에 그대로 앉는다."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(SENSOR))

    def test_seam_is_l0_and_records_pass_v4(self):
        from llmsensor.telemetry import collect as S
        from llmsensor.telemetry.schema import check as v4check
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.jsonl")
            write_session(p, SESSION, COST)
            ours = to_sensor_records(from_cc_jsonl(p, "x", Hasher(KEY)))
            seam = S.from_cc_jsonl(p, "x", S.Hasher(KEY))
        self.assertEqual(sorted(seam, key=_key), sorted(ours, key=_key))
        self.assertEqual([v4check(r) for r in ours], [[]] * len(ours))

    def test_sensor_state_engine_sits_on_l0(self):
        """L0 -> compat -> Sensor 의 State 층(정규화 묶음)이 얼린 출력과 같은 관측을 낸다."""
        from llmsensor.state.normalize import from_telemetry
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.jsonl")
            write_session(p, SESSION, COST)
            ours = from_telemetry(to_sensor_records(from_cc_jsonl(p, "x", Hasher(KEY))))
        theirs = from_telemetry(golden("cc_jsonl_cost"))
        flat = lambda bs: [(b.record_id, [(o.field, o.value, o.reported_null) for o in b.observations]) for b in bs]
        self.assertEqual(flat(ours), flat(theirs))
        self.assertTrue(ours)


if __name__ == "__main__":
    unittest.main()
