"""프로세스 안 계측 -- 실행 중인 코드(MS 런타임 · 도구 실행기 · 행동 실행기)가 L0 사건을 바로 낸다.

    rec = Recorder("r17", JsonlSink("ledger.jsonl"), source="inproc:ms")
    rec.llm_request(0, "anthropic", "claude-…")
    rec.llm_response(0, "anthropic", usage=resp["usage"], status_code=200, elapsed_ms=1840, stop_reason="end_turn")
    with rec.tool("Bash", {"command": "make"}) as t:     # tool.start, 끝나면 tool.end(elapsed_ms 는 단조 시계로 잰다)
        p = subprocess.run(...)
        t.result(exit_code=p.returncode, is_error=p.returncode != 0, output=p.stdout)
    rec.heartbeat("worker-1")
    with rec.action("RETURN", decision_ref=dc_id) as a:  # action.dispatch / action.result -- 결과가 다시 L0 로(닫힌 고리)
        ...

**판단하지 않는다.** `tool()` 은 시간 초과를 정하지 않는다 -- 경과 시간을 잴 뿐이다. 실행기가 스스로 시간 초과로 끊었으면
그 사실을 `timed_out=True`(선언)로 넘긴다. 예외가 나면 예외 종류 이름만 적고(`exception`), 메시지는 남기지 않는다.
결과를 넘기지 않고 블록이 끝나면 is_error 는 '못 봄' 이다 -- '오류 없음' 으로 메우지 않는다.
"""
from __future__ import annotations

import itertools
import json
import time
from contextlib import contextmanager

from .errors import translate
from .event import make
from .hashing import Hasher, default_hasher, target_hash, tool_head, tool_sig
from .usage import l0_usage


