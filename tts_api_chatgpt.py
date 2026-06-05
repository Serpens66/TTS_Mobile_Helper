# tts_api_chatgpt.py
# based on https://github.com/LucasOe/tts-external-api/tree/master

import asyncio
import itertools
import json
import socket
import threading
from dataclasses import dataclass
from typing import Any, Optional


MESSAGE_GET_SCRIPTS = 0
MESSAGE_RELOAD = 1
MESSAGE_CUSTOM_MESSAGE = 2
MESSAGE_EXECUTE = 3

ANSWER_NEW_OBJECT = 0
ANSWER_RELOAD = 1
ANSWER_PRINT = 2
ANSWER_ERROR = 3
ANSWER_CUSTOM_MESSAGE = 4
ANSWER_RETURN = 5
ANSWER_GAME_SAVED = 6
ANSWER_OBJECT_CREATED = 7


@dataclass
class NewObjectAnswer:
    script_states: Any


@dataclass
class ReloadAnswer:
    save_path: str
    script_states: Any


@dataclass
class PrintAnswer:
    message: str


@dataclass
class ErrorAnswer:
    error: str
    guid: str
    error_message_prefix: str


@dataclass
class CustomMessageAnswer:
    custom_message: Any


@dataclass
class ReturnAnswer:
    return_id: int
    return_value: Any


@dataclass
class GameSavedAnswer:
    pass


@dataclass
class ObjectCreatedAnswer:
    guid: str


class AsyncExternalEditorApi:
    def __init__(
        self,
        host: str = "127.0.0.1",
        receive_port: int = 39998,
        send_port: int = 39999,
        timeout: float = 10.0,
        debug_incoming: bool = False,
        debug_outgoing: bool = False,
    ):
        self.host = host
        self.receive_port = receive_port
        self.send_port = send_port
        self.timeout = timeout

        self.debug_incoming = debug_incoming
        self.debug_outgoing = debug_outgoing

        self._return_ids = itertools.count(1)
        self._server: Optional[asyncio.AbstractServer] = None

        self._send_lock = asyncio.Lock()
        self._pending_returns: dict[int, asyncio.Future] = {}
        self.events: asyncio.Queue = asyncio.Queue()

    async def start(self):
        self._server = await asyncio.start_server(
            self._handle_client,
            self.host,
            self.receive_port,
            reuse_address=True,
        )
        return self

    async def close(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            raw = await reader.read()
            if not raw:
                return

            msg = json.loads(raw.decode("utf-8"))
            answer = self.parse_answer(msg)

            if self.debug_incoming:
                print("\n" + "=" * 60)
                print("[TTS -> PYTHON]")
                print(json.dumps(msg, indent=2, ensure_ascii=False))
                print("=" * 60)

            if msg.get("messageID") == ANSWER_RETURN:
                return_id = msg.get("returnID")
                future = self._pending_returns.pop(return_id, None)
                if future and not future.done():
                    future.set_result(answer)

            await self.events.put(answer)

        except Exception as e:
            await self.events.put(e)

        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def send(self, message: dict) -> None:
        async with self._send_lock:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.send_port),
                timeout=self.timeout,
            )
            if self.debug_outgoing:
                print("\n" + "=" * 60)
                print("[PYTHON -> TTS]")
                print(json.dumps(message, indent=2, ensure_ascii=False))
                print("=" * 60)
            writer.write(json.dumps(message).encode("utf-8"))
            await writer.drain()

            writer.close()
            await writer.wait_closed()

    async def execute(self, script: str) -> ReturnAnswer:
        return_id = next(self._return_ids)
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending_returns[return_id] = future

        await self.send({
            "messageID": MESSAGE_EXECUTE,
            "returnID": return_id,
            "guid": "-1",
            "script": script,
        })

        return await asyncio.wait_for(future, timeout=self.timeout)

    async def execute_on_object(self, script: str, guid: str) -> ReturnAnswer:
        return_id = next(self._return_ids)
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending_returns[return_id] = future

        await self.send({
            "messageID": MESSAGE_EXECUTE,
            "returnID": return_id,
            "guid": guid,
            "script": script,
        })

        return await asyncio.wait_for(future, timeout=self.timeout)

    async def execute_nowait(self, script: str) -> None:
        return_id = next(self._return_ids)

        await self.send({
            "messageID": MESSAGE_EXECUTE,
            "returnID": return_id,
            "guid": "-1",
            "script": script,
        })

    async def custom_message(self, custom_message: Any) -> None:
        await self.send({
            "messageID": MESSAGE_CUSTOM_MESSAGE,
            "customMessage": custom_message,
        })

    async def read_answer(self):
        return await self.events.get()

    async def messages(self):
        while True:
            yield await self.read_answer()

    @staticmethod
    def _parse_return_value(value):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return value
        return value

    def parse_answer(self, msg: dict):
        message_id = msg.get("messageID")

        if message_id == ANSWER_NEW_OBJECT:
            return NewObjectAnswer(msg.get("scriptStates"))

        if message_id == ANSWER_RELOAD:
            return ReloadAnswer(
                save_path=msg.get("savePath", ""),
                script_states=msg.get("scriptStates"),
            )

        if message_id == ANSWER_PRINT:
            return PrintAnswer(msg.get("message", ""))

        if message_id == ANSWER_ERROR:
            return ErrorAnswer(
                error=msg.get("error", ""),
                guid=msg.get("guid", ""),
                error_message_prefix=msg.get("errorMessagePrefix", ""),
            )

        if message_id == ANSWER_CUSTOM_MESSAGE:
            return CustomMessageAnswer(msg.get("customMessage"))

        if message_id == ANSWER_RETURN:
            return ReturnAnswer(
                return_id=msg.get("returnID", 0),
                return_value=self._parse_return_value(msg.get("returnValue")),
            )

        if message_id == ANSWER_GAME_SAVED:
            return GameSavedAnswer()

        if message_id == ANSWER_OBJECT_CREATED:
            return ObjectCreatedAnswer(msg.get("guid", ""))

        return msg


class ExternalEditorApi:
    """
    Thread-safe Wrapper fuer normale Flask-/SocketIO-Skripte.
    Intern laeuft asyncio in einem eigenen Thread.
    """

    def __init__(self, *args, **kwargs):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
        )
        self._thread.start()

        self._api = AsyncExternalEditorApi(*args, **kwargs)

        self._run(self._api.start())

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run(self, coro):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    def execute(self, script: str) -> ReturnAnswer:
        return self._run(self._api.execute(script))

    def execute_nowait(self, script: str):
        return asyncio.run_coroutine_threadsafe(
            self._api.execute_nowait(script),
            self._loop,
        )

    def execute_on_object(self, script: str, guid: str) -> ReturnAnswer:
        return self._run(self._api.execute_on_object(script, guid))

    def custom_message(self, custom_message: Any) -> None:
        return self._run(self._api.custom_message(custom_message))

    def read_answer(self):
        return self._run(self._api.read_answer())

    def close(self):
        self._run(self._api.close())
        self._loop.call_soon_threadsafe(self._loop.stop)
