import unittest

from telemetry import MemorySink, Recorder
from telemetry.event import check
from telemetry.usage import otel_usage


class Clock:
    def __init__(self):
        self.t = 1_000.0

    def __call__(self):
        return self.t


def rec():
    clk = Clock()
    s = MemorySink()
    return Recorder("r17", s, source="inproc:test", wall=clk, mono=clk), s, clk


class Tools(unittest.TestCase):
    def test_result_given(self):
        r, s, clk = rec()
        with r.tool("Bash", {"command": "make all"}, call_index=0) as t:
            clk.t += 250
            t.result(exit_code=2, is_error=True, output="boom")
        st, en = s.events
        self.assertEqual((st["type"], en["type"], st["data"]["tool_head"]), ("tool.start", "tool.end", "Bash:make"))
        self.assertEqual((en["data"]["elapsed_ms"], en["data"]["exit_code"], en["data"]["output_chars"]), (250, 2, 4))
        self.assertEqual([check(e) for e in s.events], [[], []])

    def test_no_result_is_unobserved_not_success(self):
        r, s, _ = rec()
        with r.tool("Read", {"file_path": "/a"}):
            pass
        self.assertIn("is_error", s.events[-1]["unobserved"])

    def test_exception_is_observed_and_reraised(self):
        r, s, _ = rec()
        with self.assertRaises(TimeoutError):
            with r.tool("Bash", {"command": "sleep 9"}):
                raise TimeoutError("secret message")
        d = s.events[-1]["data"]
        self.assertEqual((d["exception"], d["is_error"]), ("TimeoutError", True))
        self.assertNotIn("secret", str(s.events))                     # 메시지는 남기지 않는다
        self.assertIsNone(d["timed_out"])                              # 예외 이름을 시간 초과 판정으로 바꾸지 않는다

    def test_executor_may_declare_its_own_timeout(self):
        r, s, _ = rec()
        with r.tool("Bash", {"command": "sleep 9"}) as t:
            t.result(timed_out=True)                                  # 실행기 스스로 끊었다 -- 선언
        self.assertTrue(s.events[-1]["data"]["timed_out"])


class Llm(unittest.TestCase):
    def test_response_usage_normalised(self):
        r, s, _ = rec()
        r.llm_response(0, "openai", usage={"prompt_tokens": 1200, "prompt_tokens_details": {"cached_tokens": 200},
                                           "completion_tokens": 430}, status_code=200, elapsed_ms=1840)
        d = s.events[-1]["data"]
        self.assertEqual((d["input_tokens"], d["cache_read_input_tokens"], d["output_tokens"]), (1000, 200, 430))
        self.assertIn("cache_creation_input_tokens", s.events[-1]["unobserved"])
        self.assertEqual(otel_usage(d), {"gen_ai.usage.cache_read.input_tokens": 200, "gen_ai.usage.output_tokens": 430})
        r.llm_response(1, "gemini", usage={"prompt_token_count": 100, "cached_content_token_count": 40,
                                           "candidates_token_count": 10, "thoughts_token_count": 5})
        d = s.events[-1]["data"]
        self.assertEqual((d["input_tokens"], d["output_tokens"], d["thinking_tokens"]), (60, 15, 5))

    def test_error_is_translated_not_judged(self):
        r, s, _ = rec()
        r.llm_error(0, "anthropic", 429, {"error": {"type": "rate_limit_error"}}, {"Retry-After": "7"}, attempt=2)
        d = s.events[-1]["data"]
        self.assertEqual((d["error_code"], d["http_status"], d["provider_code"], d["retry_after_ms"], d["attempt"]),
                         ("RATE_LIMITED", 429, "rate_limit_error", 7000, 2))
        r.llm_error(0, "gemini", 504, {"error": {"status": "DEADLINE_EXCEEDED", "details": [
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "1.5s"}]}})
        d = s.events[-1]["data"]
        self.assertEqual((d["error_code"], d["retry_after_ms"]), ("DEADLINE_EXCEEDED", 1500))
        r.llm_error(0, "openai", 500)
        self.assertEqual(s.events[-1]["data"]["error_code"], "UNKNOWN")      # 표에 없으면 추측하지 않는다


class LlmCall(unittest.TestCase):
    def test_success_measures_elapsed_and_keeps_otel_usage_unsplit(self):
        """정규화된 OTel 꼴(MS canonical): 전체 입력만 있다 -- 캐시 밖 입력을 지어내지 않는다."""
        r, s, clk = rec()
        with r.llm_call(0, "claude", "m", prompt_chars=900) as c:
            clk.t += 1840
            c.response(usage={"input_tokens": 1200, "cached_input_tokens": 200, "output_tokens": 430},
                       usage_format="otel", finish_reason="stop", model="m")
        req, resp = s.events
        self.assertEqual((req["type"], req["data"]["prompt_chars"]), ("llm.request", 900))
        d = resp["data"]
        self.assertEqual((d["total_input_tokens"], d["cache_read_input_tokens"], d["output_tokens"], d["elapsed_ms"]),
                         (1200, 200, 430, 1840))
        self.assertIn("input_tokens", resp["unobserved"])
        self.assertEqual(d["stop_reason"], "stop")                    # OTel 이름으로 받아 같은 칸에
        self.assertEqual(otel_usage(d)["gen_ai.usage.input_tokens"], 1200)
        self.assertEqual([check(e) for e in s.events], [[], []])

    def test_error_keeps_status_and_type_not_message(self):
        class ProviderError(RuntimeError):
            def __init__(self, msg, status=None, body=None):
                super().__init__(msg)
                self.status, self.body = status, body
        r, s, clk = rec()
        with self.assertRaises(ProviderError):
            with r.llm_call(1, "claude", table="anthropic"):
                clk.t += 30
                raise ProviderError("HTTP 429: secret body", 429, {"error": {"type": "rate_limit_error"}})
        d = s.events[-1]["data"]
        self.assertEqual((d["exception"], d["http_status"], d["provider_code"], d["error_code"], d["elapsed_ms"]),
                         ("ProviderError", 429, "rate_limit_error", "RATE_LIMITED", 30))
        self.assertNotIn("secret", str(s.events))

    def test_error_without_status_is_not_translated(self):
        r, s, _ = rec()
        with self.assertRaises(ConnectionError):
            with r.llm_call(0, "sim"):
                raise ConnectionError("down")
        e = s.events[-1]
        self.assertEqual(e["data"]["exception"], "ConnectionError")
        self.assertIn("error_code", e["unobserved"])                 # 볼 것이 없었다 -- UNKNOWN 이라고 번역하지 않는다

    def test_no_response_given_emits_only_request(self):
        r, s, _ = rec()
        with r.llm_call(0, "sim"):
            pass
        self.assertEqual([e["type"] for e in s.events], ["llm.request"])

    def test_run_end_links_decision_by_id(self):
        r, s, _ = rec()
        r.run_end(decision_ref="dec-0123456789abcdef", terminal_reason="executed")
        self.assertEqual(s.events[-1]["data"]["decision_ref"], "dec-0123456789abcdef")


