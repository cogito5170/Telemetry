"""세션 사이 메시지 -> L0 사건 (CMD-NET1). ga 를 import 하지 않는다 -- 와이어 머리(head)의 JSON(dict 또는 글)만 받는다.

    sent, received = peer_events(head, run_id, seq, source="peer")      # 보낸 쪽 · 받은 쪽 사건 한 쌍
    message_event("peer.message.sent", head, run_id, seq, source)        # 한쪽만

머리의 칸: schema · id · from · to · in_reply_to (없으면 from_session= 같은 인자로 준다). 해석은 하지 않는다.
bytes 는 머리를 정준 JSON(키 정렬 · 공백 없음 · UTF-8)으로 쓴 길이, tokens_est = ceil(bytes/4).
"""
from __future__ import annotations

import json

from .event import make


def tokens_est(nbytes: int) -> int:
    return -(-nbytes // 4)


def message_event(type: str, head, run_id: str, seq: int, source: str = "peer", at=None, time_base=None,
                  from_session=None, to_session=None) -> dict:
    if type not in ("peer.message.sent", "peer.message.received"):
        raise KeyError(f"세션 메시지 사건이 아니다: {type!r}")
    if isinstance(head, (str, bytes)):
        head = json.loads(head)
    if not isinstance(head, dict):
        raise ValueError("머리는 JSON 객체여야 한다")
    n = len(json.dumps(head, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    return make(type, run_id, seq, source, at=at, time_base=time_base,
                from_session=from_session or head.get("from"), to_session=to_session or head.get("to"),
                msg_id=head.get("id"), in_reply_to=head.get("in_reply_to"), schema=head.get("schema"),
                bytes=n, tokens_est=tokens_est(n))


def peer_events(head, run_id: str, seq: int = 0, source: str = "peer", **kw) -> "tuple[dict, dict]":
    return (message_event("peer.message.sent", head, run_id, seq, source, **kw),
            message_event("peer.message.received", head, run_id, seq + 1, source, **kw))
