# sanapo/boot_master.py
from __future__ import annotations
import time
from enum import Enum, auto
from typing import TYPE_CHECKING, List, Optional

from sanapo.enums import TierTask, UnitStat
from sanapo.boot_ui import CUIBootDriver, GUIBootDriver

if TYPE_CHECKING:
    from sanapo.kernel import Kernel
    from sanapo.tier import Tier

class MasterMode(Enum):
    IDLE = auto()
    BOOTING = auto()
    SHUTDOWN = auto()

class BootMaster:
    """The Orchestrator. Manages staged startup/shutdown with 2x2 retry logic."""
    def __init__(self, kernel: Kernel):
        self.kernel = kernel
        self.mode = MasterMode.IDLE
        
        # Iteration state (Index in sorted keys, not the layer number itself)
        self.current_tier_idx: int = 0
        self.tier_attempt: int = 1
        self.global_attempt: int = 1
        
        self._ui: Optional[CUIBootDriver | GUIBootDriver] = None
        self.problem_report: List[str] = []
        self.last_detail: str = ""
        self._start_time: float = 0.0

    def ignite(self):
        """Starts the boot sequence (First Tier -> Last Tier)"""
        self.mode = MasterMode.BOOTING
        self.current_tier_idx = 0
        self.tier_attempt = 1
        self.problem_report = []
        self._start_time = time.perf_counter()
        self._init_ui()
        self._process_current_tier()

    def shutdown(self):
        """Starts the shutdown sequence (Last Tier -> First Tier)"""
        self.mode = MasterMode.SHUTDOWN
        # Start from the last index of sorted tiers
        self.current_tier_idx = len(self.kernel._tiers) - 1
        self.tier_attempt = 1
        self._init_ui()
        self._process_current_tier()

    def step(self):
        """Main monitoring logic called by Kernel loop"""
        if self.mode == MasterMode.IDLE: 
            return

        # Get sorted list of tier numbers (handles any number of tiers and any values)
        tier_nums = sorted(self.kernel._tiers.keys())
        
        # Check for completion (out of bounds)
        if self.current_tier_idx >= len(tier_nums) or self.current_tier_idx < 0:
            self._finalize()
            return

        current_tier = self.kernel._tiers[tier_nums[self.current_tier_idx]]
        self._render_ui(current_tier, len(tier_nums))

        # Monitor Tier state machine
        if current_tier.task == TierTask.NONE:
            if current_tier.last_result_ok:
                self.kernel._log.inf(f"Boot: Tier {current_tier.name} [OK]")
                self._next_step()
            else:
                self._handle_failure(current_tier)

    def update_sub_progress(self, text: str, ready: int, total: int):
        """Discrete info from Tier for UI granularity"""
        self.last_detail = f"{text} ({ready}/{total})"

    def _process_current_tier(self):
        """Commands the current tier to start its internal logic"""
        tier_nums = sorted(self.kernel._tiers.keys())
        if 0 <= self.current_tier_idx < len(tier_nums):
            tier = self.kernel._tiers[tier_nums[self.current_tier_idx]]
            if self.mode == MasterMode.BOOTING:
                tier.start()
            else:
                tier.stop()

    def _handle_failure(self, tier: Tier):
        """2 attempts per tier, 2 attempts per system (on boot only)"""
        if self.mode == MasterMode.SHUTDOWN:
            self.problem_report.append(tier.name)
            self._next_step() # In shutdown we just move on
            return

        if self.tier_attempt < 2:
            self.kernel._log.wrn(f"Boot: {tier.name} failed. Tier Retry {self.tier_attempt + 1}/2")
            self.tier_attempt += 1
            self._process_current_tier()
        elif self.global_attempt < 2:
            self.kernel._log.crt(f"Boot: {tier.name} failed twice. RESTARTING SYSTEM!")
            self.global_attempt += 1
            self.kernel.restart() # Full reboot: Shutdown -> Ignite
        else:
            self.kernel._log.err(f"Boot: Skipping dead tier {tier.name}")
            self.problem_report.append(tier.name)
            self._next_step()

    def _next_step(self):
        if self.mode == MasterMode.BOOTING:
            self.current_tier_idx += 1
        else:
            self.current_tier_idx -= 1
        self.tier_attempt = 1
        self.last_detail = ""
        self._process_current_tier()

    def _init_ui(self):
        ui_mode = self.kernel._cfg.BOOT_UI_MODE
        if ui_mode == "GUI":
            self._ui = GUIBootDriver()
        elif ui_mode == "CUI":
            self._ui = CUIBootDriver()

    def _render_ui(self, current_tier: Tier, total_tiers: int):
        if not self._ui: return
        
        # Calculate overall percentage
        if self.mode == MasterMode.BOOTING:
            idx = self.current_tier_idx
        else:
            # For shutdown, we want the bar to fill as we close tiers
            idx = (total_tiers - 1 - self.current_tier_idx)
            
        base_percent = (idx / total_tiers) * 100
        inner_percent = (current_tier.get_progress() / total_tiers) * 100
        
        status = "STARTING" if self.mode == MasterMode.BOOTING else "STOPPING"
        text = f"{status}: {current_tier.name} | {self.last_detail}"
        self._ui.update(base_percent + inner_percent, text)

    def _finalize(self):
        duration = time.perf_counter() - self._start_time
        prev_mode = self.mode
        self.mode = MasterMode.IDLE
        
        if self._ui:
            self._ui.update(100, f"Finished in {duration:.2f}s")
            self._ui.close()
            self._ui = None
        
        if prev_mode == MasterMode.BOOTING:
            self.kernel.on_started()
        else:
            self.kernel.on_stopped()
