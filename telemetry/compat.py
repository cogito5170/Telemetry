"""L0 사건 -> Sensor 꼴 v3 레코드(model_call · tool_call · run). Sensor 의 State 엔진은 손대지 않고 L0 위에 앉는다.

llmsensor 를 import 하지 않는다(저장소가 따로라 서로의 설치를 요구하지 않는다). 그래서 꼴 v3 의 칸 순서를 여기 그대로 둔다 --
`unobserved` · `reported_null` 목록의 순서가 그 순서를 따른다. 옆에 ../Sensor 가 있으면 시험이 Sensor 수집기의 출력과 **그대로** 대조한다.

옮기는 규칙:
    llm.response                    -> model_call  (context_window 는 runtime.limits 에서 -- Sensor 수집기가 그렇게 채운다)
    tool.start (+ 같은 tool_index 의 tool.end) -> tool_call  (t_issued_ms = start.at, t_result_ms = end.at)
    run.end · 마지막 run.snapshot · runtime.limits · 마지막 provider.rate_limit -> run
    run 레코드는 실행 단위 사건이 하나라도 있으면, 또는 원천이 cc_stream · sweagent 이면(Sensor 수집기가 늘 낸다) 낸다.

v3 에 자리가 없는 L0 칸(response_id · status_code · elapsed_ms · exit_code · llm.request · llm.error · heartbeat · action.* …)은
버린다 -- 꼴 v3 를 넓히지 않는다. 그것들은 원장에 남아 있다.
"""
from __future__ import annotations

V3_SOURCES = ("cc_jsonl", "cc_stream", "sweagent")
MODEL_CALL = ("call_index", "model", "t_start_ms", "t_end_ms", "time_base", "input_tokens", "cache_read_input_tokens",
              "cache_creation_input_tokens", "output_tokens", "thinking_tokens", "server_tool_requests", "iterations",
              "cache_creation_5m_input_tokens", "cache_creation_1h_input_tokens", "stop_reason",
              "tool_calls_per_message", "output_text_chars", "thinking_duration_ms", "first_chunk_ms", "stream_chunks",
              "stream_thinking_estimate", "context_window")
TOOL_CALL = ("call_index", "tool_index", "tool_name", "tool_head", "tool_sig", "tool_input_chars", "t_issued_ms",
             "t_result_ms", "time_base", "reported_duration_ms", "is_error", "interrupted", "tool_output_chars",
             "timed_out")
RUN = ("model", "run_duration_ms", "api_duration_ms", "api_duration_without_retries_ms", "ttft_ms", "num_turns",
       "cost_usd", "terminal_reason", "result_subtype", "is_error", "api_error_status", "permission_denials",
       "context_window", "max_output_tokens", "autocompact_threshold", "rate_limit_utilization", "rate_limit_status",
       "rate_limit_threshold", "snapshot_at_ms", "tokens_sent", "tokens_received", "api_calls", "reported_input_tokens",
       "reported_output_tokens", "reported_cache_read_input_tokens", "reported_cache_creation_input_tokens")
FIELDS = {"model_call": MODEL_CALL, "tool_call": TOOL_CALL, "run": RUN}


def _record(kind, run_id, source, vals: dict, nulls: set) -> dict:
    r = {"kind": kind, "run_id": run_id, "source": source}
    for k in FIELDS[kind]:
        r[k] = vals.get(k)
    r["unobserved"] = [k for k in FIELDS[kind] if r[k] is None and k not in nulls]
    r["reported_null"] = [k for k in FIELDS[kind] if r[k] is None and k in nulls]
    return r


def _take(ev, mapping, vals, nulls):
    """사건의 칸 -> 레코드 칸. 값이면 넣고, 보고된 null 이면 목록에."""
    for dst, src in mapping.items():
        v = ev["data"].get(src)
        if v is not None:
            vals[dst] = v
            nulls.discard(dst)
        elif src in ev["reported_null"]:
            vals.pop(dst, None)
            nulls.add(dst)


def _same(*names):
    return {n: n for n in names}


def to_sensor_records(events) -> "list[dict]":
    runs: dict = {}
    for e in events:
        runs.setdefault(e["run_id"], []).append(e)
    out = []
    for run_id, evs in runs.items():
        evs = sorted(evs, key=lambda e: e["seq"])
        source = evs[0]["source"]
        limits = [e for e in evs if e["type"] == "runtime.limits"]
        cw = next((e["data"]["context_window"] for e in reversed(limits) if e["data"]["context_window"] is not None), None)
        for e in evs:
            if e["type"] == "llm.response":
                d = e["data"]
                vals = {k: d[k] for k in MODEL_CALL if k in d}
                vals.update(time_base=e["time_base"], context_window=cw)
                out.append(_record("model_call", run_id, source, vals, set(e["reported_null"])))
        ends = {e["data"]["tool_index"]: e for e in evs if e["type"] == "tool.end"}
        for e in evs:
            if e["type"] != "tool.start":
                continue
            vals = dict(e["data"], t_issued_ms=e["at"], time_base=e["time_base"])
            nulls: set = set()
            end = ends.get(e["data"]["tool_index"])
            if end is not None:
                vals["t_result_ms"] = end["at"]
                _take(end, {"is_error": "is_error", "interrupted": "interrupted", "timed_out": "timed_out",
                            "tool_output_chars": "output_chars", "reported_duration_ms": "reported_duration_ms"},
                      vals, nulls)
            out.append(_record("tool_call", run_id, source, vals, nulls))
        run_evs = [e for e in evs if e["type"] in ("run.end", "run.snapshot", "runtime.limits", "provider.rate_limit")]
        if not run_evs and source not in ("cc_stream", "sweagent"):
            continue
        vals, nulls = {}, set()
        snaps = [e for e in run_evs if e["type"] == "run.snapshot"]
        if snaps:
            s = snaps[-1]
            _take(s, _same(*s["data"]), vals, nulls)
            vals["snapshot_at_ms"] = s["at"]
        for e in limits:
            _take(e, _same("context_window", "max_output_tokens", "autocompact_threshold"), vals, nulls)
        rl = [e for e in run_evs if e["type"] == "provider.rate_limit"]
        if rl:
            d = rl[-1]["data"]
            for dst, src in (("rate_limit_utilization", "utilization"), ("rate_limit_status", "declared_status"),
                             ("rate_limit_threshold", "declared_threshold")):
                vals[dst] = d[src]
        for e in run_evs:
            if e["type"] == "run.end":
                _take(e, _same(*e["data"]), vals, nulls)
        out.append(_record("run", run_id, source, vals, nulls))
    return out
