"""시험용 원천 파일 짓기 -- Claude Code JSONL · stream-json · SWE-agent .traj. 모두 지어낸 것이다(실데이터 아님)."""
import gzip
import json


def write_session(path, turns, cost_state=None):
    """turns: [("user", text) | ("tool", name, input, ok, output, extra) | ("text", s) | ("side", text)].
    extra 는 toolUseResult(interrupted · durationSeconds). cost_state 가 있으면 그 자리 뒤에 넣는다(줄 번호)."""
    lines, n, t = [], 0, 0

    def ts():
        nonlocal t
        t += 1
        return f"2026-10-01T00:00:{t:02d}Z"

    for x in turns:
        n += 1
        if x[0] == "user":
            lines.append({"type": "user", "timestamp": ts(), "message": {"role": "user", "content": x[1]}})
        elif x[0] == "side":
            lines.append({"type": "assistant", "isSidechain": True, "timestamp": ts(), "message": {
                "id": f"side{n}", "usage": {"input_tokens": 9}, "content": [{"type": "text", "text": x[1]}]}})
        elif x[0] == "text":
            mid = f"m{n}"
            lines.append({"type": "assistant", "timestamp": ts(), "message": {
                "id": mid, "model": "claude-x", "stop_reason": None,
                "usage": {"input_tokens": 100, "output_tokens": 5}, "content": [{"type": "thinking"}]}})
            lines.append({"type": "assistant", "timestamp": ts(), "thinkingDurationMs": 40, "message": {
                "id": mid, "model": "claude-x", "stop_reason": "end_turn",
                "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": None},
                "content": [{"type": "text", "text": x[1]}]}})
        else:
            _, name, inp, ok, out, extra = x
            tid = f"tu{n}"
            lines.append({"type": "assistant", "timestamp": ts(), "message": {
                "id": f"m{n}", "model": "claude-x",
                "usage": {"input_tokens": 1000, "cache_read_input_tokens": 500, "output_tokens": 10,
                          "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 30}},
                "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}})
            if ok is not None:
                lines.append({"type": "user", "timestamp": ts(), "toolUseResult": extra, "message": {
                    "role": "user", "content": [{"type": "tool_result", "tool_use_id": tid,
                                                 "content": [{"type": "text", "text": out}], "is_error": not ok}]}})
        if cost_state is not None and n == cost_state[0]:
            lines.append({"type": "cost-state", **cost_state[1]})
    with open(path, "w", encoding="utf-8") as f:
        for d in lines:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
        f.write("not json\n")


SESSION = [("user", "go"),
           ("tool", "Bash", {"command": "cd /x && make"}, False, "err", {"interrupted": False, "durationSeconds": 1.5}),
           ("tool", "Bash", {"command": "make"}, False, "Command timed out after 2m", {"interrupted": None}),
           ("tool", "Read", {"file_path": "/home/secret/a.py"}, True, "ok", {}),
           ("side", "하위 에이전트"),
           ("text", "done"),
           ("tool", "Bash", {"command": "sleep 99"}, None, "", {})]      # 결과가 안 왔다(끝나지 않음)
COST = (4, {"totalDuration": 9000, "totalAPIDuration": 7000, "totalAPIDurationWithoutRetries": 6500,
            "totalCostUSD": 0.12, "modelUsage": {"claude-x": {"inputTokens": 3000, "outputTokens": 40,
                                                              "cacheReadInputTokens": 1500,
                                                              "cacheCreationInputTokens": 0}}})

STREAM = [
    {"_t": 0, "line": {"type": "system", "subtype": "init"}},
    {"_t": 50, "line": {"type": "autocompact_state", "value": {"threshold": 160000}}},
    {"_t": 100, "line": {"type": "stream_event", "event": {"type": "message_start", "message": {
        "id": "m1", "model": "h", "usage": {"input_tokens": 10, "output_tokens": 1,
                                            "cache_creation": {"ephemeral_5m_input_tokens": 0,
                                                               "ephemeral_1h_input_tokens": 400}}}}}},
    {"_t": 150, "line": {"type": "stream_event", "event": {"type": "content_block_delta"}}},
    {"_t": 180, "line": {"type": "stream_event", "event": {"type": "content_block_delta"}}},
    {"_t": 190, "line": {"type": "system", "subtype": "thinking_tokens", "estimated_tokens": 42}},
    {"_t": 200, "line": {"type": "stream_event", "event": {"type": "message_delta", "delta": {
        "stop_reason": "tool_use"}, "usage": {"input_tokens": 10, "cache_read_input_tokens": 5,
                                              "cache_creation_input_tokens": 400, "output_tokens": 30,
                                              "output_tokens_details": {"thinking_tokens": 12}}}}},
    {"_t": 210, "line": {"type": "assistant", "message": {"id": "m1", "content": [
        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}]}}},
    {"_t": 220, "line": {"type": "rate_limit_event", "rate_limit_info": {
        "utilization": 0.81, "status": "allowed_warning", "surpassedThreshold": 0.8}}},
    {"_t": 400, "line": {"type": "user", "tool_use_result": {"interrupted": False}, "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "boom", "is_error": True}]}}},
    {"_t": 405, "line": {"type": "rate_limit_event", "rate_limit_info": {"utilization": 0.86}}},   # 상태 문자열 없이 다시
    {"_t": 410, "line": {"type": "assistant", "parent_tool_use_id": "t1", "message": {"id": "sub", "content": []}}},
    {"_t": 500, "line": {"type": "result", "subtype": "success", "duration_ms": 500, "num_turns": 1,
                         "api_error_status": None, "total_cost_usd": 0.01, "permission_denials": [{}, {}],
                         "terminal_reason": "completed", "is_error": False,
                         "modelUsage": {"h": {"contextWindow": 200000, "maxOutputTokens": None}},
                         "usage": {"input_tokens": 10, "output_tokens": 30, "cache_read_input_tokens": None}}},
]

TRAJ = {"trajectory": [{"action": "ls -la", "observation": "a b", "response": "let me look"},
                       {"action": "/tmp/private/run.sh --x", "observation": "", "response": ""},
                       {"action": "", "observation": "x", "response": "hm"}],
        "info": {"exit_status": "submitted", "model_stats": {"instance_cost": 0.3, "tokens_sent": 1000,
                                                             "tokens_received": None, "api_calls": 3}}}


def write_stream(path, lines=STREAM):
    with open(path, "w", encoding="utf-8") as f:
        for x in lines:
            f.write(json.dumps(x) + "\n")


def write_traj(path, traj=TRAJ):
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(traj, f)
