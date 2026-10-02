"""원천 -> L0 사건. **원천이 준 값만 옮긴다.** 합산 · 추정 · 해석은 하지 않는다(그것은 L1 Sensor 의 몫이다).

    from_cc_jsonl(path, run_id)    Claude Code 세션 JSONL. 파일 하나 = 실행 하나. 하위 에이전트 줄(isSidechain)은 뺀다
    from_cc_stream(path, run_id)   {"_t": 수집기 단조 ms, "line": stream-json 줄} 들 (Sensor eval/run_claude.py 가 남기는 꼴)
    from_sweagent(path, run_id)    SWE-agent .traj(.gz)

Sensor(llmsensor/telemetry/collect.py, 꼴 v3)의 수집 규칙을 그대로 옮겼다. 다른 점은 꼴뿐이다:
레코드 셋(model_call · tool_call · run) 대신 **사건**(llm.response · tool.start · tool.end · run.end · run.snapshot ·
runtime.limits · provider.rate_limit)이고, 한 원천 줄이 한 관측 시각을 가지면 그 시각이 사건의 `at` 이다.
같은 원장에서 `compat.to_sensor_records` 가 Sensor 꼴 v3 를 그대로 되짓는다(시험이 바이트 단위로 대조한다).

사건 순서(seq): 모형 호출마다 [llm.response, 그 호출이 부른 tool.start …, 그 결과 tool.end …], 그다음 실행 단위 사건을 원천에 나온 차례로.
"""
from __future__ import annotations

import gzip
import json
import re
from datetime import datetime
from pathlib import Path

from ..event import make
from ..hashing import PROGRAM, Hasher, default_hasher, tool_head, tool_sig
from ..usage import l0_usage


def _ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp() * 1000
    except ValueError:
        return None


def _take(src: dict, mapping: dict) -> "tuple[dict, list]":
    """{칸: 원천 키} -> (값들, 원천이 null 로 준 칸들). 키가 없으면 값 없음 + 목록에도 없음(= unobserved)."""
    vals, nulls = {}, []
    for field, key in mapping.items():
        if key in src:
            if src[key] is None:
                nulls.append(field)
            else:
                vals[field] = src[key]
    return vals, nulls


def _text_len(content) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(len(x.get("text", "")) for x in content if isinstance(x, dict) and x.get("type") == "text")
    return 0


TIMEOUT_TEXT = re.compile(r"Command timed out after")    # Claude Code Bash 의 런타임 선언 문구


def _timed_out(tool_name, block) -> "bool | None":
    """런타임이 시간 초과를 **선언**했나(Bash 결과 글의 문구). 다른 도구는 문구를 모르므로 None(못 봄).
    경과 시간을 문턱에 비교하지 않는다 -- 그것은 Sensor 의 일이다."""
    if tool_name != "Bash":
        return None
    c = block.get("content")
    txt = c if isinstance(c, str) else " ".join(x.get("text", "") for x in c if isinstance(x, dict)) \
        if isinstance(c, list) else ""
    return bool(TIMEOUT_TEXT.search(txt))


