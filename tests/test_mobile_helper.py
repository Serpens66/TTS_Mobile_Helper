import asyncio
import importlib
import json
import threading
import unittest
from types import SimpleNamespace
from urllib.parse import quote_plus
from unittest.mock import patch

import server_mobile_actions
from tts_api_chatgpt import AsyncExternalEditorApi


class MobileHelperTest(unittest.TestCase):
    helper = "abc123:1"
    zone = {
        "type": "global_snap",
        "snap_index": 1,
        "tag_key": "Discard",
        "position": {"x": 1, "y": 2, "z": 3},
        "name": "Discard",
    }

    def setUp(self):
        self.server = importlib.reload(server_mobile_actions)
        self.http = self.server.app.test_client()
        self.clock = 100
        self.sent = []
        self.clients = []
        self.server.time = SimpleNamespace(monotonic=lambda: self.clock)
        self.server.get_tts_api_chatgpt = lambda: SimpleNamespace(custom_message=self.sent.append)

    def tearDown(self):
        for client in self.clients:
            if client.is_connected():
                client.disconnect()

    def handshake(self, helper=None):
        response = self.http.post("/health", json={"helper": helper or self.helper})
        self.assertEqual(response.status_code, 200)
        self.run = response.json["run"]
        return response.json

    def post(self, path, sequence=1, **data):
        return self.http.post(path, json={
            "helper": self.helper, "run": self.run, "sequence": sequence, **data,
        })

    def snapshot(self, red=None, blue=None, zones=None, seated=None):
        return self.post(
            "/sync_snapshot", hands={"Red": red or [], "Blue": blue or []},
            hand_zone_colors=["Red", "Blue"], seated_colors=seated or [],
            drop_zones=zones or [], mobile_buttons=[],
        )

    def phone(self, color=None, identity=None):
        phone = self.server.socketio.test_client(self.server.app)
        self.clients.append(phone)
        if color:
            self.join(phone, color, identity or color)
            self.assertTrue(self.events(phone, "join_success"))
        return phone

    def join(self, phone, color, identity):
        phone.emit("join", {"color": color, "client_id": identity})

    def events(self, phone, name):
        return [event["args"][0] for event in phone.get_received() if event["name"] == name]

    def test_health_readiness_expiry_and_new_run(self):
        phone = self.phone("Red")
        self.assertEqual(self.http.get("/health").status_code, 200)
        self.assertFalse(self.server.lua_connection_status()["connected"])
        self.assertFalse(self.handshake()["ready"])
        old_run = self.run
        phone.emit("card_action", {"action": "flip_cards", "color": "Red", "guids": ["abcdef"]})
        self.assertFalse(self.events(phone, "card_action_result")[0]["ok"])
        self.assertEqual(self.sent, [])
        self.assertEqual(self.snapshot(red=[{"guid": "abcdef"}]).status_code, 200)
        self.assertTrue(self.events(phone, "lua_status")[-1]["ready"])
        self.clock += 10
        self.server.maintenance_once()
        self.assertEqual(self.events(phone, "lua_status")[-1], {"connected": False, "ready": False})
        self.assertFalse(self.handshake()["ready"])
        self.assertNotEqual(self.run, old_run)
        self.assertEqual(self.post("/update_hand", run=old_run, color="Red", cards=[]).status_code, 409)
        self.assertEqual(self.snapshot().status_code, 200)
        self.assertEqual(self.events(phone, "hand_updated")[-1]["cards"], [])
        self.assertTrue(self.server.table_ready)

    def test_reload_retires_old_helper_and_rejects_remote_updates(self):
        self.handshake()
        self.assertEqual(self.snapshot().status_code, 200)
        old_helper = self.helper
        self.helper = "abc123:2"
        self.assertFalse(self.handshake()["ready"])
        self.assertEqual(self.http.post("/health", json={"helper": old_helper}).status_code, 409)
        remote = self.http.post("/health", json={"helper": self.helper}, environ_overrides={"REMOTE_ADDR": "192.168.1.55"})
        self.assertEqual(remote.status_code, 403)

    def test_form_round_trip_and_atomic_validation(self):
        self.handshake()
        self.assertEqual(self.snapshot().status_code, 200)
        card = {"guid": "abcdef", "name": "%26 %22 %25 + = & café 中", "image": "http://example.test/a%20b.png?x=1&y=2", "face_down": False}
        for sequence, form in enumerate(("raw", "legacy", "named"), 1):
            body = json.dumps({"helper": self.helper, "run": self.run, "sequence": sequence, "color": "Red", "cards": [card]}, ensure_ascii=False)
            payload = body if form == "raw" else quote_plus(body) if form == "legacy" else {"payload": body}
            response = self.http.post("/update_hand", data=payload, content_type="application/x-www-form-urlencoded")
            self.assertEqual(response.status_code, 200, response.json)
            self.assertEqual(self.server.game_state["Red"][0]["name"], card["name"])
            self.assertEqual(self.server.game_state["Red"][0]["image"], card["image"])
        self.clock += 1
        before = self.server.last_lua_contact_at
        response = self.post("/update_hand", 4, cards=[], seated_colors=["Blue"])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.server.seated_colors, [])
        self.assertEqual(self.server.last_lua_contact_at, before)
        self.assertEqual(self.server.game_state["Red"][0]["guid"], "abcdef")
        self.assertEqual(self.post("/update_hand", 5, color="Red", cards=[{"guid": "abcdef", "face_down": 180}]).status_code, 400)

    def test_stale_updates_and_global_metadata(self):
        self.handshake()
        self.snapshot()
        red, blue = self.phone("Red"), self.phone("Blue")
        red.get_received()
        blue.get_received()
        self.assertEqual(self.post("/update_hand", 2, color="Red", cards=[{"guid": "abcdef"}]).status_code, 200)
        self.assertTrue(self.post("/update_hand", 1, color="Red", cards=[]).json["stale"])
        self.assertEqual(len(self.events(red, "hand_updated")), 1)
        self.assertFalse(self.events(blue, "hand_updated"))
        metadata = {"drop_zones": [], "mobile_buttons": [], "hand_zone_colors": ["Red", "Blue"], "seated_colors": ["Red"]}
        self.post("/update_table", **metadata)
        self.assertEqual(self.events(blue, "hand_updated")[-1]["seated_colors"], ["Red"])
        self.post("/update_table", 2, **metadata)
        self.assertFalse(self.events(blue, "hand_updated"))

    def test_rejected_switch_keeps_seat_and_parallel_claim_has_one_winner(self):
        red, blue = self.phone("Red"), self.phone("Blue")
        self.join(red, "Blue", "Red")
        self.assertTrue(self.events(red, "join_error"))
        self.assertEqual(self.server.color_owners["Red"], "Red")
        a, b = self.phone(), self.phone()
        barrier = threading.Barrier(2)

        def claim(phone, identity):
            barrier.wait()
            self.join(phone, "Green", identity)

        threads = [threading.Thread(target=claim, args=(phone, name)) for phone, name in [(a, "a"), (b, "b")]]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(2)
            self.assertFalse(thread.is_alive())
        results = [phone.get_received() for phone in (a, b)]
        self.assertEqual(sum(any(event["name"] == "join_success" for event in events) for events in results), 1)
        self.assertEqual(sum(any(event["name"] == "join_error" for event in events) for events in results), 1)

    def test_drop_target_identity_and_acknowledgment(self):
        self.handshake()
        self.snapshot(red=[{"guid": "abcdef"}], zones=[self.zone])
        red = self.phone("Red")
        action = {"color": "Red", "action": "play_to_zone", "guids": ["abcdef"]}
        red.emit("card_action", {**action, "target": json.dumps({**self.zone, "position": {"x": 5, "y": 2, "z": 3}})})
        self.assertFalse(self.events(red, "card_action_result")[0]["ok"])
        self.assertEqual(self.sent, [])
        red.emit("card_action", {**action, "target": json.dumps({**self.zone, "spread_cards": True})})
        self.assertTrue(json.loads(self.sent[0]["target"])["spread_cards"])
        self.assertFalse(self.events(red, "card_action_result"))
        self.post("/action_result", action_id=self.sent[0]["action_id"], result="ok")
        self.assertTrue(self.events(red, "card_action_result")[0]["ok"])

    def test_expired_selection_and_overlapping_confirmations(self):
        self.handshake()
        self.snapshot(blue=[{"guid": "abcdef"}])
        one, two = self.phone("Red", "same"), self.phone("Red", "same")
        blue = self.phone("Blue")
        one.emit("interaction_request", {"color": "Red", "target_color": "Blue", "interaction_type": "pick_open", "count": 1})
        request_id = next(iter(self.server.interaction_requests))
        blue.emit("interaction_response", {"color": "Blue", "request_id": request_id, "accepted": True})
        self.assertTrue(self.events(one, "interaction_open_pick"))
        for _ in range(self.server.INTERACTION_TTL_SECONDS // 3):
            self.clock += 3
            self.handshake()
        one.emit("interaction_open_selection_request", {"color": "Red", "request_id": request_id})
        self.assertFalse(self.events(one, "interaction_open_pick"))
        self.assertNotIn(request_id, self.server.interaction_requests)

        one.emit("interaction_request", {"color": "Red", "target_color": "Blue", "interaction_type": "pick_open", "count": 1})
        request_id = next(iter(self.server.interaction_requests))
        blue.emit("interaction_response", {"color": "Blue", "request_id": request_id, "accepted": True})
        event = {"color": "Red", "request_id": request_id, "guids": ["abcdef"]}

        def send(payload):
            self.sent.append(payload)
            if len(self.sent) == 1:
                two.emit("interaction_pick_cards", event)

        with patch.object(self.server, "get_tts_api_chatgpt", return_value=SimpleNamespace(custom_message=send)):
            one.emit("interaction_pick_cards", event)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.server.interaction_requests[request_id]["status"], "processing")
        self.post("/action_result", action_id=self.sent[0]["action_id"], result="ok")
        self.assertNotIn(request_id, self.server.interaction_requests)

    def test_timeout_does_not_resend_card_action(self):
        self.handshake()
        self.snapshot(red=[{"guid": "abcdef"}])
        red = self.phone("Red")
        red.emit("card_action", {"color": "Red", "action": "reorder_hand", "guids": ["abcdef"]})
        self.clock += 5
        self.handshake()
        self.clock += 5
        with patch.object(self.server.socketio, "start_background_task"):
            self.server.maintenance_once()
        self.assertFalse(self.events(red, "card_action_result")[-1]["ok"])
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.server.pending_actions, {})


