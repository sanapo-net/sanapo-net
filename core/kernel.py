# core/kernel.py
import asyncio

from core.enums import Addr, AddressBusyError
from core.bus import Bus
from core.orchestrator import Orchestrator
from core.buffer import Buffer
from core.settings import Settings

class Kernel:
    def __init__(self):
        self.loop = asyncio.get_event_loop()
        self.bus = Bus(self.loop)
        self.buffer = Buffer()
        self.settings = Settings()
        self.orchestrator = Orchestrator(self.bus.get_all)
        try:
            self.msg = self.orchestrator.connect(Addr.KERNEL)
        except AddressBusyError:
            print("Kernel is registred already!")
            return

    async def launch(self):
        """core starter"""
        self.orchestrator.start()
        while True:
            await asyncio.sleep(1)