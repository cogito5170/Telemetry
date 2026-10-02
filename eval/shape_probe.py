"""원천 줄의 **꼴만** 보여 주는 탐침 -- 글(내용)은 내지 않는다. L0 수집기가 그 줄에서 무슨 사건을 냈는지 나란히 보인다.

    python3 eval/shape_probe.py <세션>.jsonl --from <ISO 시각> --to <ISO 시각>
    python3 eval/shape_probe.py <세션>.jsonl --lines 4400 4460

줄마다: 줄 번호(0 부터) · 시각 · type/subtype · 맨 위 키 이름들 · message.role · content 꼴(str 길이 | 블록 type 목록) ·
isMeta · isSidechain · isCompactSummary · isVisibleInTranscriptOnly · origin.kind · turnOrigin · turnPosition 있나 ·
queue operation/reason · 그 줄에서 L0 가 낸 실행 단위 사건(입력 · 차례 경계 · 오류 · 압축 …).
CMD-T13(재개 입력의 turn.start 누락)처럼 '왜 이 줄이 사건이 안 됐나' 를 가릴 때 쓴다. 출력은 그대로 이슈에 붙여도 된다(글이 없다).
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def shape(d: dict) -> dict:
    m = d.get("message") if isinstance(d.get("message"), dict) else {}
    c = m.get("content")
    if isinstance(c, str):
        content = f"str({len(c)})"
    elif isinstance(c, list):
        content = [b.get("type", "?") if isinstance(b, dict) else type(b).__name__ for b in c]
    else:
        content = None if c is None else type(c).__name__
    o = d.get("origin")
    return {"type": d.get("type"), "subtype": d.get("subtype"), "keys": sorted(d),
            "role": m.get("role"), "content": content,
            "flags": [k for k in ("isMeta", "isSidechain", "isCompactSummary", "isVisibleInTranscriptOnly",
                                  "isApiErrorMessage") if d.get(k)],
            "origin": o.get("kind") if isinstance(o, dict) else o, "turnOrigin": d.get("turnOrigin"),
            "turnPosition": isinstance(d.get("turnPosition"), dict),
            "queue": [d.get("operation"), d.get("reason")] if d.get("type") == "queue-operation" else None,
            "model": m.get("model") if d.get("type") == "assistant" else None}


def main(argv) -> int:
    if not argv:
        print(__doc__)
        return 2
    path = argv[0]
    lo = hi = None
    t_lo = t_hi = None
    if "--lines" in argv:
        i = argv.index("--lines")
        lo, hi = int(argv[i + 1]), int(argv[i + 2])
    if "--from" in argv:
        t_lo = argv[argv.index("--from") + 1]
    if "--to" in argv:
        t_hi = argv[argv.index("--to") + 1]
    sys.path.insert(0, str(ROOT))
    import telemetry.collect as C
    # 수집기를 그대로 돌리며 실행 단위 사건(입력 · 차례 경계 · 오류 …)이 어느 원천 줄에서 났는지만 엿본다
    by_line: dict = {}
    evs_lines = []
    orig_run_event = C._Ledger.run_event

    def run_event(self, type, at, data, nulls=()):
        evs_lines.append((self.line, type))
        return orig_run_event(self, type, at, data, nulls)
    C._Ledger.run_event = run_event
    try:
        C.from_cc_jsonl(path, "probe")
    finally:
        C._Ledger.run_event = orig_run_event
    for ln, t in evs_lines:
        by_line.setdefault(ln, []).append(t)
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f):
            if lo is not None and not (lo <= n <= hi):
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = d.get("timestamp")
            if t_lo and (not ts or ts < t_lo):
                continue
            if t_hi and (not ts or ts > t_hi):
                continue
            s = shape(d)
            s = {k: v for k, v in s.items() if v not in (None, [], False)}
            print(json.dumps({"line": n, "ts": ts, **s, "l0_events": by_line.get(n, [])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
