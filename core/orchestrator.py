# core/orchestrator.py
import threading
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict

class Orchestrator(threading.Thread):
    def __init__(self, fetch_func, main_loop):
        super().__init__(daemon=True)
        self.fetch_func = fetch_func
        self.main_loop = main_loop
        # subscribe dict: { "EVENT_TYPE": [callback1, callback2] }
        self.subscribers = defaultdict(list)
        self.executor = ThreadPoolExecutor(max_workers=20)
        self.tick_rate = 0.025

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._main_loop())

    async def _main_loop(self):
        while True:
            start_time = time.perf_counter()
            messages = await self.fetch_func()

            for msg in messages:
                event_type = msg.get("event")
                if event_type in self.subscribers:
                    for cb in self.subscribers[event_type]:
                        self._dispatch(cb, msg)

            wait = self.tick_rate - (time.perf_counter() - start_time)
            await asyncio.sleep(max(0, wait))

    def _dispatch(self, cb, msg):
        if asyncio.iscoroutinefunction(cb):
            asyncio.run_coroutine_threadsafe(cb(msg), self.main_loop)
        else:
            self.executor.submit(cb, msg)

    def subscribe(self, event_type, cb):
        self.subscribers[event_type].append(cb)
