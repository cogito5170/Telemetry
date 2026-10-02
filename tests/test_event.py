import os
import tempfile
import unittest

from telemetry import ledger
from telemetry.event import check, make, observed


class Envelope(unittest.TestCase):
    def test_unobserved_and_reported_null_are_distinct(self):
        e = make("run.end", "r", 3, "cc_stream", reported_null=["api_error_status"], cost_usd=0.1)
        self.assertEqual(e["id"], "r:3")
        self.assertIn("api_error_status", e["reported_null"])
        self.assertNotIn("api_error_status", e["unobserved"])
        self.assertIn("ttft_ms", e["unobserved"])
        self.assertTrue(observed(e, "api_error_status"))
        self.assertFalse(observed(e, "ttft_ms"))
        self.assertEqual(check(e), [])
        with self.assertRaises(ValueError):
            make("run.end", "r", 0, "s", reported_null=["cost_usd"], cost_usd=1.0)

    def test_check_catches_lies(self):
        e = make("tool.end", "r", 0, "s", tool_index=0, is_error=False)
        bad = dict(e, unobserved=[k for k in e["unobserved"] if k != "exit_code"])
        self.assertTrue(check(bad))                                     # null 인데 어느 목록에도 없다
        bad = dict(e, data=dict(e["data"], is_error="no"))
        self.assertTrue(check(bad))                                     # 형
        bad = dict(e, data=dict(e["data"], output_chars=-1), unobserved=[k for k in e["unobserved"] if k != "output_chars"])
        self.assertTrue(check(bad))                                     # 음수 개수
        self.assertTrue(check(dict(e, id="r:9")))                       # id 는 run_id:seq
        self.assertTrue(check(dict(e, time_base="days")))
        self.assertTrue(check(dict(e, health="BAD")))                   # 봉투도 닫혀 있다
        self.assertEqual(check(e), [])

    def test_zero_is_not_missing(self):
        e = make("llm.response", "r", 0, "s", call_index=0, output_tokens=0)
        self.assertEqual(e["data"]["output_tokens"], 0)
        self.assertNotIn("output_tokens", e["unobserved"])
        self.assertIn("input_tokens", e["unobserved"])

    def test_bool_is_not_a_number(self):
        with self.assertRaises(ValueError):
            make("llm.response", "r", 0, "s", call_index=0, output_tokens=True)


class Ledger(unittest.TestCase):
    def test_roundtrip_and_rejects(self):
        evs = [make("heartbeat", "r", i, "s", at=float(i), time_base="unix_ms", emitter="w", beat=i) for i in range(3)]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "l.jsonl")
            ledger.write(p, evs)
            self.assertEqual(ledger.read(p), evs)
            with open(p, "a") as f:
                f.write('{"type": "heartbeat"}\nnot json\n')
            with self.assertRaises(ValueError):
                ledger.read(p)
            ok, rej = ledger.read_lenient(p)
            self.assertEqual((len(ok), [n for n, _ in rej]), (3, [4, 5]))


if __name__ == "__main__":
    unittest.main()
