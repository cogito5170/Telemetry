"""BD-50 대조 장부 -- 실데이터 기록마다 Sensor 수집기와 L0 수집기(compat 경유)가 같은 꼴 v3 레코드를 내는지 맞대고 남긴다.

    python3 eval/l0_check.py cc_jsonl <세션>.jsonl ...
    python3 eval/l0_check.py sweagent <dir>/*.traj.gz
    python3 eval/l0_check.py --summary
    python3 eval/l0_check.py --freeze <source> <파일> ...   Sensor 의 원래 수집기 출력 지문(고정 열쇠)을 장부 행에 얼린다
    python3 eval/l0_check.py --verify <source> <파일> ...   L0 경로로 다시 지어 얼린 지문과 맞댄다 -- 원래 수집기를 지운 뒤의 대조
    python3 eval/l0_check.py --reported <source> <보고한 세션> <내용 해시> <native> <l0> <same> <telemetry> <sensor>
        다른 세션이 자기 기록으로 돌린 결과를 옮겨 적는다(그 세션의 기록은 이 컨테이너에 없다). reported_by 가 붙는다.

옆에 ../Sensor 가 있어야 한다(llmsensor.telemetry.l0.compare 를 쓴다). 장부(eval/results/l0_check_corpus.json)에는
**내용을 남기지 않는다**: 기록 식별자의 해시 · 파일 내용 해시 · 레코드 수 · 같은가 · 다르면 다른 칸 이름뿐.

BD-50 기준: 수집기 셋(cc_jsonl · cc_stream · sweagent)마다 **서로 다른 기록** 3 개 이상에서 100 % 같다.
'서로 다른 기록' 은 파일이 아니라 기록 식별자로 센다 -- 같은 세션 JSONL 을 시각을 달리해 두 번 재도 하나다.
"""
from __future__ import annotations

import datetime
import gzip
import hashlib
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SENSOR = ROOT.parent / "Sensor"
LEDGER = ROOT / "eval" / "results" / "l0_check_corpus.json"
SOURCES = ("cc_jsonl", "cc_stream", "sweagent")
NEED = 3


def _h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def recording_id(source: str, path: pathlib.Path) -> str:
    """기록 식별자(해시). cc_jsonl: sessionId · cc_stream: init 의 session_id · sweagent: 파일 이름(인스턴스)."""
    if source == "sweagent":
        return _h(path.name.split(".")[0])
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if source == "cc_jsonl" and d.get("sessionId"):
                return _h(d["sessionId"])
            if source == "cc_stream":
                ln = d.get("line") or {}
                if ln.get("session_id"):
                    return _h(ln["session_id"])
    return _h(str(path.resolve()))          # 식별자가 없다 -- 경로로(같은 파일만 같은 기록)


