# modules/icmp_scanner/manager_icmp.py
from __future__ import annotations

import time
from collections import defaultdict
from math import ceil
from typing import TYPE_CHECKING, Any

from sanapo.base_module import BaseModule
from common.config import Config
from common.settings import Settings
from common.enums import EvtType, SpeedShiftICMP, TickInterval
from modules.common.scan.pool_watchdog import PoolWatchdog
from modules.common.scan.thread_pool_manager import ThreadPoolManager
from modules.icmp_scanner.scanner_icmp import ScannerICMP

if TYPE_CHECKING:
    from sanapo.protocol import Frame
    from sanapo.base_unit import UnitModuleView


DeviceData = dict[str, Any]
Devicelist = list[DeviceData]
Batchlist = list[Devicelist]
BatchPlan = dict[str, Batchlist]
TTLMap = dict[str, float]

CATEGORY_MIN_BATCH = Config.CATEGORY_MIN_BATCH
BASE_WORKERS_PER_CATEGORY = Config.BASE_WORKERS_PER_CATEGORY

SAFETY_MARGIN_FRACTION: float = 0.1


class ManagerICMP(BaseModule):
    """
    Orchestrates ICMP scanning: builds scan plan, distributes batches
    across thread pool categories, and reacts to configuration events
    (network changes, scan rate changes, thread pool size changes, etc.).
    """

    def __init__(self, unit_view: UnitModuleView) -> None:
        """
        Initializes the manager, scanner, thread pool and watchdog.

        Args:
            unit_view: safe module view provided by the framework sanapo.
        """
        super().__init__(unit_view)

        self._base_limits: dict[TickInterval, int] = BASE_WORKERS_PER_CATEGORY.copy()
        self._base_total: int = sum(self._base_limits.values())
        self._current_limits: dict[TickInterval, int] = {}

        current_limit: int = Settings.icmp_scan_threads_max
        self._pool: ThreadPoolManager = ThreadPoolManager(current_limit)
        self._watchdog: PoolWatchdog = PoolWatchdog(self.v.log)
        self._scanner: ScannerICMP = ScannerICMP(Config, self._pool, self._watchdog, self.v.log)
        self._initialize_pools(current_limit)
        self._snapshot: Any | None = None
        self._speed_shift: SpeedShiftICMP = SpeedShiftICMP.NORMAL

        min_interval = TickInterval.SEC_05.value
        max_interval = TickInterval.SEC_8.value
        self._intervals: list[TickInterval] = [
            t for t in TickInterval if min_interval <= t.value <= max_interval
        ]

        self._tick_schedule: dict = self._prepare_schedule()

        self._scan_profiles: dict[SpeedShiftICMP, Any] | None = None

        self._uids_by_latency: list[int] | None = None

        self._cached_plan: BatchPlan | None = None

        self._cached_ttl: TTLMap | None = None

        self._tick_counter: int = 0
        self._last_10m_ts: int = 0
        self._ticks_lookup: tuple = (
            (16, EvtType.TICK_8),
            (8, EvtType.TICK_4),
            (4, EvtType.TICK_2),
            (2, EvtType.TICK_1),
        )

        self.v.scr.configure_subscriptions(events={
            EvtType.TICK_05: self._on_tick,
            EvtType.TICK_1: self._on_tick,
            EvtType.TICK_2: self._on_tick,
            EvtType.TICK_4: self._on_tick,
            EvtType.TICK_8: self._on_tick,
            EvtType.NETWORK_NEW_VER: self._on_new_net_ver,
            EvtType.ICMP_UIDS_BY_LATENCY_READY: self._on_uids_by_latency,
            EvtType.ICMP_NEW_INTERVALS: self._on_speed_changed,
        })

        self.v.config.subscribe(
            "ICMP_SCAN_THREADS_MAX",
            self._on_threads_limit_changed
        )

        self.v.log.inf(
            f"ManagerICMP initialized with {current_limit} max threads, "
            f"distribution: {self._current_limits}"
        )

    def _initialize_pools(self, total_limit: int) -> None:
        """
        Creates pools for all categories based on current total limit.

        Args:
            total_limit: maximum number of threads available
        """
        new_limits = self._calculate_distribution(total_limit)
        self._current_limits = new_limits

        for interval in self._intervals:
            limit = new_limits.get(interval, 10)
            try:
                self._pool.new_pool(interval.name, limit)
                self.v.log.dbg(f"Created pool '{interval.name}' with {limit} workers")
            except ValueError:
                pass

    def _calculate_distribution(self, total_limit: int) -> dict[TickInterval, int]:
        """
        Calculates worker distribution across categories proportionally.

        Args:
            total_limit: total threads available

        Returns:
            Dictionary mapping interval to number of workers
        """
        distribution: dict[TickInterval, int] = {}
        allocated: int = 0

        min_required: int = len(self._base_limits)
        if total_limit < min_required:
            self.v.log.wrn(
                f"Total limit {total_limit} is less than minimum required {min_required}. "
                f"Setting to {min_required}"
            )
            total_limit = min_required

        for interval, base_limit in self._base_limits.items():
            raw_limit = int(total_limit * (base_limit / self._base_total))
            raw_limit = max(1, raw_limit)
            distribution[interval] = raw_limit
            allocated += raw_limit

        while allocated > total_limit:
            for interval in sorted(distribution, key=lambda x: x.value, reverse=True):
                if distribution[interval] > 1:
                    distribution[interval] -= 1
                    allocated -= 1
                    if allocated == total_limit:
                        break

        remaining: int = total_limit - allocated
        if remaining > 0:
            sorted_intervals = sorted(
                distribution.keys(),
                key=lambda x: x.value
            )
            for interval in sorted_intervals:
                if remaining <= 0:
                    break
                distribution[interval] += 1
                remaining -= 1

        return distribution

    def _rebalance_pools(self, new_total: int) -> None:
        """
        Rebalances thread pools when total limit changes.

        Args:
            new_total: new maximum number of threads
        """
        self.v.log.inf(f"Rebalancing pools: new total limit = {new_total}")

        if new_total < 1:
            self.v.log.err(f"Invalid thread limit: {new_total}. Must be >= 1")
            return

        new_limits = self._calculate_distribution(new_total)

        old_limits = self._current_limits.copy()

        for interval in self._intervals:
            new_limit = new_limits.get(interval, 10)
            try:
                old_limit = self._pool.get_pool_size(interval.name)
                if old_limit != new_limit:
                    self._pool.resize_pool(interval.name, new_limit)
                    self.v.log.inf(
                        f"Pool '{interval.name}' resized: {old_limit} → {new_limit} workers"
                    )
            except Exception as e:
                self.v.log.err(f"Failed to resize pool '{interval.name}': {e}")

        self._current_limits = new_limits

        try:
            self._pool.set_max_workers(new_total)
            self.v.log.inf(f"ThreadPoolManager max workers updated to {new_total}")
        except Exception as e:
            self.v.log.err(f"Failed to update ThreadPoolManager max workers: {e}")

        self._log_distribution(new_limits, old_limits)

    def _on_threads_limit_changed(self, new_value: int) -> None:
        """
        Callback for ICMP_SCAN_THREADS_MAX configuration change.

        Args:
            new_value: new thread limit value
        """
        self.v.log.inf(f"Configuration changed: ICMP_SCAN_THREADS_MAX = {new_value}")

        current_total = self._pool.get_max_workers()
        if current_total == new_value:
            self.v.log.dbg(f"Thread limit unchanged: {new_value}")
            return

        self._rebalance_pools(new_value)

    def _log_distribution(self, new_limits: dict[TickInterval, int],
                          old_limits: dict[TickInterval, int] | None = None) -> None:
        """
        Logs current distribution for debugging.

        Args:
            new_limits: new distribution
            old_limits: old distribution for comparison (optional)
        """
        total = sum(new_limits.values())
        self.v.log.dbg(f"Current distribution (total={total}):")

        for interval, count in sorted(new_limits.items(), key=lambda x: x[0].value):
            percentage = (count / total * 100) if total > 0 else 0
            change = ""
            if old_limits and interval in old_limits:
                diff = count - old_limits[interval]
                if diff != 0:
                    change = f" ({'+' if diff > 0 else ''}{diff})"
            self.v.log.dbg(f"  {interval.name}: {count} workers ({percentage:.1f}%){change}")

    def define_manifest(self) -> dict:
        """
        Describes module parameters for container registry identification.
        """
        return {
            "version": "2.0.0",
            "role": "icmp_scanner_manager",
            "is_public": False,
            "is_persistent": True,
        }

    def start(self) -> bool:
        """
        Sets internal execution timeouts during container configuration setup.
        """
        self.v.step_timeout = 0.5
        self.v.log.inf("ICMP manager module successfully activated within container.")
        return True

    def step(self) -> None:
        """
        Core iteration loop called by framework container on every cycle heartbeat.
        """
        self._process_clock_tick()

    def stop(self) -> bool:
        """
        Saves dynamic resources and safely deactivates internal pools.
        """
        self._pool.shutdown()
        return True

    def _process_clock_tick(self) -> None:
        """
        Calculates time intervals and triggers standard framework events sequentially.
        """
        self._tick_counter += 1
        payload = {"tick_id": self._tick_counter}
        sent_rtt = False

        for steps, evt_type in self._ticks_lookup:
            if self._tick_counter % steps == 0:
                self.v.scr.send_evt(evt_type, payload)
                sent_rtt = True
                break

        if not sent_rtt:
            self.v.scr.send_evt(EvtType.TICK_05, payload)

        now_10m = (int(time.time()) // 600) * 600
        if now_10m > self._last_10m_ts:
            self._last_10m_ts = now_10m
            self.v.scr.send_evt(EvtType.TICK_10M, {"time": now_10m})

    def _on_tick(self, frame: Frame) -> None:
        """
        Executes scan batches according to the current plan.

        Args:
            frame: incoming event frame with tick metadata.
        """
        if not self._scan_profiles:
            return

        tick_type = frame.evt_type
        tick_id = frame.payload["tick_id"]

        scan_results = self._scanner.pop_results()

        if not self._cached_plan:
            if scan_results:
                self.v.scr.send_evt(
                    EvtType.ICMP_RAW_READY, payload={"data": scan_results}
                )
            return

        active_categories: list[str] = []
        for interval in self._tick_schedule[self._speed_shift][tick_type]:
            active_categories.append(interval.name)

        if not active_categories:
            if scan_results:
                self.v.scr.send_evt(
                    EvtType.ICMP_RAW_READY, payload={"data": scan_results}
                )
            return

        total_workers = self._pool.get_max_workers()

        desired_limits: dict[str, int] = {}
        for cat in active_categories:
            batches = self._cached_plan.get(cat, [])
            desired_limits[cat] = len(batches) if batches else 0

        total_desired = sum(desired_limits.values())
        if total_desired > total_workers:
            scale = total_workers / total_desired
            for cat in list(desired_limits.keys()):
                if desired_limits[cat] > 0:
                    desired_limits[cat] = max(1, int(desired_limits[cat] * scale))
            overflow = sum(desired_limits.values()) - total_workers
            if overflow > 0:
                sorted_cats = sorted(
                    active_categories,
                    key=lambda x: (
                        TickInterval[x].value
                        if x in TickInterval.__members__
                        else 0
                    ),
                    reverse=True,
                )
                for cat in sorted_cats:
                    if overflow <= 0:
                        break
                    if desired_limits[cat] > 1:
                        reducible = desired_limits[cat] - 1
                        cut = min(overflow, reducible)
                        desired_limits[cat] -= cut
                        overflow -= cut

        actual_limits: dict[str, int] = {}
        for cat in active_categories:
            desired = desired_limits.get(cat, 0)
            if desired == 0:
                continue
            reserve = (
                max(1, int(desired * SAFETY_MARGIN_FRACTION))
                if desired > 0
                else 0
            )
            available = self._pool.available_slots(cat)
            effective = min(desired, max(0, available - reserve))
            if effective > 0:
                actual_limits[cat] = effective

        batches_to_send: dict[str, Batchlist] = {}
        ttl_map: TTLMap = {}
        for cat, limit in actual_limits.items():
            all_batches = self._cached_plan.get(cat, [])
            if all_batches and limit > 0:
                batches_to_send[cat] = all_batches[:limit]
                ttl_map[cat] = self._cached_ttl.get(cat, Config.SCAN_ICMP_DEFAULT_TTL)

        self._scanner.execute(batches_to_send, ttl_map)

        if scan_results:
            self.v.scr.send_evt(
                EvtType.ICMP_RAW_READY, payload={"data": scan_results}
            )

    def _on_speed_changed(self, frame: Frame) -> None:
        """
        Updates speed shift mode and rebuilds plan.

        Args:
            frame: event frame with 'icmp_speed_shift' payload.
        """
        self._speed_shift = frame.payload["icmp_speed_shift"]
        self._rebuild_plan()

    def _on_new_net_ver(self, frame: Frame) -> None:
        """
        Rebuilds scan profiles from a new network snapshot, then recreates plan.

        Args:
            frame: event frame containing 'snapshot' object.
        """
        snapshot = frame.payload.get("snapshot", None)
        if not snapshot:
            self.v.log.err(
                "ManagerICMP: payload without 'snapshot' in NETWORK_NEW_VER"
            )
            return
        self._snapshot = snapshot
        self._get_scan_profiles_by_net_tab(snapshot.tab)
        self._sort_scan_profiles()
        self._rebuild_plan()

    def _on_uids_by_latency(self, frame: Frame) -> None:
        """
        Stores new latency ordering and rebuilds plan.

        Args:
            frame: event frame with 'uids_by_latency' list.
        """
        temp_score = frame.payload.get("uids_by_latency", None)
        if not temp_score:
            self.v.log.err("ManagerICMP: uids_by_latency was empty")
            return
        self._uids_by_latency = temp_score
        self._sort_scan_profiles()
        self._rebuild_plan()

    def _rebuild_plan(self) -> None:
        """
        Constructs batch plan and TTL map from current scan profiles.
        """
        if not self._scan_profiles:
            self._cached_plan = None
            self._cached_ttl = None
            return

        plan: BatchPlan = {}
        ttl_map: TTLMap = {}

        speed_profile = self._scan_profiles.get(self._speed_shift, {})
        for interval, timeout_map in speed_profile.items():
            cat_name = interval.name
            devices: Devicelist = []
            for dev_list in timeout_map.values():
                devices.extend(dev_list)

            if not devices:
                continue

            total = len(devices)
            min_batch = Config.CATEGORY_MIN_BATCH.get(interval, 10)
            max_workers_cat = self._current_limits.get(interval, 10)

            desired = min(max_workers_cat, max(1, ceil(total / min_batch)))
            reserve = (
                max(1, int(desired * SAFETY_MARGIN_FRACTION))
                if desired > 0
                else 0
            )

            effective_plan = (
                max(1, desired - reserve) if desired > reserve else desired
            )
            if effective_plan <= 0:
                continue

            batch_size = ceil(total / effective_plan)
            max_batch = Config.ICMP_MAX_BATCH_PER_CATEGORY.get(interval, 200)
            batch_size = min(batch_size, max_batch)

            batches: Batchlist = []
            for i in range(0, total, batch_size):
                chunk = devices[i:i + batch_size]
                batch_payload = []
                for dev in chunk:
                    batch_payload.append({
                        "uid": dev["uid"],
                        "ip": dev["ip"],
                        "tick_id": 0,
                        "rtt": float("nan"),
                        "timeout": dev["timeout"],
                    })
                batches.append(batch_payload)

            plan[cat_name] = batches

            base_timeout = devices[0]["timeout"] if devices else 2.0
            ttl = base_timeout + Config.SCAN_ICMP_TTL_EXTRA
            ttl_map[cat_name] = ttl

        self._cached_plan = plan
        self._cached_ttl = ttl_map
        self.v.log.dbg(
            f"ManagerICMP: plan rebuilt for {len(plan)} categories."
        )

    def _prepare_schedule(self) -> dict:
        """
        Builds mapping: speed shift -> tick event -> list of intervals active.

        Returns:
            Nested dictionary described above.
        """
        tick_to_int = {
            EvtType.TICK_05: TickInterval.SEC_05,
            EvtType.TICK_1: TickInterval.SEC_1,
            EvtType.TICK_2: TickInterval.SEC_2,
            EvtType.TICK_4: TickInterval.SEC_4,
            EvtType.TICK_8: TickInterval.SEC_8,
        }
        full_map = {}
        for shift in SpeedShiftICMP:
            shift_map = {}
            for phys_evt, phys_int in tick_to_int.items():
                active_groups = []
                for group_int in self._intervals:
                    idx = self._intervals.index(group_int)
                    new_idx = max(
                        0, min(idx - shift.value, len(self._intervals) - 1)
                    )
                    effective_int = self._intervals[new_idx]
                    if (
                        (phys_int.value + 0.001) >= effective_int.value
                        and (phys_int.value % effective_int.value) < 0.01
                    ):
                        active_groups.append(group_int)
                shift_map[phys_evt] = active_groups
            full_map[shift] = shift_map
        return full_map

    def _get_scan_profiles_by_net_tab(
        self, tab: dict[int, dict[str, Any]]
    ) -> None:
        """
        Converts network table into nested scan profiles:
        speed -> interval -> timeout -> devices.

        Args:
            tab: mapping uid -> device data
                 (must contain 'icmp_interval', 'ip', 'timeout').
        """
        raw_profiles = {
            s: defaultdict(lambda: defaultdict(list)) for s in SpeedShiftICMP
        }

        for uid, dev_data in tab.items():
            orig_interval = dev_data.get("icmp_interval")
            if not isinstance(orig_interval, TickInterval):
                continue

            base_timeout = dev_data.get("timeout", 2.0)
            margin_norm = Config.SCAN_ICMP_TIMEOUT_MIN_MARGIN[orig_interval]
            timeout_norm = min(base_timeout, orig_interval.value - margin_norm)
            data_norm = {"uid": uid, "ip": dev_data["ip"], "timeout": timeout_norm}

            raw_profiles[SpeedShiftICMP.NORMAL][orig_interval][timeout_norm].append(
                data_norm
            )
            raw_profiles[SpeedShiftICMP.SLOWER][orig_interval][timeout_norm].append(
                data_norm
            )

            fast_interval = self._shift_interval(orig_interval, SpeedShiftICMP.FASTER)
            margin_fast = Config.SCAN_ICMP_TIMEOUT_MIN_MARGIN[fast_interval]
            timeout_fast = min(base_timeout, fast_interval.value - margin_fast)
            data_fast = {"uid": uid, "ip": dev_data["ip"], "timeout": timeout_fast}
            raw_profiles[SpeedShiftICMP.FASTER][orig_interval][timeout_fast].append(
                data_fast
            )

        self._scan_profiles = {}
        for mode in raw_profiles:
            self._scan_profiles[mode] = {
                interval: dict(timeouts)
                for interval, timeouts in raw_profiles[mode].items()
            }

    def _sort_scan_profiles(self) -> None:
        """
        Sorts device lists inside scan profiles by latency order (if available).
        """
        if not self._scan_profiles:
            return

        if self._uids_by_latency:
            order = {uid: idx for idx, uid in enumerate(self._uids_by_latency)}
        else:
            order = {}

        for mode_intervals in self._scan_profiles.values():
            for timeout_map in mode_intervals.values():
                for dev_list in timeout_map.values():
                    dev_list.sort(key=lambda d: order.get(d["uid"], float("inf")))

    def _shift_interval(
        self, current: TickInterval, shift: SpeedShiftICMP
    ) -> TickInterval:
        """
        Shifts interval according to speed mode, clamped to available range.

        Args:
            current: base interval.
            shift: speed shift mode.

        Returns:
            Adjusted interval.
        """
        try:
            idx = self._intervals.index(current)
            new_idx = idx - shift.value
            clamped = max(0, min(new_idx, len(self._intervals) - 1))
            return self._intervals[clamped]
        except ValueError:
            return current