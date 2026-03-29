# core/kernel.py
import asyncio
from dataclasses import dataclass
from typing import Callable, Any
from queue import Queue, Empty
import time

from core.enums import Addr, MsgType, CmdType, EvtType, AddressBusyError, UnknownRecipientError
from core.buffer import Buffer
from core.config import Config
from network.network import Network
from core.protocol import Frame

# ToDo: add new property form Network and Buffer
@dataclass(frozen=True)
class ModuleTools:
    """Data proxy object for modules. For Principle of Least Privilege"""
    inbox: Queue          # Incoming messages for the module to process
    outbox: Queue         # Outgoing messages from the module to the bus
    config: Any           # Global configuration settings
    get_metrics: Callable # Method to retrieve a buffer snapshot
    network_ver: int      # Version of network for change checking
    network_tab: dict     # Dict of net interfaces into network

class Kernel:
    def __init__(self):
        self.config = Config()
        self.buffer = Buffer()
        self.network = Network()
        self.bus = Queue() 
        self.registry = {} # modele queues {Addr: Queue, ...}
        self.is_running = True

    # ToDo: give property by Principle of Least Privilege (PoLP)
    def get_tools(self, addr: Addr) -> ModuleTools:
        """Register the data-proxy object and provide it to the module."""
        if not isinstance(addr, Addr):
            raise UnknownRecipientError(f"Address '{addr}' is not defined in Addr enum.")
        if addr in self.registry:
            raise AddressBusyError(f"Address '{addr}' is already registered by another module.")
        inbox = Queue()
        self.registry[addr] = inbox
        return ModuleTools(
            inbox=inbox,
            outbox=self.bus,
            config=self.config,
            get_metrics=lambda: self.buffer.snapshot,
            network_ver=self.network.network_ver,
            network_tab=self.network.network_tab
        )
    
    # ToDo: missing recipient
    def route_messages(self):
        """
        Main mail sorter (Main Thread).
        Processes the incoming bus and distributes messages to module inboxes.
        """
        now = time.perf_counter()
        q_size = self.bus.qsize()

        # 1. Backpressure protection - once every 1 second
        if q_size > self.config.BUS_READ_LIMIT:
            if now - self._last_overcrowded_alert > 1.0:
                alert_frame=Frame(
                    msg_type=MsgType.EVENT,
                    sender=Addr.KERNEL,
                    evt_type=EvtType.BUS_IS_OVERCROWDED,
                    payload=f"Current bus size: {q_size}"
                )
                self.bus.put_nowait(alert_frame)
                self._last_overcrowded_alert = now
                print(f"[WARNING] Bus overcrowded! Size: {q_size}")

        # 2. Message parsing cycle
        processed_count = 0
        try:
            while not self.bus.empty() and processed_count < self.config.BUS_READ_LIMIT:
                frame = self.bus.get_nowait()
                processed_count += 1

                # If it is a stop command
                if frame.cmd_type == CmdType.APP_STOP:
                    self.stop(frame)
                    break

                # If metrics: push to buffer immediately
                # ToDo: this needs refactoring
                if frame.msg_type == MsgType.DATA:
                    self.buffer.update(frame.payload)

                # Routing
                # For Command and Report
                if frame.recipient:
                    if frame.recipient in self.registry:
                        self.registry[frame.recipient].put_nowait(frame)
                # For Event
                else:
                    for addr, inbox in self.registry.items():
                        # Do not send the event back to the sender
                        if addr != frame.sender:
                            inbox.put_nowait(frame)
                            
        except Empty:
            pass
        except Exception as e:
            print(f"[ERROR] Routing failed: {e}")


    def stop(self):
        print("[Kernel] Shutdown initiated...")
        self.is_running = False

    async def launch(self):
        """core starter"""
        print("[Kernel] Running...")
        while self.is_running:
            self.route_messages()
            await asyncio.sleep(self.config.CORE_TICK_RATE)
        print("[Kernel] Halted.")
