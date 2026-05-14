import sys
import os
import time
import traceback
from time import perf_counter

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sanapo.base_module import BaseModule


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
    """Test unit for tier start check"""
    def start(self):
        time.sleep(0.1)
        self._u.start_timeout = 0.35
        self._u.log.inf("DummyWorker: I am awake and working!")
        self._u.started()

    def step(self) -> bool:
        return True

    def stop(self):
        self._u.log.inf("DummyWorker: Going to sleep...")


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
    kernel._cfg.SYSTEM_NAME = "LOCAL"

    api.add_tier(layer_num=1, name="tier_1")
    api.add_tier(layer_num=2, name="tier_2")
    api.add_thread(name="MAIN_POOL", type=ThreadType.TICKABLE, tct=0.02)

    api.add_unit(
        name="UNIT_1",
        type=UnitType.TICKABLE,
        m_class=DummyWorker,
        thread_name="MAIN_POOL",
        tier_layer=1,
        tier_name="tier_1"
    )

    api.add_unit(
        name="UNIT_2",
        type=UnitType.TICKABLE,
        m_class=DummyWorker,
        thread_name="MAIN_POOL",
        tier_layer=2,
        tier_name="tier_2"
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
    start_run = perf_counter()
    while perf_counter() - start_run < 3.0:
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
    start_stop = perf_counter()
    while perf_counter() - start_stop < 2.0:
        kernel.loop()
    assert_success(t_name)
except Exception as e:
    print("\n\033[91m--- DETAILED CRASH LOG ---")
    traceback.print_exc()
    print("--------------------------\033[0m\n")
    assert_failure(t_name, e)

print(f"\n\033[92m✓ ALL TESTS PASSED: Framework V1 Core works seamlessly!\033[0m")

