# sanapo/views.py
from __future__ import annotations
from typing import TYPE_CHECKING, Callable, List, Dict, Any, Optional, Union

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
        self.get_manager: Callable[[BaseUnit], ThreadManager] = kernel.get_manager_by_unit
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
    def __init__(self, kernel: Kernel):
        self._kernel = kernel

        # Life-Cycle Management
        self.start: Callable[[], None] = kernel.start
        self.stop: Callable[[], None] = kernel.stop
        self.restart: Callable[[], None] = kernel.restart
        
        # System Provisioning
        self.setup: Callable[
            [Optional[List[Dict[str, Any]]], Optional[List[Dict[str, Any]]], Optional[List[Dict[str, Any]]]], 
            Dict[str, Dict[str, Any]]
        ] = kernel.setup

        self.add_unit: Callable[
            [str, UnitType, Any, Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[str], Optional[str], Optional[int]], 
            Optional[BaseUnit]
        ] = kernel.add_unit

        self.add_units: Callable[[List[Dict[str, Any]]], Dict[str, BaseUnit]] = kernel.add_units
        
        self.add_thread: Callable[
            [str, Optional[ThreadType], Optional[float], Optional[float], Optional[float]], 
            Optional[ThreadManager]
        ] = kernel.add_thread

        self.add_threads: Callable[[List[Dict[str, Any]]], Dict[str, ThreadManager]] = kernel.add_threads
        
        self.add_tier: Callable[[Optional[int], Optional[str]], Optional[Tier]] = kernel.add_tier
        self.add_tiers: Callable[[List[Dict[str, Any]]], Dict[str, Tier]] = kernel.add_tiers

        # Graceful Removal
        self.del_unit: Callable[[Union[Addr, str]], bool] = kernel.del_unit
        self.del_tier: Callable[[Optional[int], Optional[str]], bool] = kernel.del_tier
        self.del_thread: Callable[[str], bool] = kernel.del_thread

        # Internal Tools
        self.log: Logger = kernel._log
        self.translate: Callable[..., str] = kernel._log._translator.translate

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
