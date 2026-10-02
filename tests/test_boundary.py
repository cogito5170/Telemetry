"""L0 의 경계 -- Telemetry 는 판단하지 않는다. 이 파일이 그 경계를 붙든다."""
import ast
import os
import pathlib
import tempfile
import unittest

from telemetry import Recorder, ledger
from telemetry.catalog import EVENTS, F, FORBIDDEN, check_catalog, name_problems
from telemetry.event import make
from telemetry.ledger import JsonlSink

PKG = pathlib.Path(__file__).resolve().parent.parent / "telemetry"


class Vocabulary(unittest.TestCase):
    def test_catalog_has_no_interpretation(self):
        self.assertEqual(check_catalog(), [])

    def test_interpretive_fields_are_refused(self):
        """사용자 예: health · should_retry · policy · risk · decision 은 이미 해석이나 정책이다."""
        for name in ("health", "should_retry", "policy", "risk", "decision", "token_state", "latency_ok",
                     "timeout_exceeded", "quality_score", "is_slow", "loop_detected"):
            bad = {"tool.end": dict(EVENTS["tool.end"], **{name: F("str", "measured")})}
            self.assertTrue(check_catalog(bad), name)

    def test_our_thresholds_are_refused_source_declared_ones_are_not(self):
        """'timeout_threshold = 30 s' 는 Sensor 설정이다. 런타임이 **스스로** 선언한 한도(context_window)는 사실이다."""
        self.assertTrue(name_problems("timeout_threshold_ms", F("num", "measured")))
        self.assertTrue(name_problems("latency_slo_ms", F("num", "reported")))
        self.assertEqual(name_problems("autocompact_threshold", F("int", "declared")), [])
        self.assertEqual(name_problems("decision_ref", F("str", "ref")), [])        # 결정의 id 만 -- 내용이 아니다
        self.assertTrue(name_problems("decision_ref", F("str", "reported")))
        self.assertTrue(name_problems("decision", F("str", "ref")))

    def test_event_types_are_occurrences(self):
        for et in EVENTS:
            self.assertFalse([w for w in et.replace(".", "_").split("_") if w in FORBIDDEN], et)

    def test_closed_form_refuses_unknown_fields(self):
        with self.assertRaises(KeyError):
            make("tool.end", "r", 0, "t", tool_index=0, should_retry=True)
        with self.assertRaises(KeyError):
            make("llm.verdict", "r", 0, "t")


class LayerDirection(unittest.TestCase):
    def test_l0_imports_no_upper_layer(self):
        """L0 는 아무것도 위로 보지 않는다 -- llmsensor · ms · dc 를 import 하지 않는다."""
        upper = {"llmsensor", "ms", "dc"}
        for p in PKG.rglob("*.py"):
            for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                mods = ([a.name for a in node.names] if isinstance(node, ast.Import)
                        else [node.module or ""] if isinstance(node, ast.ImportFrom) and node.level == 0 else [])
                for m in mods:
                    self.assertNotIn(m.split(".")[0], upper, f"{p.name}: {m}")

    def test_stdlib_only(self):
        import sys
        std = set(sys.stdlib_module_names) | {"telemetry"}
        for p in PKG.rglob("*.py"):
            for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        self.assertIn(a.name.split(".")[0], std, f"{p.name}: {a.name}")
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    self.assertIn((node.module or "").split(".")[0], std, f"{p.name}: {node.module}")


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class TimeoutIsASensorQuestion(unittest.TestCase):
    """사용자의 예 그대로: tool_start · tool_end · elapsed = 31,200 ms. TIMEOUT 이라는 판단은 L0 에 없다.
    문턱을 30 s 에서 60 s 로 바꿔도 **원장은 그대로** 다시 읽힌다."""

    def test_same_ledger_two_thresholds(self):
        clk = Clock()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ledger.jsonl")
            rec = Recorder("r17", JsonlSink(path), mono=clk, wall=clk)
            with rec.tool("Bash", {"command": "pytest -q"}) as t:
                clk.t += 31_200
                t.result(exit_code=0, is_error=False, output="1 passed")
            before = pathlib.Path(path).read_bytes()
            events = ledger.read(path)

            def timeout_observed(evs, threshold_ms):     # L1 의 일 -- 시험 안에만 있다
                return [e["data"]["tool_index"] for e in evs
                        if e["type"] == "tool.end" and e["data"]["elapsed_ms"] is not None
                        and e["data"]["elapsed_ms"] > threshold_ms]
            self.assertEqual(timeout_observed(events, 30_000), [0])
            self.assertEqual(timeout_observed(events, 60_000), [])
            self.assertEqual(pathlib.Path(path).read_bytes(), before)
        end = events[-1]
        self.assertEqual(end["data"]["elapsed_ms"], 31_200)
        self.assertIn("timed_out", end["unobserved"])       # 실행기가 선언하지 않았다 -- '아니다' 가 아니라 '못 봄'
        self.assertEqual(end["data"]["exit_code"], 0)


if __name__ == "__main__":
    unittest.main()