def content_hash(path: pathlib.Path) -> str:
    op = gzip.open if path.suffix == ".gz" else open
    with op(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


def _rev(repo: pathlib.Path) -> str:
    p = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    return p.stdout.strip() or "?"


GOLDEN_KEY = b"bd50-golden-v1"     # 지문용 고정 열쇠(해시 겨냥이 실행마다 바뀌지 않게). 비밀이 아니다


def digest(records) -> str:
    key = lambda r: (r["kind"], r.get("tool_index", r.get("call_index", -1)))
    return hashlib.sha256(json.dumps(sorted(records, key=key), ensure_ascii=False, sort_keys=True)
                          .encode("utf-8")).hexdigest()[:16]


def _l0_records(source, path):
    sys.path.insert(0, str(ROOT))
    from telemetry import collect as c
    from telemetry.compat import to_sensor_records
    from telemetry.hashing import Hasher
    fn = {"cc_jsonl": c.from_cc_jsonl, "cc_stream": c.from_cc_stream, "sweagent": c.from_sweagent}[source]
    return to_sensor_records(fn(str(path), "golden", Hasher(GOLDEN_KEY)))


def freeze_or_verify(mode, source, paths) -> int:
    rows = load()
    bad = 0
    for p in paths:
        ch = content_hash(p)
        row = next((r for r in rows if r["source"] == source and r["content"] == ch), None)
        if row is None:
            print(f"장부에 없는 내용 {source} {ch} -- 먼저 대조로 넣는다")
            bad += 1
            continue
        if mode == "freeze":
            sys.path.insert(0, str(SENSOR))
            from llmsensor.telemetry import collect as S
            fn = {"cc_jsonl": S.from_cc_jsonl, "cc_stream": S.from_cc_stream, "sweagent": S.from_sweagent}[source]
            row["v3_digest"] = digest(fn(str(p), "golden", S.Hasher(GOLDEN_KEY)))
            row["frozen_sensor"] = _rev(SENSOR)
            print(f"FROZEN {source} {ch} {row['v3_digest']}")
        else:
            got = digest(_l0_records(source, p))
            ok = got == row.get("v3_digest")
            bad += not ok
            print(("SAME " if ok else "DIFF ") + f"{source} {ch} frozen={row.get('v3_digest')} l0={got}")
    if mode == "freeze":
        LEDGER.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 1 if bad else 0


def load() -> list:
    return json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else []


def summary(rows) -> dict:
    out = {}
    for s in SOURCES:
        rs = [r for r in rows if r["source"] == s]
        recs = {r["recording"] for r in rs}
        bad = [r for r in rs if not r["same"]]
        out[s] = {"recordings": len(recs), "checks": len(rs), "all_same": not bad,
                  "meets_bd50": len(recs) >= NEED and not bad}
    out["all_sources_meet_bd50"] = all(out[s]["meets_bd50"] for s in SOURCES)
    return out


def main(argv) -> int:
    if argv[:1] == ["--reported"]:
        source, by, ch, native, l0, same, tel, sen = argv[1:9]
        rows = load()
        if any(r["source"] == source and r["content"] == ch for r in rows):
            print("이미 있다")
            return 0
        rows.append({"source": source, "recording": _h(f"reported:{by}"), "content": ch, "native": int(native),
                     "l0": int(l0), "same": same == "true", "diff_fields": [], "checked": datetime.date.today().isoformat(),
                     "telemetry": tel, "sensor": sen, "reported_by": by})
        LEDGER.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(json.dumps(summary(rows), ensure_ascii=False))
        return 0
    if argv[:1] in (["--freeze"], ["--verify"]):
        return freeze_or_verify(argv[0][2:], argv[1], [pathlib.Path(p) for p in argv[2:]])
    if argv[:1] == ["--summary"]:
        print(json.dumps(summary(load()), ensure_ascii=False, indent=1))
        return 0
    source, paths = argv[0], [pathlib.Path(p) for p in argv[1:]]
    if source not in SOURCES or not paths:
        print(__doc__)
        return 2
    sys.path.insert(0, str(SENSOR))
    sys.path.insert(0, str(ROOT))
    from llmsensor.telemetry.l0 import compare
    rows = load()
    seen = {(r["source"], r["content"]) for r in rows}
    revs = {"telemetry": _rev(ROOT), "sensor": _rev(SENSOR)}
    for p in paths:
        ch = content_hash(p)
        if (source, ch) in seen:
            continue
        r = compare(source, str(p))
        if not r.get("available"):
            print("L0 Telemetry 를 못 찾았다")
            return 2
        row = {"source": source, "recording": recording_id(source, p), "content": ch, "native": r["native"],
               "l0": r["l0"], "same": r["same"], "diff_fields": (r["first_diff"] or {}).get("fields", []),
               "checked": datetime.date.today().isoformat(), **revs}
        rows.append(row)
        seen.add((source, ch))
        print(("SAME " if r["same"] else "DIFF ") + f"{source} {row['recording']} {r['native']}/{r['l0']}")
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary(rows), ensure_ascii=False))
    return 0 if all(r["same"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
