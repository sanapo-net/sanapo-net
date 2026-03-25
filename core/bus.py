# core/bus.py
import asyncio

from core.protocol import Frame
from core.enums import MsgType, Addr, EvtType

BUS_GET_ALL_LIMIT = 200

class Bus:
    def __init__(self, loop):
        self._loop = loop
        self._queue = asyncio.Queue()

    def send(self, message):
        """
        Thread-safe message delivery to the bus.

        Supports sending from any thread and both sync/async contexts.
        """
        try:
            self._queue.put_nowait(message)
        except (RuntimeError, AttributeError):
            # If self.send was called from another thread
            self._loop.call_soon_threadsafe(self._queue.put_nowait, message)

    async def get_all(self):
        """
        Read up to limit messages to keep tick rate stable

        If limit is achieved, publication event
        """
        items = []
        while len(items) < BUS_GET_ALL_LIMIT:
            try:
                msg = self._queue.get_nowait()
                #msg = await self._queue.get()
                items.append(msg)
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break
        if len(items) == BUS_GET_ALL_LIMIT:
            msg = Frame(
                msg_type = MsgType.EVENT,
                sender = Addr.BUS,
                evt_type = EvtType.BUS_IS_OVERCROWDED
            )
            self.send(msg)
        return items