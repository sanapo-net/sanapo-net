# core/bus.py
import asyncio

class Bus:
    def __init__(self, loop):
        self._loop = loop
        self._queue = asyncio.Queue()

    def send(self, message):
        """wrapper for Thread-safe msg sending to bus from any Thread and Sync/Async"""
        try:
            self._queue.put_nowait(message)
        except (RuntimeError, AttributeError):
            # if self.send was called from another thread
            self._loop.call_soon_threadsafe(self._queue.put_nowait, message)

    async def get_all(self):
        """read all messages for orchestrator"""
        items = []
        while not self._queue.empty():
            items.append(await self._queue.get())
            self._queue.task_done()
        return items