class ClosedLoop(unittest.TestCase):
    def test_action_result_returns_to_l0(self):
        """Action 의 결과는 다시 Telemetry 로. 결정의 **내용**은 없고 id 만 잇는다."""
        r, s, clk = rec()
        with r.action("RETURN", decision_ref="dc-abc", target="/fleet/drone7") as a:
            clk.t += 90
            a.result(status_code=200)
        disp, res = s.events
        self.assertEqual((disp["data"]["action_ref"], res["data"]["action_ref"]), ("r17/a0", "r17/a0"))
        self.assertEqual((disp["data"]["decision_ref"], res["data"]["elapsed_ms"]), ("dc-abc", 90))
        self.assertTrue(disp["data"]["target"].startswith("#"))
        self.assertIn("is_error", res["unobserved"])

    def test_external_action_ref_is_carried(self):
        """CMD-T16: 실행기의 command_id 를 그대로 싣는다 -- L0 에서 명령 -> 의도 -> 결정으로 거슬러 갈 수 있게."""
        r, s, _ = rec()
        with r.action("RETURN", decision_ref="dec-0123456789abcdef", action_ref="cmd-89abcdef01234567") as a:
            a.result(is_error=False)
        disp, res = s.events
        self.assertEqual((disp["data"]["action_ref"], res["data"]["action_ref"]),
                         ("cmd-89abcdef01234567", "cmd-89abcdef01234567"))
        self.assertEqual([check(e) for e in s.events], [[], []])
        with r.action("HOLD"):                                         # 안 주면 지금과 같다 -- 밖의 ref 가 번호를 먹지 않는다
            pass
        self.assertEqual(s.events[-1]["data"]["action_ref"], "r17/a0")

    def test_sequential_repeat_of_same_ref_is_recorded(self):
        """같은 명령을 차례로 다시 실행 -- 둘 다 적는다(되풀이는 관측, 해석은 위층)."""
        r, s, _ = rec()
        for code in (503, 200):
            with r.action("RETURN", action_ref="cmd-x") as a:
                a.result(status_code=code)
        self.assertEqual([(e["type"], e["data"]["action_ref"]) for e in s.events],
                         [("action.dispatch", "cmd-x"), ("action.result", "cmd-x")] * 2)

    def test_overlapping_same_ref_refused_before_any_event(self):
        """결과 전에 같은 ref 를 또 열면 짝을 지을 수 없다 -- 사건을 내기 전에 거절하고, 먼저 연 것은 그대로 닫힌다."""
        r, s, _ = rec()
        with r.action("RETURN", action_ref="cmd-x"):
            with self.assertRaises(ValueError):
                with r.action("RETURN", action_ref="cmd-x"):
                    pass
            self.assertEqual([e["type"] for e in s.events], ["action.dispatch"])
        self.assertEqual([e["type"] for e in s.events], ["action.dispatch", "action.result"])
        with r.action("RETURN", action_ref="cmd-x"):                  # 닫힌 뒤에는 다시 연다
            pass
        with r.action("A", action_ref="r17/a0"):                       # 지은 ref 와 겹쳐도 같은 규칙
            with self.assertRaises(ValueError):
                with r.action("B"):
                    pass

    def test_exception_closes_the_ref(self):
        r, s, _ = rec()
        with self.assertRaises(RuntimeError):
            with r.action("RETURN", action_ref="cmd-x"):
                raise RuntimeError("boom")
        self.assertEqual(s.events[-1]["data"]["exception"], "RuntimeError")
        with r.action("RETURN", action_ref="cmd-x"):
            pass

    def test_bad_action_ref_refused(self):
        r, s, _ = rec()
        for bad in ("", 7, b"cmd"):
            with self.assertRaises(ValueError):
                with r.action("RETURN", action_ref=bad):
                    pass
        self.assertEqual(s.events, [])

    def test_heartbeat_counts_per_emitter(self):
        r, s, _ = rec()
        for w in ("a", "b", "a"):
            r.heartbeat(w)
        self.assertEqual([(e["data"]["emitter"], e["data"]["beat"]) for e in s.events], [("a", 0), ("b", 0), ("a", 1)])
        self.assertEqual([e["seq"] for e in s.events], [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
