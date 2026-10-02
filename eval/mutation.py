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
     "                if d[\"end\"] is not None:\n", "                if d[\"end\"] is None:\n                    d.update(end={\"is_error\": False}, t_result=None, nulls=[])\n                if True:\n"),
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