class _Ledger:
    """한 실행의 모형 호출 · 도구 호출을 모았다가 사건으로 낸다."""

    def __init__(self, run_id, source, time_base, hasher=None):
        self.run_id, self.source, self.tb = run_id, source, time_base
        self.h = hasher or default_hasher()
        self.calls: dict = {}
        self.order: list = []
        self.tools: dict = {}
        self.tool_order: list = []
        self.tail: list = []           # 실행 단위 사건 (줄, type, at, data, nulls)
        self.line = 0                  # 지금 읽는 원천 줄 번호 -- 사건 순서(seq)는 원천에 나온 차례를 따른다

    def call(self, mid):
        if mid not in self.calls:
            self.calls[mid] = {"t_start_ms": None, "t_end_ms": None, "tools": 0, "text": 0, "_line": self.line}
            self.order.append(mid)
        return self.calls[mid]

    def seen(self, c, t):
        if t is None:
            return
        c["t_start_ms"] = t if c["t_start_ms"] is None else min(c["t_start_ms"], t)
        c["t_end_ms"] = t if c["t_end_ms"] is None else max(c["t_end_ms"], t)

    def tool_use(self, mid, block, t):
        c = self.call(mid)
        c["tools"] += 1
        tid = block.get("id") or f"anon{len(self.tool_order)}"
        inp = block.get("input") or {}
        name = block.get("name", "")
        self.tools[tid] = {"start": {"call_index": self.order.index(mid), "tool_name": name,
                                     "tool_head": tool_head(name, inp, self.h), "tool_sig": tool_sig(name, inp, self.h),
                                     "tool_input_chars": len(json.dumps(inp, ensure_ascii=False))},
                           "t_issued": t, "end": None, "line_start": self.line}
        self.tool_order.append(tid)

    def tool_result(self, block, t, extra=None, extra_nulls=()):
        d = self.tools.get(block.get("tool_use_id"))
        if d is None:
            return
        end = {"is_error": bool(block.get("is_error")), "timed_out": _timed_out(d["start"]["tool_name"], block),
               "output_chars": _text_len(block.get("content"))}
        end.update(extra or {})
        d["end"], d["t_result"], d["nulls"], d["line_end"] = end, t, list(extra_nulls), self.line

    def run_event(self, type, at, data, nulls=()):
        self.tail.append((self.line, type, at, data, [k for k in nulls if data.get(k) is None]))

    def events(self) -> "list[dict]":
        """원천에 나온 차례(줄 번호)로 늘어놓는다. 모형 호출은 첫 줄, 도구 시작 · 끝은 그 줄, 실행 단위 사건은 그 줄.
        같은 줄이면 응답 → 도구 시작 → 도구 끝 → 실행 단위 사건."""
        items = []                     # (줄, 등급, 넣은 차례, type, at, nulls, data)

        def put(line, rank, type, at, nulls, data):
            items.append((line, rank, len(items), type, at, nulls, data))
        for i, mid in enumerate(self.order):
            c = self.calls[mid]
            vals = {k: c.get(k) for k in ("model", "t_start_ms", "t_end_ms", "stop_reason", "thinking_duration_ms",
                                          "first_chunk_ms", "stream_chunks", "stream_thinking_estimate")}
            vals.update(c.get("usage") or {})
            nl = set(c.get("unulls") or ())
            if c.get("sr_null"):
                nl.add("stop_reason")
            if c.get("tdm_null"):
                nl.add("thinking_duration_ms")
            vals.update(call_index=i, tool_calls_per_message=c["tools"], output_text_chars=c["text"])
            if isinstance(mid, str):
                vals["response_id"] = mid
            put(c["_line"], 0, "llm.response", c["t_end_ms"], [k for k in nl if vals.get(k) is None], vals)
        for j, tid in enumerate(self.tool_order):
            d = self.tools[tid]
            put(d["line_start"], 1, "tool.start", d["t_issued"], [], dict(tool_index=j, **d["start"]))
            if d["end"] is not None:
                put(d.get("line_end", d["line_start"]), 2, "tool.end", d["t_result"],
                    [k for k in d["nulls"] if d["end"].get(k) is None], dict(tool_index=j, **d["end"]))
        for line, type, at, data, nulls in self.tail:
            put(line, 3, type, at, nulls, data)
        out = []
        for _, _, _, type, at, nulls, data in sorted(items, key=lambda x: x[:3]):
            out.append(make(type, self.run_id, len(out), self.source, at=at, time_base=self.tb,
                            reported_null=nulls, **data))
        return out


