# core/orchestrator.py
import threading
import asyncio
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from core.enums import Addr, MsgType, AddressBusyError, MessageTypeError
from core.messenger import Messenger

TICK_RATE = 0.025 # seconds
THREAD_POOL_MAX_SIZE = 20

class Orchestrator(threading.Thread):
    def __init__(self, bus):
        super().__init__(daemon=True)
        self.bus = bus
        self._registry = {}     # {Addr: Messenger, ...}
        self._subscribers = defaultdict(list) # {EentType: [callbacks], ...}
        self.executor = ThreadPoolExecutor(max_workers = THREAD_POOL_MAX_SIZE)
        self.loop = None # for event_loop

    def connect(self, address: Addr) -> Messenger:
        """Messenger creating wuth Address checking"""
        if address in self._registry:
            raise AddressBusyError(f"Address {address} is already taken")

        messenger = Messenger(address, self.bus, self)
        self._registry[address] = messenger
        return messenger

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._main_loop())
        finally:
            self.loop.close()

    async def _main_loop(self):
        # Tick time calc
        next_tick_time = self.loop.time()
        while True:
            next_tick_time += TICK_RATE

            # Bus reading
            messages = await self.bus.get_all()
            for msg in messages:
                msg_type = msg.msg_type

                # For commands and reports
                if msg_type in [MsgType.COMMAND, MsgType.REPORT]:
                    target = self._registry.get(msg.recipient)
                    if msg_type == MsgType.COMMAND:
                        handler = target._handle_incoming_command
                    else:
                        handler = target._handle_incoming_report
                    self._dispatch(handler, msg)

                # For events
                elif msg.msg_type == MsgType.EVENT:
                    for messenger in self._registry.values():
                        self._dispatch(messenger._handle_incoming_event, msg)

                else:
                    raise MessageTypeError(f"MessageTypeError: {msg.msg_type}")

            # Tick time calc
            now_time = self.loop.time()
            wait_time = next_tick_time - now_time
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            else:
                next_tick_time = now_time

    def _dispatch(self, handler, msg):
        """Put task to the messenger"""
        self.executor.submit(handler, msg)