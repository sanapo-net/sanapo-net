# core/kernel.py
import asyncio

from core.enums import Addr, CmdType, AddressBusyError
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
        self.messenger.subscribe(self.stop, cmd_type = CmdType.STOP_APP)

    def stop(self, frame=None):
        """
        Stop the entire application.
        Can be called by a command STOP_APP from the bus or manually.
        """
        if frame:
            print(f"[Kernel] Stop signal received from {frame.sender}")
        
        print("[Kernel] Initiating shutdown...")
        
        # 3. Stop the orchestrator's thread and loop
        self.orchestrator.stop()
        
        # 4. Wait for threads to finish (max 2 seconds)
        if self.orchestrator.is_alive():
            self.orchestrator.join(timeout=2.0)
            
        print("[Kernel] System halted.")

    async def launch(self):
        """core starter"""
        self.orchestrator.start()
        while True:
            await asyncio.sleep(1)