def from_cc_jsonl(path, run_id: str, hasher: "Hasher | None" = None) -> "list[dict]":
    L = _Ledger(run_id, "cc_jsonl", "unix_ms", hasher)
    last_ts = None
    with open(path, encoding="utf-8") as f:
        for ln, line in enumerate(f):
            L.line = ln
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if _ts(d.get("timestamp")) is not None:
                last_ts = _ts(d.get("timestamp"))
            if d.get("type") == "cost-state":
                # 세션 끝 합계가 **아니다** -- 그 줄까지의 누적 스냅숏. 자기 시각이 없어 바로 앞 줄의 시각을 쓴다
                mu = d.get("modelUsage") or {}

                def tot(k, mu=mu):
                    return sum(v.get(k) or 0 for v in mu.values()) if mu else None
                L.run_event("run.snapshot", last_ts, {
                    "run_duration_ms": d.get("totalDuration"), "api_duration_ms": d.get("totalAPIDuration"),
                    "api_duration_without_retries_ms": d.get("totalAPIDurationWithoutRetries"),
                    "cost_usd": d.get("totalCostUSD"), "reported_input_tokens": tot("inputTokens"),
                    "reported_output_tokens": tot("outputTokens"),
                    "reported_cache_read_input_tokens": tot("cacheReadInputTokens"),
                    "reported_cache_creation_input_tokens": tot("cacheCreationInputTokens")})
            if d.get("isSidechain"):
                continue
            t = _ts(d.get("timestamp"))
            if d.get("type") == "queue-operation" and d.get("operation") == "enqueue":
                # 런타임이 입력을 받아 줄에 세웠다 -- 차례가 시작되기 전이다(다른 operation 은 아직 옮기지 않는다)
                c = d.get("content")
                L.run_event("input.received", t, {"input_chars": len(c) if isinstance(c, str) else None})
            elif d.get("type") == "system" and d.get("subtype") == "stop_hook_summary":
                # 런타임의 Stop 사건. 훅이 막았으면(preventedContinuation) 차례는 끝나지 않고 이어진다
                v, nl = _take(d, {"stop_hook_count": "hookCount"})
                kind = "turn.continued" if d.get("preventedContinuation") is True else "turn.end"
                L.run_event(kind, t, {"marker": "stop_hook_summary", **v}, nl)
            m = d.get("message")
            if not isinstance(m, dict):
                continue
            content = m.get("content")
            is_input = d.get("type") == "user" and not d.get("isMeta") and (
                isinstance(content, str) or (isinstance(content, list) and content and not any(
                    isinstance(b, dict) and b.get("type") == "tool_result" for b in content)))
            if is_input:
                # 입력이 대화에 들어갔다 -- 차례가 열린다. 글은 길이만
                pos = d.get("turnPosition") if isinstance(d.get("turnPosition"), dict) else {}
                v, nl = _take(pos, {"turn_index": "turnIndex", "prompt_index": "promptIndex"})
                origin = d.get("turnOrigin") or ((d.get("origin") or {}).get("kind") if isinstance(d.get("origin"), dict)
                                                 else None)
                L.run_event("turn.start", t, {**v, "turn_origin": origin, "input_chars": _text_len(content)}, nl)
            if d.get("type") == "assistant" and m.get("id"):
                c = L.call(m["id"])
                L.seen(c, t)
                c["model"] = m.get("model")
                if m.get("usage"):
                    c["usage"], c["unulls"] = l0_usage("anthropic", m["usage"])
                if m.get("stop_reason"):
                    c["stop_reason"] = m["stop_reason"]
                elif "stop_reason" in m:
                    c["sr_null"] = True           # 조각 줄은 null 을 준다 -- 끝까지 값이 안 오면 '보고된 null'
                if d.get("thinkingDurationMs") is not None:
                    c["thinking_duration_ms"] = d["thinkingDurationMs"]
                elif "thinkingDurationMs" in d:
                    c["tdm_null"] = True
                for b in m.get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        L.tool_use(m["id"], b, t)
                    elif isinstance(b, dict) and b.get("type") == "text":
                        c["text"] += len(b.get("text", ""))
            elif d.get("type") == "user" and isinstance(m.get("content"), list):
                tur = d.get("toolUseResult") if isinstance(d.get("toolUseResult"), dict) else {}
                extra, tnull = _take(tur, {"interrupted": "interrupted"})
                if isinstance(tur.get("durationSeconds"), (int, float)):
                    extra["reported_duration_ms"] = tur["durationSeconds"] * 1000
                elif "durationSeconds" in tur:
                    tnull.append("reported_duration_ms")
                for b in m["content"]:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        L.tool_result(b, t, extra, tnull)
    return L.events()


