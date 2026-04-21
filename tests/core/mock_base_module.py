# /tests/core/mock_base_module.py
from __future__ import annotations
import time
import itertools
from typing import TYPE_CHECKING
from concurrent.futures import ThreadPoolExecutor

from core.enums import EvtType, CmdType, RptType
from tests.common import FloatGenerator, PersistentGenerator

if TYPE_CHECKING:
    from main import Tools
    from core.logger import Logger
    from core.secretary import Secretary

def generate_mock_names():
    speeds = ['L', 'H']  # Low / High
    drivers = ['M', 'S'] # Module / Secretary (loop)
    threads = ['T', '_'] # ThreadPool / NoThreadPool
    combinations = itertools.product(speeds, drivers, threads)
    return ["".join(combo) for combo in combinations]

trace_log = [] #[{'ts': float, 'who': str, 'act': str, 'type': str, 'id': str, 'target': str},...]
mock_module_settings = {
    "speed_fast": {True: (0.001, 0.05, 0.01), False: (0.01, 0.5, 0.1)},
    "evt_freq": 10,
    "cmd_freq": 10,
    "recipients": []
}

class BaseMockModule:
    def __init__(self, tools: Tools, logger: Logger, secr: Secretary,
                name_code: str, mock_module_settings: dict[str, any]):
        self._secr = secr
        self._log  = logger
        self._code = name_code
        self._addr = secr.address
        
        # Parsing properties
        self._is_fast = 'L' in name_code
        self._module_leads = 'M' in name_code
        self._has_threads = 'T' in name_code

        # Iteration settings (can be changed by the test)
        self.cmd_freq = mock_module_settings["cmd_freq"]
        self.evt_freq = mock_module_settings["evt_freq"]
        
        # Simulation of operation (CandleGenerator for realistic jitter)
        work_params = self._is_fast = mock_module_settings["speed_higt"][self._is_fast]
        self._other_work_gen = FloatGenerator(f"mock_{name_code}_other_work", *work_params)
        self._task_work_gen = FloatGenerator(f"mock_{name_code}_task_work", *work_params)
        
        # Random Target Generator (Reproducible)
        self._target_gen = PersistentGenerator(f"mock_{name_code}_targets")

        self._cycle_count = 0
        self._is_running = True
        self._tick_interval = tools.config.MODULE_TICK_TCT_DEFAULT

        # Pool management (T flag)
        if self._has_threads:
            self._pool = ThreadPoolExecutor(max_workers=5)

        # Subscriptions
        self._secr.configure_subscriptions(
            events={EvtType.EVT_TEST: self._on_evt_test},
            commands={CmdType.CMD_TEST: self._on_cmd_test}
        )

    def start(self) -> None:
        if self._module_leads and not self._is_running:
            self._is_running = True

    def stop(self) -> None:
        self._is_running = False
    
    def step(self) -> None:
        """Life Cycle Simulation"""
        self._cycle_count += 1
        
        # 1. The hard work of an independent module
        if self._module_leads:
            time.sleep(self._other_work_gen.next())

        # 2. Desire to send a command
        if self.cmd_freq > 0 and (self._cycle_count % self.cmd_freq == 0):
            # Select a target from the global list (must be available in the test)
            addrs = mock_module_settings["recipients"]
            available_targets = [a for a in addrs if a != self._addr]
            if available_targets:
                target = self._target_gen._rnd.choice(available_targets)
                msg_id = f"{self._addr}_{self._cycle_count}"
                self._secr.send_cmd(
                    target, CmdType.CMD_TEST, cb=self._on_cmd_done, payload={"msg_id": msg_id})
                self._trace("sent", "CMD", msg_id, target.name)

        # 3. Desire to send an event
        if self.evt_freq > 0 and (self._cycle_count % self.evt_freq == 0):
            msg_id = f"{self._addr}_{self._cycle_count}"
            self._secr.send_evt(EvtType.EVT_TEST, payload={"msg_id": msg_id})
            self._trace("sent", "EVT", msg_id)

    def worker_loop(self):
        """An outer loop started by the Kernel in a thread."""
        if self._module_leads:
            while self._is_running:
                start_ts = time.perf_counter()
                self.step()
                self._secr.step()
                elapsed = time.perf_counter() - start_ts
                time.sleep(max(0, self._tick_interval - elapsed))

    def _trace(self, action: str, msg_type: str, msg_id: str, target: str = ""):
        """Recording into a single log for subsequent construction of statistical matrices."""
        trace_log.append({
            "ts": time.perf_counter(),
            "who": self._code,
            "action": action,   # 'sent', 'received'
            "type": msg_type,
            "id": msg_id,
            "target": target
        })

    def _on_evt_test(self, frame):
        self._trace("received", "EVT", frame.payload.get("evt_id"))

    def _on_cmd_test(self, frame):
        self._trace("received", "CMD", frame.cmd_id)
        
        def do_work():
            time.sleep(self._task_work_gen.next())
            self._secr.send_rpt(frame.sender, frame.cmd_id, RptType.DONE)
            self._trace("sent", "RPT", frame.cmd_id, frame.sender.name)

        if self._has_threads:
            self._pool.submit(do_work)
        else:
            do_work()

    def _on_cmd_done(self, frame):
        self._trace("received", "RPT", frame.cmd_id)
