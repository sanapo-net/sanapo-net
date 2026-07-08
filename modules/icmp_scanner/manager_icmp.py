# modules/icmp_scanner/manager_icmp.py
from __future__ import annotations
from datetime import datetime
from collections import defaultdict
from math import ceil
from typing import TYPE_CHECKING

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

# ---------------------------------------------------------------------------
# Aliases
# ---------------------------------------------------------------------------

DeviceData = dict[str, any]
Devicelist = list[DeviceData]
Batchlist = list[Devicelist]
BatchPlan = dict[str, Batchlist]  # Plan cache: category_name(TickInterval) -> precomputed batches
TTLMap = dict[str, float]  # TTL map: category_name(TickInterval) -> time-to-live in seconds

# ---------------------------------------------------------------------------
# Category configuration constants
# ---------------------------------------------------------------------------

# Minimum batch size for different intervals
CATEGORY_MIN_BATCH: dict[TickInterval, int] = {
    TickInterval.SEC_05: 2,
    TickInterval.SEC_1:  4,
    TickInterval.SEC_2:  6,
    TickInterval.SEC_4:  8,
    TickInterval.SEC_8:  10,
}

# Base worker distribution (for proportional calculation)
BASE_WORKERS_PER_CATEGORY: dict[TickInterval, int] = {
    TickInterval.SEC_05: 30,
    TickInterval.SEC_1:  20,
    TickInterval.SEC_2:  13,
    TickInterval.SEC_4:  7,
    TickInterval.SEC_8:  5,
}

