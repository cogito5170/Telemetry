"""변이 시험 -- 코드를 일부러 망가뜨려 시험이 빨개지는지 본다. 하나라도 초록으로 남으면 그 시험은 헛돈다.

    python3 eval/mutation.py            # 복사본에서 변이마다 시험을 돌린다. 원본은 건드리지 않는다
"""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
# (이름, 파일, 바꿀 글, 바꿀 것) -- 각각 L0 경계의 한 줄을 깬다
MUTANTS = [
    ("해석 칸 하나를 목록에 넣음", "telemetry/catalog.py",
     '"tool_index": _f("int", X),\n        "is_error"', '"tool_index": _f("int", X), "health": _f("str", M),\n        "is_error"'),
    ("우리 문턱을 measured 로 넣음", "telemetry/catalog.py",
     '"elapsed_ms": _f("num", M, "수집기가 한 시계로 시작~끝을 잰 값"),',
     '"elapsed_ms": _f("num", M, "수집기가 한 시계로 시작~끝을 잰 값"), "timeout_threshold_ms": _f("num", M),'),
    ("Recorder 가 경과 시간으로 시간 초과를 판정", "telemetry/recorder.py",
     'self.emit("tool.end", tool_index=idx, elapsed_ms=self.mono() - t0, **h.vals)',
     'el = self.mono() - t0\n            h.vals.setdefault("timed_out", el > 30000)\n            self.emit("tool.end", tool_index=idx, elapsed_ms=el, **h.vals)'),
    ("결과 없음을 성공으로 메움", "telemetry/recorder.py",
     "        h = _Outcome()\n        t0 = self.mono()\n        try:\n            yield h\n        except BaseException as e:\n            h.vals.setdefault(\"exception\", type(e).__name__)\n            h.vals.setdefault(\"is_error\", True)       #",
     "        h = _Outcome()\n        h.vals[\"is_error\"] = False\n        t0 = self.mono()\n        try:\n            yield h\n        except BaseException as e:\n            h.vals[\"exception\"] = type(e).__name__\n            h.vals[\"is_error\"] = True       #"),
    ("예외 메시지를 남김", "telemetry/recorder.py",
     'h.vals.setdefault("exception", type(e).__name__)\n            h.vals.setdefault("is_error", True)       #',
     'h.vals.setdefault("exception", f"{type(e).__name__}: {e}")\n            h.vals.setdefault("is_error", True)       #'),
    ("다른 도구의 시간 초과를 False 로 메움", "telemetry/collect/__init__.py",
     'if tool_name != "Bash":\n        return None', 'if tool_name != "Bash":\n        return False'),
    ("오지 않은 결과를 지어냄", "telemetry/collect/__init__.py",
     "            if d[\"end\"] is not None:\n",
     "            if d[\"end\"] is None:\n                d.update(end={\"is_error\": False}, t_result=None, nulls=[])\n            if True:\n"),
    ("보고된 null 을 못 봄으로", "telemetry/collect/__init__.py",
     "                nulls.append(field)\n", "                pass\n"),
    ("하위 에이전트 줄을 섞음", "telemetry/collect/__init__.py",
     '            if d.get("isSidechain"):\n                continue\n', ""),
    ("겨냥 경로를 평문으로", "telemetry/hashing.py",
     'return f"{nm}:#{h(target)}"', 'return f"{nm}:{target}"'),
    ("OpenAI 입력에서 캐시를 안 뺌", "telemetry/usage.py",
     'out["input_tokens"] = pt - cached', 'out["input_tokens"] = pt'),
    ("표에 없는 오류를 추측", "telemetry/errors.py",
     "K.RATE_LIMITED if http_status == 429 else K.UNKNOWN", "K.RATE_LIMITED if http_status == 429 else K.SERVER_ERROR"),
    ("0 을 못 봄으로", "telemetry/event.py",
     "        d[k] = data.get(k)\n", "        d[k] = data.get(k) or None\n"),
    ("봉투를 연다(모르는 칸 허용)", "telemetry/event.py",
     "    if set(ev) != set(ENVELOPE):", "    if not set(ENVELOPE) <= set(ev):"),
    ("compat 이 보고된 null 을 버림", "telemetry/compat.py",
     "            nulls.add(dst)\n", "            pass\n"),
    ("compat 이 마지막이 아니라 첫 요금 한도 사건을 씀", "telemetry/compat.py",
     'd = rl[-1]["data"]', 'd = rl[0]["data"]'),
    ("OTel 꼴에서 캐시 밖 입력을 지어냄", "telemetry/usage.py",
     "                out[dst] = u[src]\n        return out, []",
     "                out[dst] = u[src]\n        if u.get(\"input_tokens\") is not None:\n            out[\"input_tokens\"] = u[\"input_tokens\"] - (u.get(\"cached_input_tokens\") or 0)\n        return out, []"),
    ("볼 것 없는 오류를 UNKNOWN 으로 번역", "telemetry/recorder.py",
     "        nothing = http_status is None and not body", "        nothing = False"),
    ("오류 메시지를 남김", "telemetry/recorder.py",
     "getattr(e, \"headers\", None), attempt, self.mono() - t0, type(e).__name__, table)",
     "getattr(e, \"headers\", None), attempt, self.mono() - t0, f\"{type(e).__name__}: {e}\", table)"),
    ("Stop 훅이 막은 끝을 끝으로", "telemetry/collect/__init__.py",
     'kind = "turn.continued" if d.get("preventedContinuation") is True else "turn.end"', 'kind = "turn.end"'),
    ("isMeta 줄을 입력으로", "telemetry/collect/__init__.py",
     'is_input = d.get("type") == "user" and not d.get("isMeta") and (', 'is_input = d.get("type") == "user" and ('),
    ("닫힘 표시 없이 파일 끝을 닫힘으로", "telemetry/collect/__init__.py",
     '            L.run_event("turn.end", t, {"marker": "result"})\n    return L.events()',
     '            L.run_event("turn.end", t, {"marker": "result"})\n    L.run_event("source.closed", None, {})\n    return L.events()'),
    ("L0 가 turn_open 을 계산해 싣는다", "telemetry/catalog.py",
     '"input_chars": _f("int", M),\n    },\n    "turn.end"', '"input_chars": _f("int", M), "turn_open": _f("bool", M),\n    },\n    "turn.end"'),
    ("원천 순서를 버림(옛 순서)", "telemetry/collect/__init__.py",
     "sorted(items, key=lambda x: x[:3])", "sorted(items, key=lambda x: (x[1], x[2]))"),
    ("번호가 없는 차례에 번호를 세어 메움", "telemetry/collect/__init__.py",
     '                L.run_event("turn.start", t, {**v, "turn_origin": origin', '                v.setdefault("turn_index", L.line)\n                L.run_event("turn.start", t, {**v, "turn_origin": origin'),
    ("D1: 구조화 칸 timedOutAfterMs 를 안 봄", "telemetry/collect/__init__.py",
     '    if isinstance(tur, dict) and "timedOutAfterMs" in tur:\n        return True\n    if tool_name != "Bash":',
     '    if tool_name != "Bash":'),
    ("D1: 성공한 출력이 인용한 문구를 시간 초과로", "telemetry/collect/__init__.py",
     'return bool(block.get("is_error") is True and txt.lstrip().startswith("Exit code") and TIMEOUT_TEXT.search(txt))',
     'return bool(TIMEOUT_TEXT.search(txt))'),
    ("D2: 429 줄을 모형 호출로", "telemetry/collect/__init__.py",
     'if d.get("type") == "assistant" and (d.get("isApiErrorMessage") or d.get("apiErrorStatus") is not None):',
     'if False:'),
    ("D2: <synthetic> 줄을 모형 호출로", "telemetry/collect/__init__.py",
     'elif d.get("type") == "assistant" and m.get("model") == "<synthetic>":\n                pass',
     'elif False:\n                pass'),
    ("D2: compat 이 API 오류를 실행 요약에 안 옮김", "telemetry/compat.py",
     '            vals["api_error_status"] = str(errs[-1]["data"]["http_status"])', '            pass'),
    ("D4: 압축 사건을 안 거둠", "telemetry/collect/__init__.py",
     '                L.run_event("runtime.compaction", t, *_compaction(d.get("compactMetadata")))', '                pass'),
    ("백그라운드 칸이 없는데 '안 옮김' 으로 메움", "telemetry/collect/__init__.py",
     '    if "timedOutAfterMs" in tur or "backgroundTaskId" in tur:\n        v["moved_to_background"]',
     '    if True:\n        v["moved_to_background"]'),
    ("박동 표시가 없는데 False 로 메움", "telemetry/collect/__init__.py",
     '            v, nl = _take(d, {"heartbeat_flag": "heartbeat"})',
     '            v, nl = {"heartbeat_flag": bool(d.get("heartbeat"))}, []'),
    ("흡수된 입력을 안 거둠", "telemetry/collect/__init__.py",
     '                L.run_event("input.removed", t, {"reason": d.get("reason")})', '                pass'),
    ("스트림의 캐시 쓰기 나눔(message_start usage)을 버림 -- Sensor mutation_ms 의 같은 변이를 이쪽으로(CMD-T9)",
     "telemetry/collect/__init__.py",
     '                        merged = dict(c.get("_start_usage") or {})', '                        merged = {}'),
    ("compat 이 꼴 v3 칸 순서를 바꿈(얼린 출력과 달라진다)", "telemetry/compat.py",
     'RUN = ("model", "run_duration_ms",', 'RUN = ("run_duration_ms", "model",'),
    ("T10: tool_progress 를 다시 하위 에이전트로 거름", "telemetry/collect/__init__.py",
     '        if d.get("parent_tool_use_id") and not _main_progress(d, L):', '        if d.get("parent_tool_use_id"):'),
    ("T12: tool_use_id 만 봄(T10 의 결함 -- 실기록 0/8)", "telemetry/collect/__init__.py",
     'for ref in (d.get("tool_use_id"), d.get("parent_tool_use_id")):', 'for ref in (d.get("tool_use_id"),):'),
    ("T12: 도구 이름을 안 맞춤(하위 에이전트 진행이 Task 호출 id 로 새어 들어옴)", "telemetry/collect/__init__.py",
     'if t is not None and name and t["start"]["tool_name"] == name:', 'if t is not None:'),
    ("T11: API 오류로 끝난 차례를 안 닫음", "telemetry/collect/__init__.py",
     '    L.run_event("turn.end", t, {"marker": "api_error", "error_type": err})\n', ''),
    ("T11: 오류가 아닌 <synthetic> 줄에서도 차례를 닫음(짐작)", "telemetry/collect/__init__.py",
     'elif d.get("type") == "assistant" and m.get("model") == "<synthetic>":\n                pass',
     'elif d.get("type") == "assistant" and m.get("model") == "<synthetic>":\n                L.run_event("turn.end", t, {"marker": "synthetic"})'),
    ("T14: 초를 그대로 ms 로 적음", "telemetry/collect/__init__.py",
     '        return {"resets_at_ms": v * 1000}, []', '        return {"resets_at_ms": v}, []'),
    ("T14: resetsAt 을 안 읽음(못 봄으로 잘못 적음)", "telemetry/collect/__init__.py",
     '    if "resetsAt" not in src:\n        return {}, []', '    if True:\n        return {}, []'),
    ("T14: stream 의 한도 종류를 안 읽음", "telemetry/collect/__init__.py",
     '            ov, on = _take(info, {"limit_type": "rateLimitType",', '            ov, on = _take(info, {"limit_type_x": "rateLimitType",'),
    ("T13: isMeta 경계를 버림(재개 차례가 사라짐)", "telemetry/collect/__init__.py",
     '            if is_input or declared_boundary:', '            if is_input:'),
    ("T13: 경계 선언 없는 isMeta 줄도 차례를 엶", "telemetry/collect/__init__.py",
     '            declared_boundary = (d.get("type") == "user" and d.get("isMeta") is True\n                                 and isinstance(d.get("turnPosition"), dict))',
     '            declared_boundary = d.get("type") == "user" and d.get("isMeta") is True'),
    ("L0 가 위층을 import", "telemetry/ledger.py",
     "from .event import check\n", "from .event import check\ntry:\n    import llmsensor  # noqa\nexcept ImportError:\n    pass\n"),
]


