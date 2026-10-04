import json
import unittest

from telemetry import catalog
from telemetry.catalog import EVENTS, FORBIDDEN, F, check_catalog
from telemetry.event import check, make
from telemetry.peer import message_event, peer_events, tokens_est

HEAD = {"schema": "notify/1", "id": "m1", "from": "Telemetry", "to": "baseline", "kind": "report"}


class Peer(unittest.TestCase):
    def test_valid_pair_passes(self):
        s, r = peer_events(HEAD, "run", 0)
        self.assertEqual((s["type"], r["type"]), ("peer.message.sent", "peer.message.received"))
        for e in (s, r):
            self.assertEqual(check(e), [])
            self.assertEqual(e["data"]["from_session"], "Telemetry")
            self.assertIn("in_reply_to", e["unobserved"])
        self.assertEqual(check_catalog(), [])

    def test_reply_and_json_text(self):
        e = message_event("peer.message.sent", json.dumps(dict(HEAD, in_reply_to="m0")), "r", 3)
        self.assertEqual(e["data"]["in_reply_to"], "m0")

    def test_forbidden_fields_refused(self):
        for bad in ("score", "pi", "trust", "usefulness"):
            with self.assertRaises(KeyError):
                make("peer.message.sent", "r", 0, "s", from_session="a", to_session="b", msg_id="m", **{bad: 1})
        for bad in ("score", "health", "decision"):                       # 이름 규율: 카탈로그에 넣으면 걸린다
            ev = {"peer.message.sent": dict(EVENTS["peer.message.sent"], **{bad: F("num", "reported")})}
            self.assertTrue(check_catalog(ev), bad)
        self.assertLessEqual({"score", "health"}, FORBIDDEN)
        self.assertFalse({"score", "trust"} & set(EVENTS["peer.message.sent"]))

    def test_new_events_obey_forbidden_check(self):
        for t in ("peer.message.sent", "peer.message.received"):
            self.assertEqual(check_catalog({t: EVENTS[t]}), [])
            bad = {t: dict(EVENTS[t], score=F("num", "measured"))}
            self.assertTrue(any("score" in e for e in check_catalog(bad)))

    def test_missing_msg_id_refused(self):
        with self.assertRaises(ValueError):
            message_event("peer.message.sent", {k: v for k, v in HEAD.items() if k != "id"}, "r", 0)
        with self.assertRaises(ValueError):
            make("peer.message.received", "r", 0, "s", from_session="a", to_session="b", schema="x/1", bytes=1, tokens_est=1)
        e = make("peer.message.sent", "r", 0, "s", from_session="a", to_session="b", msg_id="m", schema="x/1", bytes=4, tokens_est=1)
        e["data"]["msg_id"] = None
        e["unobserved"].append("msg_id")
        self.assertTrue(check(e))

    def test_tokens_est_is_ceil(self):
        self.assertEqual([tokens_est(n) for n in (0, 1, 4, 5, 8, 9)], [0, 1, 1, 2, 2, 3])
        for n in range(1, 40):
            self.assertEqual(tokens_est(n), -(-n // 4))
        e = message_event("peer.message.sent", HEAD, "r", 0)
        n = e["data"]["bytes"]
        self.assertEqual(n, len(json.dumps(HEAD, sort_keys=True, separators=(",", ":")).encode()))
        self.assertEqual(e["data"]["tokens_est"], -(-n // 4))
        e2 = message_event("peer.message.sent", dict(HEAD, id="m12"), "r", 0)        # 길이 +1 → ceil 이 갈린다
        self.assertEqual(e2["data"]["tokens_est"], -(-e2["data"]["bytes"] // 4))

    def test_no_ga_import(self):
        import telemetry.peer as p
        self.assertNotIn("ga", [m.split(".")[0] for m in vars(p) if False] + ["x"])
        src = open(p.__file__, encoding="utf-8").read()
        self.assertNotRegex(src, r"(?m)^\s*(import|from)\s+ga\b")
