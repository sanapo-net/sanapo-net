# sanapo/boot_master.py
from __future__ import annotations
from time import perf_counter
from typing import TYPE_CHECKING

from sanapo.enums import TierTask, MasterMode
from sanapo.boot_ui import CUIBootDriver, GUIBootDriver

if TYPE_CHECKING:
    from sanapo.tier import Tier
    from sanapo.kernel import KernelBootMasterView

class BootMaster:
    """Manages staged startup/shutdown with 2x2 retry logic."""
    def __init__(self, view: KernelBootMasterView) -> None:
        self.view: KernelBootMasterView = view
        self.mode: MasterMode = MasterMode.IDLE
        
        # Iteration state (Index in sorted keys, not the layer number itself)
        self.current_tier_idx: int = 0
        self.tier_attempt: int = 1
        self.global_attempt: int = 1
        
        self._ui: CUIBootDriver | GUIBootDriver = None
        self.problem_report: list[str] = []
        self._plan: list[int] = []
        self.last_detail: str = ""
        self._start_time: float = 0.0

    def ignite(self) -> None:
        """Starts the boot sequence (First Tier -> Last Tier)"""
        self.mode = MasterMode.BOOTING
        self._plan = sorted(self.view.tiers.keys())
        self.current_tier_idx = 0
        self.tier_attempt = 1
        self.problem_report = []
        self._start_time = perf_counter()
        self._init_ui()
        self._process_current_tier()

    def shutdown(self) -> None:
        """Starts the shutdown sequence (Last Tier -> First Tier)"""
        self.mode = MasterMode.SHUTDOWN
        self._plan = sorted(self.view.tiers.keys(), reverse=True)
        self.current_tier_idx = 0
        self.tier_attempt = 1
        self._init_ui()
        self._process_current_tier()

    def step(self) -> None:
        """Main monitoring logic called by Kernel loop"""
        if self.mode == MasterMode.IDLE:
            return

        # Check for completion (out of bounds)
        if self.current_tier_idx >= len(self._plan) or self.current_tier_idx < 0:
            self._finalize()
            return
        
        tier_num = self._plan[self.current_tier_idx]
        current_tier = self.view.tiers.get(tier_num)
        if not current_tier:
            self.view.log.err("BOOT: Got None as current_tier! tier_num={num}", num=tier_num)
        
        # Send info to progress-bars
        self._render_ui(current_tier, len(self._plan))

        # Monitor Tier state machine
        if current_tier.task == TierTask.NONE:
            if current_tier.last_result_ok:
                if self.mode == MasterMode.BOOTING:
                    self.view.log.inf("BOOT: Tier {name} UP successful", name=current_tier.name)
                if self.mode == MasterMode.SHUTDOWN:
                    self.view.log.inf("BOOT: Shutdown: Tier {name} DOWN successful",name=current_tier.name)
                self._next_step()
            else:
                self._handle_failure(current_tier)

    def update_sub_progress(self, text: str, ready: int, total: int):
        """Discrete info from Tier for UI granularity"""
        self.last_detail = text
        if self._ui:
            percent = (ready / total * 100) if total > 0 else 0
            self._ui.update_local(percent, text)

    def _process_current_tier(self) -> None:
        """
        Commands the current tier to start its internal logic
        using the pre-calculated plan.
        """
        if 0 <= self.current_tier_idx < len(self._plan):
            tier_num = self._plan[self.current_tier_idx]
            tier = self.view.tiers.get(tier_num)
            if tier:
                action = "starting" if self.mode == MasterMode.BOOTING else "stopping"
                t = "BOOT: Cascade {act} Tier {name} (Layer {num})"
                self.view.log.dbg(t, act=action, name=tier.name, num=tier_num)
                if self.mode == MasterMode.BOOTING:
                    tier.start()
                else:
                    tier.stop()

    # TODO
    def _handle_failure(self, tier: Tier) -> None:
        """Processes failures for both Boot and Shutdown modes with UI feedback."""
        
        # SHUTDOWN
        if self.mode == MasterMode.SHUTDOWN:
            t = "BOOT: Shutdown: Tier {name} STUCK"
            self.view.log.wrn(t, name=tier.name)
            
            if self._ui:
                msg = self.view.translate(t, name=tier.name)
                self._ui.update_local(0, f"err {msg}")
            
            self.problem_report.append(tier.name)
            self._next_step()
            return

        # BOOT
        # Attempt for everyone Tier
        if self.tier_attempt < 2:
            t = "BOOT: Tier {name} FAIL. Retry {att}/2"
            self.view.log.wrn(t, name=tier.name, att=self.tier_attempt + 1)
            if self._ui:
                msg = self.view.translate(t, name=tier.name, att=self.tier_attempt + 1)
                self._ui.update_local(50.0, msg)
            self.tier_attempt += 1
            self._process_current_tier()

        # Attempt for entire application (if the Tier does not start after two attempts)
        elif self.global_attempt < 2:
            t = "BOOT: Tier {name} FATAL. RESTARTING..."
            self.view.log.crt(t, name=tier.name)
            if self._ui:
                msg = self.view.translate(t, name=tier.name)
                self._ui.update_local(0, f"crt {msg}")
            self.global_attempt += 1
            self.view.restart()
        else:
            t = "BOOT: Skipping dead Tier {name}"
            self.view.log.err(t, name=tier.name)
            if self._ui:
                msg = self.view.translate(t, name=tier.name)
                self._ui.update_local(0, f"wrn {msg}")
            self.problem_report.append(tier.name)
            self._next_step()

    def _next_step(self) -> None:
        if self.mode == MasterMode.BOOTING:
            self.current_tier_idx += 1
        else:
            self.current_tier_idx -= 1
        self.tier_attempt = 1
        self.last_detail = ""
        self._process_current_tier()

    def _init_ui(self) -> None:
        ui_mode = self.view.cfg.BOOT_UI_MODE
        if ui_mode == "GUI":
            self._ui = GUIBootDriver()
        elif ui_mode == "CUI":
            self._ui = CUIBootDriver()

    def _render_ui(self, current_tier: Tier, total_tiers: int) -> None:
        if not self._ui: return
        
        # Global progress bar
        global_percent = (self.current_tier_idx / total_tiers) * 100
        if self.mode == MasterMode.BOOTING:
            tpl = "BOOTING | Tier {idx}/{total}: {name}"
        if self.mode == MasterMode.SHUTDOWN:
            tpl = "SHUTDOWN | Tier {idx}/{total}: {name}"
        global_text = self.view.translate(
            tpl, 
            idx = self.current_tier_idx + 1, 
            total = total_tiers, 
            name = current_tier.name
        )
        self._ui.update_global(global_percent, global_text)
        
        # Local progress bar
        local_percent = current_tier.get_progress() * 100
        local_text = self.last_detail or f"Processing units... {int(local_percent)}%"
        self._ui.update_local(local_percent, local_text)

    def _finalize(self) -> None:
        duration = perf_counter() - self._start_time
        prev_mode = self.mode
        self.mode = MasterMode.IDLE
        
        if self._ui:
            msg = self.view.translate("Finished ({d:.2f}sec)", d=duration)
            self._ui.update_global(100.0, msg)
            self._ui.close(prev_mode.value)
            self._ui = None
        if prev_mode == MasterMode.BOOTING:
            self.view.on_started()
        else:
            self.view.on_stopped()