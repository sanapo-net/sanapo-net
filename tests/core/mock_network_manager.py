# tests/core/mock_network_manager.py
from __future__ import annotations
import time
from typing import TYPE_CHECKING

from tabulate import tabulate

from core.enums import EvtType
from tests.common import HostGenerator, FloatGenerator

if TYPE_CHECKING:
    from core.logger import Logger
    from core.secretary import Secretary
    from main import Tools

class NetworkSnapshot:
    def __init__(self, version: int, tab: dict[int, dict[str, any]]):
        self.version = version
        self.tab = tab

class MockNetworkManager:
    def __init__(self, tools: Tools, logger: Logger, secr: Secretary,
                 start_net_size: int = 200,
                 stability: float = 0.7,
                 changings: list[int] = [10, 30],
                 def_hosts: list[dict[str, any]] = [],
                 show_new_ver: bool = False
                 ):
        self._tools = tools
        self._log = logger
        self._secr = secr
        
        self._stability = stability
        self._limits = changings  # [max_remove, max_add]
        self._is_running = False
        self._show_new_ver = show_new_ver

        # 1. Isolated Generators
        self._host_gen = HostGenerator("mock_net_hosts", start_uid=100)
        self._timer_gen = FloatGenerator("mock_net_update_timer", 0.1, 60.0, 15.0)
        
        # 2. Initial Setup
        self._version = 1
        self._tab = {}
        
        # Add "immortal" predefined hosts
        for host in def_hosts:
            self._tab[host["uid"]] = host
            
        # Fill up to start_net_size
        while len(self._tab) < start_net_size:
            new_host = self._host_gen.next()
            self._tab[new_host["uid"]] = new_host

        # State for timing
        self._time_until_mutation = self._timer_gen.next()
        self._accumulator = 0.0
        self._tick_step = self._tools.config.NETWORK_TICK_SLA

        # Initial Subscriptions
        self._secr.configure_subscriptions(events={
            EvtType.APP_START: self._on_app_start,
        })

    def _on_app_start(self, frame: any) -> None:
        """Entry point. Starts the logic loop."""
        self._is_running = True
        self._send_snapshot()
        self._worker_loop()

    def _worker_loop(self) -> None:
        """Main internal loop driven by NETWORK_TICK_SLA."""
        while self._is_running:
            time.sleep(self._tick_step)
            self._accumulator += self._tick_step
            
            if self._accumulator >= self._time_until_mutation:
                # Mutation check based on stability
                if self._host_gen._rnd.random() > self._stability:
                    self._mutate_network()
                    self._send_snapshot()
                
                # Reset simulation clock
                self._accumulator = 0.0
                self._time_until_mutation = self._timer_gen.next()

    def _mutate_network(self) -> None:
        """Atomic addition and removal of hosts (UID >= 100)."""
        max_remove, max_add = self._limits
        
        # Remove logic
        removable = [uid for uid in self._tab.keys() if uid >= 100]
        if removable:
            to_remove_cnt = self._host_gen._rnd.randint(0, min(max_remove, len(removable)))
            for _ in range(to_remove_cnt):
                uid = self._host_gen._rnd.choice(removable)
                self._tab.pop(uid)
                removable.remove(uid)

        # Add logic
        to_add_cnt = self._host_gen._rnd.randint(0, max_add)
        for _ in range(to_add_cnt):
            new_host = self._host_gen.next()
            self._tab[new_host["uid"]] = new_host
        if self._show_new_ver:
            self.print_network_state()

    def _send_snapshot(self) -> None:
        """Broadcasts the current network state."""
        snapshot = NetworkSnapshot(version=self._version, tab=self._tab.copy())
        self._secr.send_evt(EvtType.NETWORK_NEW_VER, payload={"snapshot": snapshot})
        self._log.dbg(f"MockNetwork: New version {self._version} published.")
        self._version += 1

    def stop(self) -> None:
        """Safely breaks the loop."""
        self._is_running = False

    def print_network_state(self) -> None:
        """Prints the first 20 devices as a formatted table."""
        sorted_uids = sorted(self._tab.keys())[:20]
        table_data = []
        for uid in sorted_uids:
            dev = self._tab[uid]
            table_data.append([
                dev.get("uid"),
                dev.get("ip"),
                dev.get("mac"),
                dev.get("icmp_interval"),
                dev.get("priority"),
                dev.get("icmp_timeout")
            ])
        headers = ["UID", "IP Address", "MAC", "Interval", "Priority", "Timeout"]
        print(f"\n--- Network Snapshot Version {self._version-1} (Top 20) ---")
        print(tabulate(table_data, headers=headers, tablefmt="grid"))
        print("\n")