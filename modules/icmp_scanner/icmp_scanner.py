# modules/icmp_scanner/icmp_scanner.py
from __future__ import annotations
import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from icmplib import async_ping

from sanapo.base_module import BaseModule
from common.config import Config
from common.enums import EvtType, SpeedShiftICMP, TickInterval

if TYPE_CHECKING:
    from sanapo.protocol import Frame
    from sanapo.base_unit import UnitModuleView

MAX_CONCURRENT_PINGS = 2000

ALLOWED_INTERVALS: List[TickInterval] = [
    TickInterval.SEC_1,
    TickInterval.SEC_2,
    TickInterval.SEC_4,
    TickInterval.SEC_8,
    TickInterval.SEC_24,
]

BIG_TICKS = [
    (120, EvtType.TICK_120),
    (600, EvtType.TICK_600),
    (3600, EvtType.TICK_HOUR),
    (86400, EvtType.TICK_DAY),
]

PING_START_DELAY_RULES = [
    (2000, 0.00005),
    (1000, 0.0001),
    (500,  0.0002),
    (250,  0.0005),
    (0,    0.001),
]

DEFAULT_TIMEOUT = 0.5


@dataclass
class HostState:
    uid: int
    ip: str
    interval: TickInterval
    timeout: float
    effective_interval: TickInterval = field(init=False, default=TickInterval.SEC_1)
    effective_timeout: float = field(init=False, default=0.5)
    current_scan_interval: Optional[TickInterval] = None
    last_rtt: Optional[float] = None
    ready_to_report: bool = False
    scan_start_tick_id: int = 0 # tick id when the scan started


