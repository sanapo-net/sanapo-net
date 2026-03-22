# core/kernel.py
import asyncio

from core.bus import Bus
from core.orchestrator import Orchestrator
from core.data_buffer import DataBuffer
from core.settings import Settings

class Kernel:
    def __init__(self):
        self.loop = asyncio.get_event_loop()
        self.bus = Bus(self.loop)
        self.buffer = DataBuffer()
        self.settings = Settings()
        self.orchestrator = Orchestrator(self.bus.get_all, self.loop)

    def subscribe(self, event_type, cb):
        """method wrapper for orchestrator.subscribe()"""
        self.orchestrator.subscribe(event_type, cb)

    def emit(self, msg):
        """method wrapper for bus.send()"""
        self.bus.send(msg)

    async def launch(self):
        """core starter"""
        # it start core
        self.orchestrator.start()

        # send message for start
        self.emit({"event": "ENGINE_START", "interval": self.settings.ping_interval})

        while True:
            await asyncio.sleep(1)