class AdapterTest(unittest.IsolatedAsyncioTestCase):
    async def test_send_failure_timeout_and_cancellation_cleanup(self):
        api = AsyncExternalEditorApi(timeout=0.01, collect_events=False)

        async def send_failure(_):
            raise ConnectionRefusedError

        async def no_reply(_):
            pass

        with patch.object(api, "send", send_failure), self.assertRaises(ConnectionRefusedError):
            await api.execute("return 1")
        self.assertEqual(api._pending_returns, {})
        with patch.object(api, "send", no_reply), self.assertRaises(asyncio.TimeoutError):
            await api.execute_on_object("return 1", "abcdef")
        self.assertEqual(api._pending_returns, {})
        with patch.object(api, "send", no_reply):
            task = asyncio.create_task(api.execute("return 1"))
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(api._pending_returns, {})

    async def test_send_timeout_includes_waiting_for_other_commands(self):
        api = AsyncExternalEditorApi(timeout=0.01)
        async with api._send_lock:
            with patch("tts_api_chatgpt.asyncio.open_connection") as connect:
                with self.assertRaises(asyncio.TimeoutError):
                    await api.send({"messageID": 2})
                connect.assert_not_called()

    async def test_default_event_queue_is_preserved(self):
        class Reader:
            async def read(self):
                return b'{"messageID":6}'

        class Writer:
            def close(self):
                pass

            async def wait_closed(self):
                pass

        enabled = AsyncExternalEditorApi()
        disabled = AsyncExternalEditorApi(collect_events=False)
        for api in (enabled, disabled):
            await api._handle_client(Reader(), Writer())
        self.assertEqual(enabled.events.qsize(), 1)
        self.assertEqual(disabled.events.qsize(), 0)
