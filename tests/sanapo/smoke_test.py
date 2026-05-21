# tests/sanapo/smoke_test.py
from __future__ import annotations
import sys
import os
import time
import traceback
from typing import TYPE_CHECKING

from sanapo.base_module import BaseModule
from core.drafts.project_enums import EvtType, CmdType
from sanapo.enums import RptType, RptReason, SysType

if TYPE_CHECKING:
    from sanapo.base_unit import UnitModuleView
    from sanapo.protocol import Frame

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


# Prints
def assert_success(test_name: str) -> None:
    """Prints green success status"""
    print(f"\033[92m✓ SUCCESS: {test_name}\033[0m")

def assert_failure(test_name: str, error: Exception | str) -> None:
    """Prints red error status"""
    print(f"\033[91m✗ FAILED: {test_name}\033[0m")
    print(f"\033[91m  Details: {error}\033[0m")
    exit(1)

# Test unit
class DummyWorker(BaseModule):
    """Smoke test unit for messaging verification via UnitModuleView"""
    def __init__(self, view, **kwargs):
        super().__init__(view, **kwargs)
        self.v: UnitModuleView = view
        self.counter: int = 0
        
    def start(self):
        self.v.log.dbg("module start")
        if self.v.addr.unit == "UNIT_RECEIVER":
            self.v.scr.subscribe(cb=self._on_cmd, cmd=CmdType.CMD_TEST)
        self.v.started()

    def step(self) -> bool:
        if self.v.addr.unit == "UNIT_COMMANDER":
            self.counter += 1
            if self.counter % 100 == 0:
                print(f"cmd UNIT_COMMANDER -> UNIT_RECEIVER")
                recipient = self.v.addr_by_str("UNIT_RECEIVER")
                if recipient:
                    p = {"text":f"CMD: Hello to RECEIVER from {self.v.addr.unit}!"}
                    self.v.scr.send_cmd(recipient, CmdType.CMD_TEST, self._on_rpt, payload=p)

    def _on_cmd(self, frame: Frame) -> bool:
        self.v.log.dbg("module _on_cmd")
        self.v.log.dbg(f"was got cmd with p[text]:{frame.payload['text']}")
        time.sleep(0.01)
        p = {"text":f"CMD: Hello to COMMANDER from {self.v.addr.unit}!"}
        self.v.scr.send_rpt(frame.sender,frame.cmd_id, RptType.DONE, p)

    def _on_rpt(self, frame) -> bool:
        self.v.log.dbg("module _on_rpt")
        self.v.log.dbg(f"was got rpt with p[text]:{frame.payload['text']}")

    def stop(self):
        self.v.log.dbg("module stop")



# STEP 1: PROJECT ENUMS IMPORT
t_name = "Importing Project Enums from drafts"
try:
    from core.drafts.project_enums import EvtType, CmdType
    assert_success(t_name)
except ImportError as e:
    assert_failure(t_name, e)


# STEP 2: FRAMEWORK IMPORTS
t_name = "Importing Framework Core Components"
try:
    from sanapo.kernel import Kernel
    from sanapo.views import KernelUserView
    from sanapo.enums import UnitType, ThreadType, EnumRegistry
    assert_success(t_name)
except ImportError as e:
    assert_failure(t_name, e)


# STEP 3: CORE INIT
class TestEnumRegistry:
    def __init__(self):
        self.evt = EvtType
        self.cmd = CmdType

t_name = "Kernel and KernelUserView Assembly"
try:
    reg = TestEnumRegistry() 
    kernel = Kernel(enum_reg=reg)
    api = KernelUserView(kernel) 
    assert_success(t_name)
except Exception as e:
    print("\n\033[91m--- DETAILED CRASH LOG ---")
    traceback.print_exc()
    print("--------------------------\033[0m\n")
    assert_failure(t_name, e)


# STEP 4: INFRASTRUCTURE BUILD
t_name = "Infrastructure Provisioning (Tiers, Threads, Units)"
try:
    print("\n--- Building Infrastructure ---")
    kernel._cfg.BOOT_UI_MODE = "CUI"  
    kernel._cfg.KERNEL_TCT = 0.01

    api.add_tier(layer_num=1, name="TIER_for_RECEIVER")
    api.add_tier(layer_num=2, name="TIER_for_COMMANDER")
    api.add_thread(name="MAIN_POOL", type=ThreadType.TICKABLE, tct=0.02)

    api.add_unit(
        name="UNIT_RECEIVER",
        type=UnitType.TICKABLE,
        m_class=DummyWorker,
        thread_name="MAIN_POOL",
        tier_layer=1,
        tier_name="TIER_for_RECEIVER"
    )

    api.add_unit(
        name="UNIT_COMMANDER",
        type=UnitType.TICKABLE,
        m_class=DummyWorker,
        thread_name="MAIN_POOL",
        tier_layer=2,
        tier_name="TIER_for_COMMANDER"
    )
    assert_success(t_name)
except Exception as e:
    print("\n\033[91m--- DETAILED CRASH LOG ---")
    traceback.print_exc()
    print("--------------------------\033[0m\n")
    assert_failure(t_name, e)


# STEP 5: CASCADE IGNITION
print("\n--- Igniting System ---")
t_name = "System Lifecycle: Boot sequence execution"
try:
    api.start()
    start_run = time.perf_counter()
    while time.perf_counter() - start_run < 3.0:
        kernel.loop() 
    assert_success(t_name)
except KeyboardInterrupt:
    print("Interrupted by user.")
except Exception as e:
    print("\n\033[91m--- DETAILED CRASH LOG ---")
    traceback.print_exc()
    print("--------------------------\033[0m\n")
    assert_failure(t_name, e)


# STEP 6: GRACEFUL SHUTDOWN
print("\n--- Stopping System ---")
t_name = "System Lifecycle: Shutdown sequence execution"
try:
    api.stop()
    start_stop = time.perf_counter()
    while time.perf_counter() - start_stop < 2.0:
        kernel.loop()
    assert_success(t_name)

except Exception as e:
    print("\n\033[91m--- DETAILED CRASH LOG ---")
    traceback.print_exc()
    print("--------------------------\033[0m\n")
    assert_failure(t_name, e)

print(f"\n\033[92m✓ ALL TESTS PASSED: Framework V1 Core works seamlessly!\033[0m")