def from_cc_stream(path, run_id: str, hasher: "Hasher | None" = None) -> "list[dict]":
    """줄마다 {"_t": 수집기 단조 ms, "line": 원래 줄}. stream_event 에는 런타임 시각이 없어 _t 를 쓴다."""
    L = _Ledger(run_id, "cc_stream", "monotonic_ms", hasher)
    cur = None
    with open(path, encoding="utf-8") as f:
        rows = [json.loads(x) for x in f if x.strip()]
    for ln, row in enumerate(rows):
        L.line = ln
        t, d = row.get("_t"), row.get("line") or {}
        if row.get("closed") is True:
            # 수집기가 원천 프로세스의 흐름이 닫힌 것을 적었다(EOF · 종료 코드). 이 줄이 없으면 닫힘을 모른다
            rc = row.get("returncode")
            L.run_event("source.closed", t, {"exit_code": rc if isinstance(rc, int) else None})
            continue
        ty = d.get("type")
        if d.get("parent_tool_use_id"):           # 하위 에이전트 사건은 뺀다
            continue
        if ty == "stream_event":
            ev = d.get("event") or {}
            et = ev.get("type")
            if et == "message_start":
                msg = ev.get("message") or {}
                cur = msg.get("id")
                c = L.call(cur)
                L.seen(c, t)
                c["model"] = msg.get("model")
                c["stream_chunks"] = 0
                c["_start"] = t
                c["_start_usage"] = dict(msg.get("usage") or {})   # 캐시 쓰기 5m/1h · server_tool_use 는 여기에만
            elif cur is not None:
                c = L.call(cur)
                L.seen(c, t)
                if et == "content_block_delta":
                    c["stream_chunks"] += 1
                    if c.get("first_chunk_ms") is None and t is not None:
                        c["first_chunk_ms"] = t - c["_start"]
                elif et == "message_delta":
                    if ev.get("usage"):
                        merged = dict(c.get("_start_usage") or {})     # delta 가 최종값, 없는 칸만 start 에서
                        merged.update(ev["usage"])
                        c["usage"], c["unulls"] = l0_usage("anthropic", merged)
                    delta = ev.get("delta") or {}
                    c["stop_reason"] = delta.get("stop_reason")
                    if "stop_reason" in delta and delta["stop_reason"] is None:
                        c["sr_null"] = True
        elif ty == "system" and d.get("subtype") == "init":
            L.run_event("turn.start", t, {})        # claude -p: 프롬프트를 받고 세션을 연 런타임 선언 -- 차례 하나
        elif ty == "system" and d.get("subtype") == "thinking_tokens" and cur is not None:
            L.call(cur)["stream_thinking_estimate"] = d.get("estimated_tokens")
        elif ty == "assistant":
            m = d.get("message") or {}
            mid = m.get("id")
            if mid:
                for b in m.get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        L.tool_use(mid, b, t)
                    elif isinstance(b, dict) and b.get("type") == "text":
                        L.call(mid)["text"] += len(b.get("text", ""))
        elif ty == "user":
            m = d.get("message") or {}
            tur = d.get("tool_use_result") if isinstance(d.get("tool_use_result"), dict) else {}
            for b in m.get("content") or [] if isinstance(m.get("content"), list) else []:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    ex, tn = _take(tur, {"interrupted": "interrupted"})
                    L.tool_result(b, t, ex, tn)
        elif ty == "rate_limit_event":
            info = d.get("rate_limit_info") or {}
            L.run_event("provider.rate_limit", t, {"utilization": info.get("utilization"),
                                                   "declared_status": info.get("status"),
                                                   "declared_threshold": info.get("surpassedThreshold")})
        elif ty == "autocompact_state":
            L.run_event("runtime.limits", t, {"autocompact_threshold": (d.get("value") or {}).get("threshold")})
        elif ty == "result":
            mu = d.get("modelUsage") or {}
            m0 = next(iter(mu.values()), {}) if len(mu) == 1 else {}
            v, n = _take(d, {"run_duration_ms": "duration_ms", "api_duration_ms": "duration_api_ms",
                             "ttft_ms": "ttft_ms", "num_turns": "num_turns", "cost_usd": "total_cost_usd",
                             "terminal_reason": "terminal_reason", "result_subtype": "subtype",
                             "is_error": "is_error", "api_error_status": "api_error_status"})
            if "api_error_status" in v:
                v["api_error_status"] = str(v["api_error_status"])
            if isinstance(d.get("permission_denials"), list):
                v["permission_denials"] = len(d["permission_denials"])
            v3, n3 = _take(d.get("usage") or {}, {
                "reported_input_tokens": "input_tokens", "reported_output_tokens": "output_tokens",
                "reported_cache_read_input_tokens": "cache_read_input_tokens",
                "reported_cache_creation_input_tokens": "cache_creation_input_tokens"})
            if len(mu) == 1:
                v["model"] = next(iter(mu))
            v2, n2 = _take(m0, {"context_window": "contextWindow", "max_output_tokens": "maxOutputTokens"})
            if v2 or n2:
                L.run_event("runtime.limits", t, v2, n2)
            L.run_event("run.end", t, {**v, **v3}, n + n3)
            L.run_event("turn.end", t, {"marker": "result"})
    return L.events()


def from_sweagent(path, run_id: str, hasher: "Hasher | None" = None) -> "list[dict]":
    p = Path(path)
    op = gzip.open if p.suffix == ".gz" else open
    with op(p, "rt", encoding="utf-8") as f:
        d = json.load(f)
    L = _Ledger(run_id, "sweagent", None, hasher)
    for i, s in enumerate(d.get("trajectory") or []):
        L.line = i
        c = L.call(i)
        c["text"] = len(s.get("response") or "")
        act = s.get("action") or ""
        first = act.split()[0] if act.split() else ""
        # 첫 낱말이 경로(./run.sh · /tmp/x)일 수 있다 -- 맨 프로그램 이름만 평문
        name = first if not first or PROGRAM.match(first) else "#" + L.h(first)
        L.tool_use(i, {"id": f"s{i}", "name": name, "input": {"command": act}}, None)
        # 관측 글은 있지만 오류 깃발 · 시각은 없다 -- 있는 것(길이)만
        L.tools[f"s{i}"].update(end={"output_chars": len(s.get("observation") or "")}, t_result=None, nulls=[])
    info = d.get("info") or {}
    v, n = _take(info.get("model_stats") or {}, {"cost_usd": "instance_cost", "tokens_sent": "tokens_sent",
                                                  "tokens_received": "tokens_received", "api_calls": "api_calls"})
    v2, n2 = _take(info, {"terminal_reason": "exit_status"})
    L.line = len(d.get("trajectory") or [])
    L.run_event("run.end", None, {**v, **v2}, n + n2)
    return L.events()
