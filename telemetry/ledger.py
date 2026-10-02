"""원장 -- L0 사건을 덧붙이기만 하는 JSONL. 고치지 않는다. 위층(Sensor · State)은 이것을 다시 읽어 언제든 재현한다.

같은 원장을 문턱만 바꿔 다시 읽을 수 있는 것이 L0 를 따로 두는 까닭이다(timeout 30 s -> 60 s 로 바꿔도 원장은 그대로).
"""
from __future__ import annotations

import json

from .event import check


class MemorySink:
    def __init__(self):
        self.events: list = []

    def write(self, ev: dict) -> None:
        self.events.append(ev)


class JsonlSink:
    """한 줄에 사건 하나. 쓸 때마다 flush -- 프로세스가 죽어도 거기까지는 남는다(끝 사건이 없는 시작이 곧 증거다)."""

    def __init__(self, path):
        self.path = path

    def write(self, ev: dict) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False, sort_keys=True) + "\n")


def write(path, events) -> None:
    s = JsonlSink(path)
    for e in events:
        s.write(e)


def read(path) -> "list[dict]":
    """꼴에 안 맞는 줄이 있으면 멈춘다."""
    events, rejects = read_lenient(path)
    if rejects:
        n, errs = rejects[0]
        raise ValueError(f"{path}:{n}: {errs}")
    return events


def read_lenient(path) -> "tuple[list, list]":
    """꼴에 안 맞는 줄은 건너뛰고 (줄 번호, 까닭) 으로 모은다 -- 조용히 버리지 않는다."""
    out, rejects = [], []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
                errs = check(ev) if isinstance(ev, dict) else ["사건이 객체가 아니다"]
            except json.JSONDecodeError as e:
                errs = [f"JSON: {e}"]
            if errs:
                rejects.append((n, errs))
            else:
                out.append(ev)
    return out, rejects
