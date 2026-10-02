"""CMD-T19 측정 도구: Claude Code PreToolUse 훅으로 걸어, 훅이 불린 순간(그리고 1 초 뒤) transcript 에 **지금 도구의**
tool_use 줄이 이미 있는지 적는다. 함께 그 순간 L0 cc_jsonl 수집기가 무엇을 내는지(그 id 의 tool.start 가 있나 ·
끝 없는 tool.start 수)도 적는다 -- Sensor 가 그 순간을 '기다리는 중' 으로 볼지 가르는 값이다.
**글은 남기지 않는다** -- 불린 값 · 줄 수 · 개수 · 훅 입력 키 이름 · tool_use_id 만.

    {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command",
        "command": "T19_OUT=<out.jsonl> T19_TELEMETRY=<Telemetry 경로> python3 <이 파일>"}]}]}}

훅은 아무것도 출력하지 않고 0 으로 끝난다(도구를 막지 않는다). 비밀값을 읽거나 적지 않는다(BD-95).
"""
import json
import os
import sys
import time

t0 = time.time()
d = json.load(sys.stdin)
tid = d.get("tool_use_id")
path = d.get("transcript_path")


def snapshot():
    """transcript 를 한 번 읽어 둔다 -- 날 줄 검사와 L0 보기가 **같은 바이트**를 보게(첫 실행에서 둘 사이에 줄이 써지는 경합을 봤다)."""
    t = time.time()
    if not path or not os.path.exists(path):
        return None, round((t - t0) * 1000, 1)
    with open(path, encoding="utf-8") as f:
        return f.read(), round((t - t0) * 1000, 1)


def look(text):
    r = {"lines": 0, "use": False, "result": False, "uses_total": 0, "results_total": 0}
    for line in (text or "").splitlines():
        r["lines"] += 1
        try:
            x = json.loads(line)
        except json.JSONDecodeError:
            continue
        c = (x.get("message") or {}).get("content")
        if not isinstance(c, list):
            continue
        for b in c:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                r["uses_total"] += 1
                r["use"] = r["use"] or b.get("id") == tid
            if b.get("type") == "tool_result":
                r["results_total"] += 1
                r["result"] = r["result"] or b.get("tool_use_id") == tid
    return r


def l0_view(text):
    """같은 바이트를 L0 로 거두면: 이 id 의 tool.start 가 있나 · 끝(tool.end) 없는 tool.start 수."""
    tel = os.environ.get("T19_TELEMETRY")
    if not tel or text is None:
        return None
    import tempfile
    if tel not in sys.path:
        sys.path.insert(0, tel)
    from telemetry.collect import from_cc_jsonl
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
        f.write(text)
    try:
        evs = from_cc_jsonl(f.name, "probe")
    finally:
        os.unlink(f.name)
    starts = {e["data"]["tool_index"]: e["data"].get("tool_use_id") for e in evs if e["type"] == "tool.start"}
    ended = {e["data"]["tool_index"] for e in evs if e["type"] == "tool.end"}
    return {"this_start": tid in starts.values(), "starts": len(starts),
            "open_starts": sum(1 for i in starts if i not in ended)}


def sample():
    text, ms = snapshot()
    return {"ms_after_hook": ms, "exists": text is not None, **look(text), "l0": l0_view(text)}


row = {"hook_unix_ms": round(t0 * 1000), "keys": sorted(d), "event": d.get("hook_event_name"),
       "tool_name": d.get("tool_name"), "has_tool_use_id": bool(tid), "tool_use_id": tid, "at_hook": sample()}
time.sleep(float(os.environ.get("T19_DELAY_S", "1.0")))        # 시험만 줄인다
row["after_1s"] = sample()
with open(os.environ["T19_OUT"], "a", encoding="utf-8") as f:
    f.write(json.dumps(row) + "\n")