class ScannerICMP(BaseModule):
    def __init__(self, unit_view: UnitModuleView) -> None:
        super().__init__(unit_view)
        self.settings = Config

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self.tick_id: int = 0
        self.snapshot_ver: int = 0 # network snapshot version
        self._registry: Dict[int, HostState] = {}
        self._pending_tasks: Dict[int, asyncio.Task] = {}
        self._semaphore: asyncio.Semaphore = None
        self._input_queue: asyncio.Queue = None
        self._stop_async: asyncio.Event = None

        self._scanning_enabled: bool = False
        self._speed_shift: SpeedShiftICMP = SpeedShiftICMP.NORMAL
        self._intervals: List[TickInterval] = ALLOWED_INTERVALS
        self._last_big_tick_sent: Dict[int, int] = {period: -1 for period, _ in BIG_TICKS}
        self._start_delay: float = 0.001
        self._warned_icmplib: bool = False

        self.v.secr.configure_subscriptions(events={
            EvtType.NEW_NETWORK_VER: self._on_new_network,
            EvtType.NEW_ICMP_RATE: self._on_new_rate,
            EvtType.ICMP_SCAN_START: self._on_scan_start,
            EvtType.ICMP_SCAN_STOP: self._on_scan_stop,
        })

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> bool:
        if self._loop is not None:
            return True
        self._loop = asyncio.new_event_loop()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> bool:
        self.v.stop_timeout = 1.1
        if self._loop is None:
            return True
        if self._loop.is_running() and hasattr(self, '_stop_async'):
            self._loop.call_soon_threadsafe(self._stop_async.set)
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._loop.close()
        self._loop = None
        self._thread = None
        return True

    def define_manifest(self) -> dict:
        return {
            "version": "1.0.0",
            "role": "icmp_scanner",
            "is_public": False,
            "is_persistent": True,
        }

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------
    def _on_new_network(self, frame: Frame) -> None:
        asyncio.run_coroutine_threadsafe(self._input_queue.put(frame), self._loop)

    def _on_new_rate(self, frame: Frame) -> None:
        asyncio.run_coroutine_threadsafe(self._input_queue.put(frame), self._loop)

    def _on_scan_start(self, frame: Frame) -> None:
        asyncio.run_coroutine_threadsafe(self._input_queue.put(frame), self._loop)

    def _on_scan_stop(self, frame: Frame) -> None:
        asyncio.run_coroutine_threadsafe(self._input_queue.put(frame), self._loop)

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------
    def _run_event_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._async_main())

    async def _async_main(self) -> None:
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_PINGS)
        self._input_queue = asyncio.Queue()
        self._stop_async = asyncio.Event()
        self._pending_tasks.clear()

        try:
            await asyncio.gather(
                self._process_events(),
                self._tick_scheduler(),
            )
        finally:
            for task in self._pending_tasks.values():
                task.cancel()
            if self._pending_tasks:
                await asyncio.gather(*self._pending_tasks.values(), return_exceptions=True)
            self._pending_tasks.clear()

    # ------------------------------------------------------------------
    # Event processing
    # ------------------------------------------------------------------
    async def _process_events(self) -> None:
        while not self._stop_async.is_set():
            try:
                frame: Frame = await asyncio.wait_for(self._input_queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            if frame.msg_type.value == "evt":
                kind = frame.evt_type
                if kind == EvtType.NEW_NETWORK_VER:
                    await self._handle_new_network(frame)
                elif kind == EvtType.NEW_ICMP_RATE:
                    await self._handle_new_rate(frame)
                elif kind == EvtType.ICMP_SCAN_START:
                    await self._handle_scan_start(frame)
                elif kind == EvtType.ICMP_SCAN_STOP:
                    await self._handle_scan_stop(frame)

    async def _handle_new_network(self, frame: Frame) -> None:
        snapshot = frame.payload.get("snapshot")
        if not snapshot:
            self.v.log.err("NEW_NETWORK_VER without snapshot")
            return
        tab = snapshot.get("tab") if isinstance(snapshot, dict) else None
        if tab is None:
            self.v.log.err("NEW_NETWORK_VER: Snapshot without 'tab'")
            return
        self.snapshot_ver = snapshot.get("ver", 0)
        await self._rebuild_registry(tab)

    async def _handle_new_rate(self, frame: Frame) -> None:
        new_shift = frame.payload.get("icmp_speed_shift", SpeedShiftICMP.NORMAL)
        if new_shift != self._speed_shift:
            self._apply_speed_shift(new_shift)

    async def _handle_scan_start(self, frame: Frame) -> None:
        if not self._scanning_enabled:
            self._scanning_enabled = True
            self.v.log.inf("ICMP scanning started")

    async def _handle_scan_stop(self, frame: Frame) -> None:
        if self._scanning_enabled:
            self._scanning_enabled = False
            self.v.log.inf("ICMP scanning stopped")

            ready_hosts = [h for h in self._registry.values() if h.ready_to_report]
            if ready_hosts:
                results = []
                for h in ready_hosts:
                    results.append({
                        "uid": h.uid,
                        "rtt": h.last_rtt,
                        "effective_interval": int(h.current_scan_interval.value) if h.current_scan_interval else 0
                    })
                    h.ready_to_report = False
                    h.current_scan_interval = None
                try:
                    self._send_report(results)
                except Exception as e:
                    self.v.log.err(f"Failed to send ICMP report: {e}")

            for task in self._pending_tasks.values():
                task.cancel()
            if self._pending_tasks:
                await asyncio.gather(*self._pending_tasks.values(), return_exceptions=True)
            self._pending_tasks.clear()

            for h in self._registry.values():
                h.ready_to_report = False
                h.current_scan_interval = None

    # ------------------------------------------------------------------
    # Host registry
    # ------------------------------------------------------------------
    async def _rebuild_registry(self, tab: Dict[int, Dict[str, Any]]) -> None:
        new_uids = set(tab.keys())

        for uid in list(self._registry.keys()):
            if uid not in new_uids:
                if uid in self._pending_tasks:
                    self._pending_tasks[uid].cancel()
                    self._pending_tasks.pop(uid, None)
                del self._registry[uid]

        for uid, dev_data in tab.items():
            base_interval = dev_data.get("icmp_interval")
            if not isinstance(base_interval, TickInterval):
                try:
                    base_interval = TickInterval(int(base_interval))
                except (ValueError, TypeError):
                    self.v.log.wrn(f"Invalid interval {base_interval} for uid {uid}, skipping")
                    continue

            if base_interval not in self._intervals:
                self.v.log.wrn(f"Unsupported interval {base_interval} for uid {uid}, skipping")
                continue

            preferred_timeout = dev_data.get("timeout", DEFAULT_TIMEOUT)
            timeout = self._select_timeout(base_interval.value, preferred_timeout)

            if uid in self._registry:
                h = self._registry[uid]
                h.ip = dev_data["ip"]
                h.interval = base_interval
                h.timeout = timeout
                self._update_effective_params(h)
            else:
                h = HostState(
                    uid=uid,
                    ip=dev_data["ip"],
                    interval=base_interval,
                    timeout=timeout,
                )
                self._update_effective_params(h)
                self._registry[uid] = h

        self._update_start_delay()
        self.v.log.inf(f"Registry rebuilt with {len(self._registry)} hosts")

    def _apply_speed_shift(self, new_shift: SpeedShiftICMP) -> None:
        self._speed_shift = new_shift
        for host in self._registry.values():
            self._update_effective_params(host)
        self.v.log.inf(f"SpeedShift changed to {new_shift}")

    def _shift_interval(self, current: TickInterval, shift: SpeedShiftICMP) -> TickInterval:
        try:
            idx = self._intervals.index(current)
            new_idx = idx + shift.value
            new_idx = max(0, min(new_idx, len(self._intervals) - 1))
            return self._intervals[new_idx]
        except ValueError:
            return current

    def _select_timeout(self, base_interval_sec: float, preferred_timeout: float) -> float:
        """
        Selects the maximum timeout from Config.ICMP_TIMEOUTS
        that does not exceed preferred_timeout and is less than base_interval.
        """
        max_allowed = min(preferred_timeout, base_interval_sec)
        candidates = [t for t in Config.ICMP_TIMEOUTS if t <= max_allowed]
        return max(candidates) if candidates else Config.ICMP_TIMEOUTS[0]

    def _select_effective_timeout(self, effective_interval: TickInterval, base_timeout: float) -> float:
        """
        Selects the maximum timeout from Config.ICMP_TIMEOUTS
        that does not exceed base_timeout and is less than effective_interval.
        """
        max_allowed = min(base_timeout, effective_interval.value)
        candidates = [t for t in Config.ICMP_TIMEOUTS if t <= max_allowed]
        return max(candidates) if candidates else Config.ICMP_TIMEOUTS[0]

    def _update_effective_params(self, host: HostState) -> None:
        host.effective_interval = self._shift_interval(host.interval, self._speed_shift)
        host.effective_timeout = self._select_effective_timeout(
            host.effective_interval,
            host.timeout
        )

    def _update_start_delay(self) -> None:
        count = len(self._registry)
        for threshold, delay in PING_START_DELAY_RULES:
            if count >= threshold:
                self._start_delay = delay
                return

    # ------------------------------------------------------------------
    # Tick scheduler
    # ------------------------------------------------------------------        
    async def _tick_scheduler(self) -> None:
        while not self._stop_async.is_set():
            try:
                now = time.time()
                delay = (-now) % 1
                if delay > 0:
                    await asyncio.sleep(delay)

                current_sec = int(time.time())
                tick_size = self.get_tick_size(current_sec % 86400)   # seconds into day
                self.tick_id += 1

                asyncio.create_task(self._execute_tick(self.tick_id, tick_size))
                self._send_big_ticks(self.tick_id, current_sec)
            except Exception as e:
                self.v.log.err(f"Error in tick scheduler: {e}")
                await asyncio.sleep(0.1)

    def _send_big_ticks(self, tick_id, current_sec: int) -> None:
        for period, evt_type in BIG_TICKS:
            if current_sec % period == 0 and self._last_big_tick_sent.get(period, -1) != current_sec:
                self.v.secr.send_evt(evt_type, payload={"timestamp": current_sec, "tick_id": tick_id})
                self._last_big_tick_sent[period] = current_sec

    @staticmethod
    def get_tick_size(second_of_day: int) -> int:
        """
        second_of_day - number of second in day (0..86399)
        """
        for divisor in (24, 16, 8, 4, 2):
            if second_of_day % divisor == 0:
                return divisor
        return 1

    # ------------------------------------------------------------------
    # Tick execution
    # ------------------------------------------------------------------
    async def _execute_tick(self, tick_id, tick_size: int) -> None:
        if not self._scanning_enabled:
            return

        ready_hosts = [h for h in self._registry.values() if h.ready_to_report]
        if ready_hosts:
            results = []
            for h in ready_hosts:
                results.append({
                    "uid": h.uid,
                    "rtt": h.last_rtt,
                    "tick_id": h.scan_start_tick_id
                })
                h.ready_to_report = False
                h.scan_start_tick_id = 0
                h.current_scan_interval = None
            try:
                self._send_report(results)
            except Exception as e:
                self.v.log.err(f"Failed to send ICMP report: {e}")

        for h in self._registry.values():
            if self._is_tick_match(tick_size, h.effective_interval):
                if h.uid in self._pending_tasks:
                    continue
                h.current_scan_interval = h.effective_interval
                h.scan_start_tick_id = tick_id
                h.ready_to_report = False
                task = asyncio.create_task(self._ping_one(h))
                self._pending_tasks[h.uid] = task
                task.add_done_callback(lambda t, uid=h.uid: self._pending_tasks.pop(uid, None))

    @staticmethod
    def _is_tick_match(tick: int, interval: TickInterval) -> bool:
        return tick % int(interval.value) == 0

    # ------------------------------------------------------------------
    # Ping
    # ------------------------------------------------------------------
    async def _ping_one(self, host: HostState) -> None:
        await asyncio.sleep(self._start_delay)

        async with self._semaphore:
            try:
                result = await async_ping(host.ip, timeout=host.effective_timeout, count=1)
                if result.is_alive:
                    host.last_rtt = result.avg_rtt / 1000.0
                else:
                    host.last_rtt = -1.0
            except asyncio.CancelledError:
                raise
            except ImportError:
                host.last_rtt = -1.0
                if not self._warned_icmplib:
                    self.v.log.wrn("icmplib not installed, all pings will fail")
                    self._warned_icmplib = True
                if self._scanning_enabled:
                    host.ready_to_report = True
            except Exception:
                host.last_rtt = -1.0
            else:
                if self._scanning_enabled:
                    host.ready_to_report = True

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    def _send_report(self, results: List[Dict[str, Any]]) -> None:
        payload = {
            "snapshot_ver": self.snapshot_ver,
            "timestamp": time.time(),
            "tick_id": self.tick_id,
            "results": results,
        }
        self.v.secr.send_evt(EvtType.ICMP_RAW_READY, payload)