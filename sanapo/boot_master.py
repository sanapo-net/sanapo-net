# sanapo/boot_master.py
from __future__ import annotations
import os
from time import perf_counter
from typing import TYPE_CHECKING

from sanapo.enums import TierStat, BootTask
from sanapo.boot_ui import CUIBootDriver, GUIBootDriver

if TYPE_CHECKING:
    from sanapo.tier import Tier
    from sanapo.kernel import KernelBootMasterView

class BootMaster:
    """Manages staged startup/shutdown with 2x2 retry logic."""
    def __init__(self, view: KernelBootMasterView) -> None:
        self.view: KernelBootMasterView = view
        self.mode: BootTask = BootTask.NONE
        
        # Iteration state (Index in sorted keys, not the layer number itself)
        self.current_tier_id: int = 0        
        self._ui: CUIBootDriver | GUIBootDriver = None
        self.problem_report: list[str] = []
        self._plan: list[int] = []
        self.last_detail: str = ""
        self._start_time: float = 0.0

    def boot(self) -> None:
        """Starts the boot sequence (First Tier -> Last Tier)"""
        self.mode = BootTask.BOOT
        self._plan = sorted(self.view.tiers.keys())
        self.job_prepary()

    def shutdown(self) -> None:
        """Starts the shutdown sequence (Last Tier -> First Tier)"""
        self.mode = BootTask.SHUTDOWN
        self._plan = sorted(self.view.tiers.keys(), reverse=True)
        self.job_prepary()

    def job_prepary(self) -> None:
        self.current_tier_id = -1
        self.problem_report = []
        self._start_time = perf_counter()
        self._init_ui()
        self._next_tier()
        self.step()

    def step(self) -> None:
        """Take next Tier from job plan and strart/stop it"""

        if self.mode == BootTask.NONE:
            return
        if self.current_tier is None:
            t = "current_tier is None, i={i}, plan={plan}"
            self.view.log.err(t, i=self.current_tier_id, plan=self._plan)
            self._next_tier()
            return
        elif self.current_tier == False:
            self._finalize()
            return
        
        self._render_ui()
        self._start_or_stop_tier(self.current_tier)

        # Monitor Tier state machine
        if self.current_tier.stat in [TierStat.WORKING, TierStat.STOPPED]:
            if self.current_tier.last_result_ok:
                if self.mode == BootTask.BOOT:
                    t = "BOOT: boot: Tier {name} started successful"
                    self.view.log.inf(t, name=self.current_tier.name)
                if self.mode == BootTask.SHUTDOWN:
                    t = "BOOT: shutdown: Tier {name} stopped successful"
                    self.view.log.inf(t, name=self.current_tier.name)
                self._next_tier()
            else:
                self._handle_failure(self.current_tier)

    # TODO in v2: move translations to boot_ui
    def _handle_failure(self, tier: Tier) -> None:
        """Processes failures for both Boot and Shutdown modes with UI feedback."""
        # SHUTDOWN
        if self.mode == BootTask.SHUTDOWN:
            t = "BOOT: shutdown: Tier {name} fail"
            self.view.log.wrn(t, name=tier.name)
            if self._ui:
                msg = self.view.translate(t, name=tier.name)
                self._ui.update_local(0, f"err {msg}")
            self.problem_report.append(tier.name)
            self._next_tier()
            return

        # BOOT
        if self.mode == BootTask.BOOT:
            # First problem for Tier
            if not tier.is_flaky:
                self.restart_tier()
                return
            stuck_system = int(os.environ.get("SANAPO_STUCK_SYSTEM", "0"))
            # Attempts System restart arent spended, Second problem for Tier -> restart System
            if stuck_system < self.view.cfg.SYSTEM_STUCK_REBOOT_MAX:
                t = "BOOT: Tier {name} fail, restart Tier fail, restart System"
                self.view.log.crt(t, name=tier.name)
                if self._ui:
                    msg = self.view.translate(t, name=tier.name)
                    self._ui.update_local(0, f"crt {msg}")
                os.environ[f"SANAPO_STUCK_SYSTEM"] = str(stuck_system + 1)
                self.view.restart()
            # Attems System restart are spended, Second problem for Tier -> ignore
            else:
                t = "BOOT: Tier {name} fail, restart Tier fail, ignore"
                self.view.log.err(t, name=tier.name)
                if self._ui:
                    msg = self.view.translate(t, name=tier.name)
                    self._ui.update_local(0, f"wrn {msg}")
                self.problem_report.append(tier.name)
                self._next_tier()

    def _next_tier(self) -> None:
        self.current_tier_id += 1
        if 0 <= self.current_tier_id < len(self._plan):
            tier_num = self._plan[self.current_tier_id]
            self.current_tier = self.view.tiers.get(tier_num)
        else:
            self.current_tier = False
        
    def _start_or_stop_tier(self, tier: Tier) -> None:
        action = self.mode.value
        if self.mode == BootTask.BOOT and tier.stat in [TierStat.CREATED, TierStat.STOPPED]:
            t = "BOOT: {act} Tier {name} ({num})"
            self.view.log.dbg(t, act=action, name=tier.name, num=tier.layer_num)
            tier.start()
        elif self.mode == BootTask.SHUTDOWN and tier.stat == TierStat.WORKING:
            t = "BOOT: {act} Tier {name} ({num})"
            self.view.log.dbg(t, act=action, name=tier.name, num=tier.layer_num)
            tier.stop()

    # TODO in v2: real Tier restart
    def restart_tier(self) -> None:
        t = "BOOT: Tier {name} fail, restart Tier"
        self.view.log.wrn(t, name=self.current_tier.name)
        if self._ui:
            msg = self.view.translate(t, name=self.current_tier.name)
            self._ui.update_local(50.0, msg)
        self.current_tier.is_flaky = True
        os.environ[f"SANAPO_STUCK_{self.current_tier.name}"] = "1"
        self._start_or_stop_tier(self.current_tier)

    # TODO calc timeout or join 
    def _finalize(self) -> None:
        duration = perf_counter() - self._start_time
        self._start_time = 0.0
        prev_mode = self.mode
        self.mode = BootTask.NONE

        # FIXED: If we are shutting down, explicitly join all remaining OS threads to clear RAM
        if prev_mode == BootTask.SHUTDOWN:
            for manager in list(self.view.managers.values()):
                try:
                    manager.join(timeout=0.1)
                except Exception as e:
                    self.view.log.err(f"join fail, err={e}")

        if prev_mode == BootTask.BOOT: self.view.on_started()
        elif prev_mode == BootTask.SHUTDOWN: self.view.on_stopped()
        t = "BOOT: {job} finished ({d:.2f}sec)"
        self.view.log.inf(t, job=prev_mode.value, d=duration)
        if self._ui:
            msg = self.view.translate(t, job=prev_mode.value, d=duration)
            self._ui.update_global(100.0, msg)
            self._ui.close(prev_mode.value)
            self._ui = None

    # --- ui ---

    def update_sub_progress_ui(self, text: str, ready: int, total: int):
        """Discrete info from Tier for UI granularity"""
        self.last_detail = text
        if self._ui:
            percent = (ready / total * 100) if total > 0 else 0
            self._ui.update_local(percent, text)

    def _init_ui(self) -> None:
        ui_mode = self.view.cfg.BOOT_UI_MODE
        if ui_mode == "GUI":
            self._ui = GUIBootDriver()
        elif ui_mode == "CUI":
            self._ui = CUIBootDriver()

    def _render_ui(self) -> None:
        if not self._ui: return

        total_tiers = len(self._plan)
        # Global progress bar
        global_percent = (self.current_tier_id / total_tiers) * 100
        if self.mode == BootTask.BOOT:
            tpl = "BOOTING | Tier {idx}/{total}: {name}"
        if self.mode == BootTask.SHUTDOWN:
            tpl = "SHUTDOWN | Tier {idx}/{total}: {name}"
        global_text = self.view.translate(
            tpl, 
            idx = self.current_tier_id + 1, 
            total = total_tiers, 
            name = self.current_tier.name
        )
        self._ui.update_global(global_percent, global_text)
        
        # Local progress bar
        local_percent = self.current_tier.get_progress() * 100
        local_text = self.last_detail or f"Processing units... {int(local_percent)}%"
        self._ui.update_local(local_percent, local_text)