def run(tree):
    p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."], cwd=tree,
                       capture_output=True, text=True)
    return p.returncode == 0, p.stderr.strip().splitlines()[-1] if p.stderr.strip() else ""


def main():
    out = []
    with tempfile.TemporaryDirectory() as d:
        base = pathlib.Path(d) / "Telemetry"
        shutil.copytree(ROOT, base, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        (pathlib.Path(d) / "Sensor").symlink_to(ROOT.parent / "Sensor") if (ROOT.parent / "Sensor").is_dir() else None
        ok, _ = run(base)
        assert ok, "원본이 초록이 아니다"
        for name, f, old, new in MUTANTS:
            p = base / f
            src = p.read_text(encoding="utf-8")
            assert src.count(old) >= 1, f"변이 자리를 못 찾음: {name}"
            p.write_text(src.replace(old, new, 1), encoding="utf-8")
            green, tail = run(base)
            p.write_text(src, encoding="utf-8")
            out.append({"mutant": name, "red": not green, "tail": tail})
            print(("RED  " if not green else "GREEN") + "  " + name)
    red = sum(o["red"] for o in out)
    print(f"{red}/{len(out)} 빨강")
    (ROOT / "eval" / "mutation_results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n",
                                                         encoding="utf-8")
    return 0 if red == len(out) else 1


if __name__ == "__main__":
    sys.exit(main())
