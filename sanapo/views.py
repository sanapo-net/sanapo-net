# sanapo/views.py
from __future__ import annotations
from typing import TYPE_CHECKING, Callable, Union

if TYPE_CHECKING:
    from sanapo.kernel import Kernel
    from sanapo.config import Config
    from sanapo.logger import Logger
    from sanapo.base_unit import BaseUnit
    from sanapo.tier import Tier
    from sanapo.thread_manager import ThreadManager
    from sanapo.addr import Addr
    from sanapo.enums import UnitType, ThreadType

class KernelTierView:
    """Limited Kernel API for Tiers to ensure safety and precision."""
    def __init__(self, kernel: Kernel):
        self.cfg: Config = kernel._cfg
        self.rebuild_unit: Callable[[BaseUnit], None] = kernel.rebuild_unit
        self.get_manager: Callable[[Addr], ThreadManager] = kernel.get_manager_by_addr
        self.emit_progress: Callable[[str, int, int], None] = kernel.emit_boot_progress

class KernelBootMasterView:
    """Limited Kernel API for Tiers to ensure safety and precision."""
    def __init__(self, kernel: Kernel):
        self.cfg: Config = kernel._cfg
        self.log: Logger = kernel._log
        self.tiers: dict[int, Tier] = kernel._tiers
        self.translate: Callable[..., str] = kernel._translator.translate
        self.restart: Callable[[None], None] = kernel.restart
        self.on_started: Callable[[None], None] = kernel.on_started
        self.on_stopped: Callable[[None], None] = kernel.on_stopped

class KernelUserView:
    """High-level secure API for project developers to interact with the sanapo Kernel."""

    def __init__(self, kernel: Kernel) -> None:
        self._kernel = kernel

        # Life-Cycle Management
        self.start: Callable[[], None] = kernel.start
        self.stop: Callable[[], None] = kernel.stop
        self.restart: Callable[[], None] = kernel.restart

    def setup(
        self,
        threads: list[dict[str, any]] | None = None,
        tiers: list[dict[str, any]] | None = None,
        units: list[dict[str, any]] | None = None
    ) -> dict[str, dict[str, any]]:
        """Unified entry for system building"""
        return self._kernel.setup(threads, tiers, units)

    def add_unit(
        self,
        name: str,
        type: UnitType,
        m_class: any,
        m_params: dict[str, any] | None = None,
        manifest: dict[str, any] | None = None,
        thread_name: str | None = None,
        tier_name: str | None = None,
        tier_layer: int | None = None
    ) -> BaseUnit | None:
        """Add a single unit to the system"""
        return self._kernel.add_unit(
            name, type, m_class, m_params, manifest, thread_name, tier_name, tier_layer)

    def add_units(self, configs: list[dict[str, any]]) -> dict[str, BaseUnit]:
        """Add multiple units to the system"""
        return self._kernel.add_units(configs)

    def add_thread(
        self,
        name: str,
        type: ThreadType | None = None,
        tct: float | None = None,
        tct_hiber: float | None = None,
        join_margin: float | None = None
    ) -> ThreadManager | None:
        """Add a thread manager to the system"""
        return self._kernel.add_thread(name, type, tct, tct_hiber, join_margin)

    def add_threads(self, configs: list[dict[str, any]]) -> dict[str, ThreadManager]:
        """Add multiple thread managers to the system"""
        return self._kernel.add_threads(configs)

    def add_tier(self, layer_num: int | None = None, name: str | None = None) -> Tier | None:
        """
        Add a tier to the system with specific layer number and/or name
        """
        return self._kernel.add_tier(layer_num, name)

    def add_tiers(self, configs: list[dict[str, any]]) -> dict[str, Tier]:
        """Add multiple tiers to the system"""
        return self._kernel.add_tiers(configs)

    def del_unit(self, addr: Union[Addr, str]) -> bool:
        """Gracefully stops and removes a unit from all registries"""
        return self._kernel.del_unit(addr)

    def del_tier(self, layer_num: int | None = None, name: str | None = None) -> bool:
        """Removes a Tier only if it contains no units"""
        return self._kernel.del_tier(layer_num, name)

    def del_thread(self, name: str) -> bool:
        """Stops and removes a ThreadManager only if no units are assigned to it"""
        return self._kernel.del_thread(name)

    # Internal Tools
    @property
    def log(self) -> Logger:
        """Access to the kernel's logger"""
        return self._kernel._log

    @property
    def translate(self) -> Callable[..., str]:
        """Access to translation service"""
        return self._kernel._log._translator.translate

    # Property-based Flags to ensure real-time accuracy
    @property
    def is_running(self) -> bool:
        """True if the system main loop is active."""
        return self._kernel._is_running

    @property
    def is_shutdowning(self) -> bool:
        """True if the shutdown sequence is in progress."""
        return self._kernel._is_shutdowning

    @property
    def is_rebooting(self) -> bool:
        """True if the system is scheduled for a global restart."""
        return self._kernel._is_rebooting
