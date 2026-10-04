"""사건 봉투 -- L0 의 단 하나의 꼴.

    {"spec": "l0-telemetry/1", "id": "<run_id>:<seq>", "type": "tool.end", "run_id": ..., "seq": 7,
     "source": "cc_jsonl", "at": 1759363200000.0, "time_base": "unix_ms",
     "data": {...catalog 의 칸 전부...}, "unobserved": [...], "reported_null": [...]}

null 인 칸은 그 이름이 **정확히 한 목록**에 있다 (Sensor 꼴 v2 의 규율을 그대로):

    unobserved     원천이 그 값을 주지 않았다 -- 못 봤다
    reported_null  원천이 그 칸을 null 로 **주었다** -- 봤고, 값이 null 이다

0 과 '못 봄', '보고된 null' 과 '못 봄' 을 섞지 않는다. 기본값으로 메우지 않는다.
`at` 은 그 사건을 본 시각. 원천에 시각이 없으면 None(SWE-agent) -- 순서는 seq 가 준다.
"""
from __future__ import annotations

from .catalog import EVENTS, REQUIRED, SPEC, TIME_BASES

ENVELOPE = ("spec", "id", "type", "run_id", "seq", "source", "at", "time_base", "data", "unobserved", "reported_null")
_PY = {"int": (int,), "num": (int, float), "str": (str,), "bool": (bool,)}


def make(type: str, run_id: str, seq: int, source: str, at=None, time_base=None, reported_null=(), **data) -> dict:
    """빈 칸은 null. reported_null 에 든 이름은 '원천이 null 로 줬다', 나머지 null 은 unobserved. 모르는 칸은 KeyError."""
    if type not in EVENTS:
        raise KeyError(f"모르는 사건 종류 {type!r}")
    fields = EVENTS[type]
    extra = (set(data) | set(reported_null)) - set(fields)
    if extra:
        raise KeyError(f"{type}: 꼴에 없는 칸 {sorted(extra)}")
    rn = set(reported_null)
    d = {}
    for k in fields:
        d[k] = data.get(k)
        if k in rn and d[k] is not None:
            raise ValueError(f"{type}.{k}: reported_null 인데 값이 있다 ({d[k]!r})")
    ev = {"spec": SPEC, "id": f"{run_id}:{seq}", "type": type, "run_id": run_id, "seq": seq, "source": source,
          "at": at, "time_base": time_base, "data": d,
          "unobserved": [k for k in fields if d[k] is None and k not in rn],
          "reported_null": [k for k in fields if d[k] is None and k in rn]}
    errs = check(ev)
    if errs:
        raise ValueError(f"{type}: {errs}")
    return ev


def observed(ev: dict, k: str) -> bool:
    """그 칸을 봤나 -- 값이 있거나, 원천이 null 로 보고했으면 봤다."""
    return ev["data"].get(k) is not None or k in ev.get("reported_null", ())


def check(ev: dict) -> "list[str]":
    """닫힌 꼴 검사. 빈 목록이면 통과."""
    errs = []
    if set(ev) != set(ENVELOPE):
        errs.append(f"봉투 칸 {sorted(set(ev) ^ set(ENVELOPE))}")
        return errs
    if ev["spec"] != SPEC:
        errs.append(f"spec {ev['spec']!r}")
    fields = EVENTS.get(ev["type"])
    if fields is None:
        return errs + [f"모르는 사건 종류 {ev['type']!r}"]
    if not isinstance(ev["run_id"], str) or not ev["run_id"]:
        errs.append("run_id")
    if not isinstance(ev["seq"], int) or isinstance(ev["seq"], bool) or ev["seq"] < 0:
        errs.append("seq")
    if ev["id"] != f"{ev['run_id']}:{ev['seq']}":
        errs.append("id ≠ run_id:seq")
    if not isinstance(ev["source"], str) or not ev["source"]:
        errs.append("source")
    if ev["time_base"] not in TIME_BASES:
        errs.append(f"time_base {ev['time_base']!r}")
    if ev["at"] is not None and (not isinstance(ev["at"], (int, float)) or isinstance(ev["at"], bool)):
        errs.append("at")
    data = ev["data"]
    if not isinstance(data, dict) or set(data) != set(fields):
        return errs + [f"data 칸 {sorted(set(data or {}) ^ set(fields))}"]
    for k, f in fields.items():
        v = data[k]
        lists = (k in ev["unobserved"]) + (k in ev["reported_null"])
        if v is None:
            if lists != 1:
                errs.append(f"null 인 {k} 가 unobserved/reported_null 중 정확히 하나에 있어야 한다 ({lists})")
            continue
        if lists:
            errs.append(f"값이 있는 {k} 가 null 목록에 있다")
        ok = isinstance(v, _PY[f.type]) and not (f.type != "bool" and isinstance(v, bool))
        if not ok:
            errs.append(f"{k}: {f.type} 이 아니다 ({v!r})")
        elif f.type in ("int", "num") and f.origin != "ref" and v < 0 and k not in ("exit_code",):
            errs.append(f"{k}: 음수 {v}")
    for k in REQUIRED.get(ev["type"], ()):
        if data.get(k) is None:
            errs.append(f"{ev['type']}.{k}: 꼭 있어야 하는 칸이 비었다")
    for k in ev["unobserved"] + ev["reported_null"]:
        if k not in fields:
            errs.append(f"목록에 꼴 밖 칸 {k}")
    return errs
