"""겨냥 글은 남기지 않는다. 도구 인자에서 꺼낸 겨냥(파일 경로 · URL · 패턴 · 검색어 · 실행 파일 경로)은 열쇠 해시(HMAC-SHA256,
12 hex)로만. 평문은 `^[A-Za-z][A-Za-z0-9_.+-]*$` 꼴의 **맨 프로그램 이름**(git · python3 · pytest)뿐 -- 걸음 종류를 가르는 데 필요하고, 경로가 아니다.

열쇠: 환경 변수 `TELEMETRY_HASH_KEY`(또는 Sensor 와 같은 `LLMSENSOR_HASH_KEY`) 가 있으면 그것, 없으면 **프로세스마다 무작위로 만들고
저장하지 않는다.** 한 수집 안에서는 같은 겨냥이 같은 해시를 받아 반복을 셀 수 있지만, 글을 되찾거나 사전 대입으로 맞춰 볼 수 없다.
(Sensor llmsensor/telemetry/collect.py 의 규칙을 그대로 옮겼다 -- 같은 열쇠면 같은 해시가 나온다.)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets

PROGRAM = re.compile(r"^[A-Za-z][A-Za-z0-9_.+-]*$")


class Hasher:
    def __init__(self, key: "bytes | str | None" = None):
        if key is None:
            key = os.environ.get("TELEMETRY_HASH_KEY") or os.environ.get("LLMSENSOR_HASH_KEY") or secrets.token_bytes(32)
        self.key = key.encode() if isinstance(key, str) else key

    def __call__(self, text: str) -> str:
        return hmac.new(self.key, text.encode(), hashlib.sha256).hexdigest()[:12]


_DEFAULT: "Hasher | None" = None


def default_hasher() -> Hasher:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = Hasher()
    return _DEFAULT


def call_head(name: str, inp: dict) -> str:
    """도구 이름 + 무엇을 겨눴나(명령의 첫 낱말 · 파일 경로). llmsensor.trace.call_head 와 같은 정의."""
    inp = inp or {}
    if "command" in inp:
        words = str(inp["command"]).split()
        skip = {"cd": 2, "timeout": 2, "&&": 1, "env": 1, "sudo": 1, "time": 1, "nohup": 1, "setsid": 1}
        while words and (words[0] in skip or "=" in words[0]):
            words = words[skip.get(words[0], 1):]
        if words[:2] in (["python3", "-m"], ["python", "-m"]):
            words = words[2:]
        return f"{name}:{words[0] if words else ''}"
    for k in ("file_path", "path", "url", "pattern", "query"):
        if k in inp:
            return f"{name}:{inp[k]}"
    return name


def tool_sig(name: str, inp, h: Hasher) -> str:
    return h(name + json.dumps(inp or {}, ensure_ascii=False, sort_keys=True))


def tool_head(name: str, inp, h: Hasher) -> str:
    """이름:겨냥. 겨냥이 맨 프로그램 이름(명령의 첫 낱말)이면 평문, 그 밖은 #해시."""
    nm, _, target = call_head(name, inp or {}).partition(":")
    if not target:
        return nm
    if "command" in (inp or {}) and PROGRAM.match(target):
        return f"{nm}:{target}"
    return f"{nm}:#{h(target)}"


def target_hash(text: "str | None", h: Hasher) -> "str | None":
    return None if text is None else "#" + h(str(text))
