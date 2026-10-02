"""CMD-T18 측정 도구: Claude Code PostToolUse 훅으로 걸어, 훅이 불린 순간 transcript 에 그 도구의 tool_use · tool_result 가
이미 있는지 적는다(그리고 1 초 뒤 다시). **글은 남기지 않는다** -- 불린 값 · 줄 수 · 개수 · 훅 입력 키 이름 · tool_use_id 만.

    {"hooks": {"PostToolUse": [{"matcher": "*", "hooks": [{"type": "command",
        "command": "T18_OUT=<out.jsonl> python3 <이 파일>"}]}]}}      # 임시 디렉터리의 settings.json, claude -p --settings 로

비밀값을 읽거나 적지 않는다(BD-95). 2026-10-02 측정 결과는 baseline#1 CMD-T18 보고에 있다.
"""
import json, os, sys, time
t0 = time.time()
d = json.load(sys.stdin)
out = os.environ["T18_OUT"]
tid = d.get("tool_use_id")
path = d.get("transcript_path")

def look():
    r = {"exists": bool(path) and os.path.exists(path), "lines": 0, "use": False, "result": False, "uses_total": 0, "results_total": 0}
    if not r["exists"]:
        return r
    with open(path, encoding="utf-8") as f:
        for line in f:
            r["lines"] += 1
            try:
                x = json.loads(line)
            except json.JSONDecodeError:
                continue
            c = (x.get("message") or {}).get("content")
            if isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        r["uses_total"] += 1
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        r["results_total"] += 1
                    if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id") == tid:
                        r["use"] = True
                    if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") == tid:
                        r["result"] = True
    return r

row = {"hook_unix_ms": round(t0 * 1000), "keys": sorted(d), "event": d.get("hook_event_name"), "tool_name": d.get("tool_name"),
       "has_tool_use_id": bool(tid), "tool_use_id": tid, "at_hook": look()}
time.sleep(1.0)
row["after_1s"] = look()
with open(out, "a", encoding="utf-8") as f:
    f.write(json.dumps(row) + "\n")