class Recorder:
    def __init__(self, run_id: str, sink, source: str = "inproc", wall=None, mono=None, hasher: "Hasher | None" = None):
        self.run_id, self.sink, self.source = run_id, sink, source
        self.wall = wall or (lambda: time.time() * 1000)            # 사건 시각(unix ms)
        self.mono = mono or (lambda: time.monotonic() * 1000)       # 경과 시간만 이것으로
        self.h = hasher or default_hasher()
        self._seq = itertools.count()
        self._tool = itertools.count()
        self._act = itertools.count()
        self._beats: dict = {}

    def emit(self, type: str, reported_null=(), **data) -> dict:
        ev = make(type, self.run_id, next(self._seq), self.source, at=self.wall(), time_base="unix_ms",
                  reported_null=reported_null, **data)
        self.sink.write(ev)
        return ev

    # ── 실행 ──
    def run_start(self, model=None, provider=None):
        return self.emit("run.start", model=model, provider=provider)

    def run_end(self, **reported):
        return self.emit("run.end", **reported)

    # ── 모형 호출 ──
    def llm_request(self, call_index: int, provider: str, model=None, attempt: int = 0, prompt_chars=None):
        return self.emit("llm.request", call_index=call_index, provider=provider, model=model, attempt=attempt,
                         prompt_chars=prompt_chars)

    def llm_response(self, call_index: int, provider: str, usage=None, usage_format: "str | None" = None, **kw):
        """usage_format: usage 의 꼴(anthropic · openai · gemini · otel). 없으면 provider 이름을 꼴로 쓴다."""
        vals, nulls = l0_usage(usage_format or provider, usage or {})
        return self.emit("llm.response", nulls, call_index=call_index, provider=provider, **vals, **kw)

    def llm_error(self, call_index: int, provider: str, http_status=None, body=None, headers=None, attempt: int = 0,
                  elapsed_ms=None, exception=None, table: "str | None" = None):
        """table: 오류 대응표 이름(anthropic · openai · gemini). 없으면 provider. 상태 · 본문이 없으면 번역하지 않는다(못 봄)."""
        t = translate(table or provider, http_status, body, headers)
        nothing = http_status is None and not body
        return self.emit("llm.error", call_index=call_index, attempt=attempt, provider=provider,
                         http_status=t.http_status, provider_code=t.provider_code,
                         error_code=None if nothing else t.error_code.value,
                         error_code_source=None if nothing else t.source, retry_after_ms=t.retry_after_ms,
                         exception=exception, elapsed_ms=elapsed_ms)

    @contextmanager
    def llm_call(self, call_index: int, provider: str, model=None, attempt: int = 0, prompt_chars=None,
                 table: "str | None" = None):
        """llm.request 를 내고, 블록 안에서 `c.response(...)` 를 부르면 llm.response, 예외가 나면 llm.error(예외 종류 ·
        예외에 status · body 가 붙어 있으면 그것)를 낸다. 경과 시간은 단조 시계로 잰다. 예외는 다시 던진다."""
        self.llm_request(call_index, provider, model, attempt, prompt_chars)
        h = _Call()
        t0 = self.mono()
        try:
            yield h
        except BaseException as e:
            self.llm_error(call_index, provider, getattr(e, "status", None), getattr(e, "body", None),
                           getattr(e, "headers", None), attempt, self.mono() - t0, type(e).__name__, table)
            raise
        else:
            if h.kw is not None:
                self.llm_response(call_index, provider, elapsed_ms=self.mono() - t0, **h.kw)

    # ── 도구 ──
    @contextmanager
    def tool(self, name: str, inp: "dict | None" = None, call_index=None):
        idx = next(self._tool)
        inp = inp or {}
        self.emit("tool.start", call_index=call_index, tool_index=idx, tool_name=name,
                  tool_head=tool_head(name, inp, self.h), tool_sig=tool_sig(name, inp, self.h),
                  tool_input_chars=len(json.dumps(inp, ensure_ascii=False)))
        h = _Outcome()
        t0 = self.mono()
        try:
            yield h
        except BaseException as e:
            h.vals.setdefault("exception", type(e).__name__)
            h.vals.setdefault("is_error", True)       # 런타임(파이썬)이 예외로 오류를 알렸다 -- 관측이다
            raise
        finally:
            self.emit("tool.end", tool_index=idx, elapsed_ms=self.mono() - t0, **h.vals)

    # ── 생존 · 의존 ──
    def heartbeat(self, emitter: str):
        n = self._beats.get(emitter, 0)
        self._beats[emitter] = n + 1
        return self.emit("heartbeat", emitter=emitter, beat=n)

    def dependency_probe(self, target: str, status_code=None, error_code=None, elapsed_ms=None):
        return self.emit("dependency.probe", target=target_hash(target, self.h), status_code=status_code,
                         error_code=error_code, elapsed_ms=elapsed_ms)

    # ── 행동 -- 결정의 내용은 적지 않는다. 무엇이 실행됐고 어떻게 끝났나만 ──
    @contextmanager
    def action(self, action_type: str, decision_ref=None, target=None):
        ref = f"{self.run_id}/a{next(self._act)}"
        self.emit("action.dispatch", action_ref=ref, decision_ref=decision_ref, action_type=action_type,
                  target=target_hash(target, self.h))
        h = _Outcome()
        t0 = self.mono()
        try:
            yield h
        except BaseException as e:
            h.vals.setdefault("exception", type(e).__name__)
            h.vals.setdefault("is_error", True)
            raise
        finally:
            self.emit("action.result", action_ref=ref, elapsed_ms=self.mono() - t0, **h.vals)


class _Call:
    def __init__(self):
        self.kw = None

    def response(self, **kw):
        self.kw = kw


class _Outcome:
    """블록 안에서 결과를 넘기는 손잡이. 넘긴 것만 사건에 들어간다."""

    def __init__(self):
        self.vals: dict = {}

    def result(self, output: "str | None" = None, **reported):
        if output is not None:
            reported["output_chars"] = len(output)
        self.vals.update({k: v for k, v in reported.items() if v is not None})