SAFETY_MARGIN_FRACTION: float = 0.1  # 10% threads reserve


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
        self.settings: Settings = Settings
        current_limit: int = Settings.icmp_scan_threads_max

        self._base_limits: dict[TickInterval, int] = BASE_WORKERS_PER_CATEGORY.copy()
        self._base_total: int = sum(self._base_limits.values())
        self._current_limits: dict[TickInterval, int] = {}

        self._pool: ThreadPoolManager = ThreadPoolManager(current_limit)
        self._watchdog: PoolWatchdog = PoolWatchdog(self.v.log)
        self._scanner: ScannerICMP = ScannerICMP(Config, self._pool, self._watchdog, self.v.log)

        self._initialize_pools(current_limit) # for every TickInterval host group

        self._snapshot: any | None = None  # Network snapshot, updated on NEW_NETWORK_VER.
        self._speed_shift: SpeedShiftICMP = SpeedShiftICMP.NORMAL  # Active speed shift mode.

        min_interval = TickInterval.SEC_05.value
        max_interval = TickInterval.SEC_8.value
        self._intervals: list[TickInterval] = [
            t for t in TickInterval if min_interval <= t.value <= max_interval
        ]

        # Precomputed tick schedule.
        self._tick_schedule: dict = self._prepare_schedule()

        # Scan profiles: speed -> interval -> timeout -> device list.
        self._scan_profiles: dict[SpeedShiftICMP, any] | None = None

        # Ordered list of UIDs by latency (from BufferICMP).
        self._uids_by_latency: list[int] | None = None

        # Cached batch plan to avoid recalculating every tick.
        self._cached_plan: BatchPlan | None = None

        # Cached TTL map (of threads) matching the current cached plan.
        self._cached_ttl: TTLMap | None = None

        # Ticker state variables.
        self._tick_counter: int = 0
        self._last_10m_ts: int = 0
        self._ticks_lookup: tuple = (
            (16, EvtType.TICK_8),
            (8, EvtType.TICK_4),
            (4, EvtType.TICK_2),
            (2, EvtType.TICK_1),
        )

        # Subscribe to framework events.
        self.v.secr.configure_subscriptions(events={
            EvtType.NEW_NETWORK_VER: self._on_new_net_ver,
            EvtType.NEW_ICMP_UIDS_BY_LATENCY: self._on_uids_by_latency,
            EvtType.NEW_ICMP_RATE: self._on_new_rate,
            EvtType.NEW_ICMP_SCAN_THREADS_MAX: self._on_new_threads_limit,
        })

        self.v.log.inf(
            f"initialized with {current_limit} max threads, distribution: {self._current_limits}"
        )

    # ------------------------------------------------------------------
    # Pool initialization and rebalancing
    # ------------------------------------------------------------------

    def _initialize_pools(self, threads_max: int) -> None:
        """Creates pools for all categories based on current total limit."""
        self._current_limits = self._calculate_distribution(threads_max)
        for interval in self._intervals:
            limit = self._current_limits.get(interval, 10)
            try:
                self._pool.new_pool(interval.name, limit)
                self.v.log.dbg(f"Created pool '{interval.name}' with {limit} workers")
            except ValueError:
                pass  # already exists


    def _calculate_distribution(self, threads_max: int) -> dict[TickInterval, int]:
        """Calculates dict by total thread limit: key=TickInterval, val=count of threads."""
        distribution: dict[TickInterval, int] = {}
        allocated: int = 0

        # Check minimal limit
        min_required: int = len(self._base_limits)
        if threads_max < min_required:
            self.v.log.wrn(
                f"Total limit {threads_max} is less than minimum required {min_required}. "
                f"Setting to {min_required}"
            )
            threads_max = min_required

        # Apportionment
        for interval, base_limit in self._base_limits.items():
            raw_limit = int(threads_max * (base_limit / self._base_total))
            raw_limit = max(1, raw_limit) # Min one thread for ctegory (pool)
            distribution[interval] = raw_limit
            allocated += raw_limit

        # If you exceed the limit, we cut back starting with the slowest ones
        while allocated > threads_max:
            for interval in sorted(distribution, key=lambda x: x.value, reverse=True):
                if distribution[interval] > 1:
                    distribution[interval] -= 1
                    allocated -= 1
                    if allocated == threads_max:
                        break

        # If there are any undistributed threads left, add them to the fastest categories
        remaining: int = threads_max - allocated
        if remaining > 0:
            sorted_intervals = sorted(distribution.keys(), key=lambda x: x.value)
            for interval in sorted_intervals:
                if remaining <= 0:
                    break
                distribution[interval] += 1
                remaining -= 1

        return distribution


    def _rebalance_pools(self, new_threads_max: int) -> None:
        """Rebalances thread pools when total limit changes."""
        self.v.log.inf(f"Rebalancing pools: new total limit = {new_threads_max}")

        if new_threads_max < 1:
            self.v.log.err(f"Invalid thread limit: {new_threads_max}. Must be >= 1")
            return

        new_limits = self._calculate_distribution(new_threads_max)
        old_limits = self._current_limits.copy()

        for interval in self._intervals:
            new_limit = new_limits.get(interval, 10)
            try:
                old_limit = self._pool.get_pool_size(interval.name)
                if old_limit != new_limit:
                    self._pool.resize_pool(interval.name, new_limit)
                    self.v.log.inf(f"Pool '{interval.name}' resized: {old_limit} → {new_limit}")
            except Exception as e:
                self.v.log.err(f"Failed to resize pool '{interval.name}': {e}")

        self._current_limits = new_limits
        try:
            self._pool.set_max_workers(new_threads_max)
            self.v.log.inf(f"ThreadPoolManager max workers updated to {new_threads_max}")
        except Exception as e:
            self.v.log.err(f"Failed to update ThreadPoolManager max workers: {e}")

        self._log_distribution(new_limits, old_limits)


    def _on_new_threads_limit(self, frame: Frame) -> None:
        """Callback for NEW_ICMP_SCAN_THREADS_MAX setting."""
        new_value = self.settings.icmp_scan_threads_max
        self.v.log.inf(f"Configuration changed: NEW_ICMP_SCAN_THREADS_MAX = {new_value}")
        if self._pool.get_max_workers() == new_value:
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

    # ------------------------------------------------------------------
    # Framework lifecycle
    # ------------------------------------------------------------------

    def define_manifest(self) -> dict:
        """Describes module parameters for container registry identification."""
        return {
            "version": "1.0.0",
            "role": "icmp_scanner_manager",
            "is_public": False,
            "is_persistent": True,
        }

    def start(self) -> bool:
        """Sets internal execution timeouts during container configuration setup."""
        self.v.step_timeout = 0.5
        return True

    def step(self) -> None:
        """Core iteration loop called by framework container on every cycle heartbeat."""
        self._process_clock_tick()

    def stop(self) -> bool:
        """Saves dynamic resources and safely deactivates internal pools."""
        self._pool.shutdown()
        return True

    # ------------------------------------------------------------------
    # Clock processing
    # ------------------------------------------------------------------

    # TODO: Decide between send_evt and callback (after icmp-buffer refactoring)
    def _process_clock_tick(self) -> None:
        """Calculates time intervals and triggers standard framework events sequentially."""

        # TICK_10M
        now = datetime.now()
        rounded_minute = (now.minute // 10) * 10
        dt_10m = now.replace(minute=rounded_minute, second=0, microsecond=0)
        now_10m_ts = int(dt_10m.timestamp())
        if now_10m_ts > self._last_10m_ts:
            self._last_10m_ts = now_10m_ts
            time_str = dt_10m.strftime("%Y-%m-%d %H:%M:%S")
            self.v.secr.send_evt(EvtType.TICK_10M, {"time": time_str})

        # Ticks 05-16
        self._tick_counter += 1
        
        if self._tick_counter % 2 == 1: # quick exit
            # self.v.secr.send_evt(EvtType.TICK_05, {})
            self._on_tick(EvtType.TICK_05)
            return
        
        for steps, evt_type in self._ticks_lookup:
            if self._tick_counter % steps == 0:
                # self.v.secr.send_evt(evt_type, {})
                self._on_tick(evt_type)
                return

        # self.v.secr.send_evt(EvtType.TICK_05, {})
        self._on_tick(EvtType.TICK_05)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    # TODO: Remove the frame if it is not needed in icmp-buffer
    # def _on_tick(self, frame: Frame) -> None:
    def _on_tick(self, evt) -> None:
        """Executes scan batches according to the current plan."""
        if not self._scan_profiles: return
        if self._cached_ttl is None: return

        # tick_type = frame.evt_type
        tick_type = evt

        # Fetch results from previous scans.
        scan_results = self._scanner.pop_results()

        # If no plan exists yet, skip.
        if not self._cached_plan:
            if scan_results:
                self.v.secr.send_evt(EvtType.ICMP_RAW_READY, payload={"data": scan_results})
            return

        # Gather active category names for this tick.
        active_categories: list[str] = []
        for interval in self._tick_schedule[self._speed_shift][tick_type]:
            active_categories.append(interval.name)

        if not active_categories:
            if scan_results:
                self.v.secr.send_evt(
                    EvtType.ICMP_RAW_READY, payload={"data": scan_results}
                )
            return

        # For each active category, send only as many batches as permitted
        # by available slots minus reserve, respecting global max_workers.
        total_workers = self._pool.get_max_workers()

        # First pass: calculate desired limits based on cached plan.
        desired_limits: dict[str, int] = {}
        for cat in active_categories:
            batches = self._cached_plan.get(cat, [])
            desired_limits[cat] = len(batches) if batches else 0

        # Normalize desired limits to not exceed total workers.
        total_desired = sum(desired_limits.values())
        if total_desired > total_workers:
            # Scale down proportionally, but keep at least 1 for each non-zero.
            scale = total_workers / total_desired
            for cat in list(desired_limits.keys()):
                if desired_limits[cat] > 0:
                    desired_limits[cat] = max(1, int(desired_limits[cat] * scale))
            # Recalculate sum and cut excess from longest intervals if needed.
            overflow = sum(desired_limits.values()) - total_workers
            if overflow > 0:
                # Sort by interval length descending (SEC_8 > SEC_05).
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

        # Second pass: adjust by available slots and reserve.
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

        # Prepare map of batches to send and TTL map.
        batches_to_send: dict[str, Batchlist] = {}
        ttl_map: TTLMap = {}
        for cat, limit in actual_limits.items():
            all_batches = self._cached_plan.get(cat, [])
            if all_batches and limit > 0:
                batches_to_send[cat] = all_batches[:limit]
                ttl_map[cat] = self._cached_ttl.get(cat, Config.SCAN_ICMP_DEFAULT_TTL)

        # Execute scan.
        self._scanner.execute(batches_to_send, ttl_map)

        # Send any pending results upstream.
        if scan_results:
            self.v.secr.send_evt(
                EvtType.ICMP_RAW_READY, payload={"data": scan_results}
            )


    def _on_new_rate(self, frame: Frame) -> None:
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
            self.v.log.err("ManagerICMP: payload without 'snapshot' in NEW_NETWORK_VER")
            return
        self._snapshot = snapshot
        tab = snapshot.get("tab", None)
        if not tab:
            self.v.log.err("ManagerICMP: snapshot without 'tab' in NEW_NETWORK_VER")
            return
        self._get_scan_profiles_by_net_tab(tab)
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

    # ------------------------------------------------------------------
    # Plan (re)building
    # ------------------------------------------------------------------

    def _rebuild_plan(self) -> None:
        """Constructs batch plan and TTL map from current scan profiles."""
        if not self._scan_profiles:
            self._cached_plan = None
            self._cached_ttl = None
            return

        plan: BatchPlan = {}
        ttl_map: TTLMap = {}

        speed_profile: dict[TickInterval, dict[float, Devicelist]] = self._scan_profiles.get(
            self._speed_shift, {}
        )
        for interval, timeout_map in speed_profile.items():
            cat_name = interval.name
            # Flatten all device lists for this interval.
            devices: Devicelist = []
            for dev_list in timeout_map.values():
                devices.extend(dev_list)

            if not devices:
                continue

            interval_devs_len = len(devices)
            min_batch = CATEGORY_MIN_BATCH[interval]
            max_workers_cat = self._current_limits[interval]

            # Desired limit: one worker per min_batch hosts, capped.
            desired = min(max_workers_cat, max(1, ceil(interval_devs_len / min_batch)))
            # Reserve within desired limit (will be applied later with real available slots).
            reserve = (max(1, int(desired * SAFETY_MARGIN_FRACTION)) if desired > 0 else 0)

            # Effective limit for planning (we don't know available slots yet,
            # so we plan with desired and adjust dynamically in _on_tick).
            effective_plan = (max(1, desired - reserve) if desired > reserve else desired)
            if effective_plan <= 0:
                continue

            batch_size = ceil(interval_devs_len / effective_plan)
            # Optional max batch size per category (could be configured).
            max_batch = Config.ICMP_MAX_BATCH_PER_CATEGORY.get(interval, 200)
            batch_size = min(batch_size, max_batch)

            # Split devices into batches.
            batches: Batchlist = []
            for i in range(0, interval_devs_len, batch_size):
                chunk = devices[i:i + batch_size]
                # Prepare payload dicts expected by scanner.
                batch_payload = []
                for dev in chunk:
                    batch_payload.append({
                        "uid": dev["uid"],
                        "ip": dev["ip"],
                        "tick_id": 0,  # will be filled by scanner or manager
                        "rtt": float("nan"),
                        "timeout": dev["timeout"],
                    })
                batches.append(batch_payload)

            plan[cat_name] = batches

            # TTL = timeout + Config.SCAN_ICMP_TTL_EXTRA (50 ms)
            base_timeout = devices[0]["timeout"] if devices else 2.0
            ttl = base_timeout + Config.SCAN_ICMP_TTL_EXTRA
            ttl_map[cat_name] = ttl

        self._cached_plan = plan
        self._cached_ttl = ttl_map
        self.v.log.dbg(f"ManagerICMP: plan rebuilt for {len(plan)} categories.")

    # ------------------------------------------------------------------
    # Original _prepare_schedule (restored from old code)
    # ------------------------------------------------------------------

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
                    new_idx = max(0, min(idx + shift.value, len(self._intervals) - 1))
                    effective_int = self._intervals[new_idx]
                    if (
                        (phys_int.value + 0.001) >= effective_int.value
                        and (phys_int.value % effective_int.value) < 0.01
                    ):
                        active_groups.append(group_int)
                shift_map[phys_evt] = active_groups
            full_map[shift] = shift_map
        return full_map

    # ------------------------------------------------------------------
    # Scan profiles construction (from old code, adapted)
    # ------------------------------------------------------------------

    def _get_scan_profiles_by_net_tab(self, tab: dict[int, dict[str, any]]) -> None:
        """
        Converts network table into nested scan profiles:
        speed -> interval -> timeout -> devices.

        Args:
            tab: mapping uid -> device data
                 (must contain 'icmp_interval', 'ip', 'timeout').
        """
        raw_profiles = {s: defaultdict(lambda: defaultdict(list)) for s in SpeedShiftICMP}

        for uid, dev_data in tab.items():
            orig_interval = dev_data.get("icmp_interval")
            if not isinstance(orig_interval, TickInterval):
                continue

            base_timeout = dev_data.get("timeout", 2.0)
            margin_norm = Config.SCAN_ICMP_TIMEOUT_MIN_MARGIN[orig_interval]
            timeout_norm = min(base_timeout, orig_interval.value - margin_norm)
            data_norm = {"uid": uid, "ip": dev_data["ip"], "timeout": timeout_norm}

            raw_profiles[SpeedShiftICMP.NORMAL][orig_interval][timeout_norm].append(data_norm)
            raw_profiles[SpeedShiftICMP.SLOWER][orig_interval][timeout_norm].append(data_norm)

            fast_interval = self._shift_interval(orig_interval, SpeedShiftICMP.FASTER)
            margin_fast = Config.SCAN_ICMP_TIMEOUT_MIN_MARGIN[fast_interval]
            timeout_fast = min(base_timeout, fast_interval.value - margin_fast)
            data_fast = {"uid": uid, "ip": dev_data["ip"], "timeout": timeout_fast}
            raw_profiles[SpeedShiftICMP.FASTER][orig_interval][timeout_fast].append(data_fast)

        self._scan_profiles = {}
        for mode in raw_profiles:
            self._scan_profiles[mode] = {
                interval: dict(timeouts)
                for interval, timeouts in raw_profiles[mode].items()
            }


    def _sort_scan_profiles(self) -> None:
        """Sorts device lists inside scan profiles by latency order (if available)."""
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


    def _shift_interval(self, current: TickInterval, shift: SpeedShiftICMP) -> TickInterval:
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
            new_idx = idx + shift.value
            clamped = max(0, min(new_idx, len(self._intervals) - 1))
            return self._intervals[clamped]
        except ValueError:
            return current