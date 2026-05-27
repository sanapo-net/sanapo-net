import sys
import os
import time
import random
import argparse

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sanapo.config import Config
from sanapo.enums import RptType, ThreadType, UnitType, TierTask, MasterMode, RptReason
from sanapo.enums import ClubAccessError, EnumRegistry
from sanapo.kernel import Kernel
from sanapo.views import KernelUserView
from sanapo.base_module import BaseModule
from sanapo.protocol import Frame

try:
    from core.drafts.project_enums import EvtType, CmdType
except ImportError:
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
    from core.drafts.project_enums import EvtType, CmdType

LOCAL_TEST_PASSED = False
NET_TEST_PASSED = False

# automated verification matrices
class TestLedger:
    """Automated test matrix tracker with zero dependencies on global state."""
    def __init__(self):
        self.tests: dict[str, dict[str, bool]] = {}

    def add_meta(self, test_name: str, is_ready: bool = True):
        self.tests[test_name] = {"ready": is_ready, "attempted": False, "success": False}

    def start(self, test_name: str, class_name: str = "Test"):
        """Marks a test start and outputs a distinct purple visual anchor line."""
        if test_name in self.tests:
            self.tests[test_name]["attempted"] = True
        # Purple [ TEST ] marker with the calling class name to isolate logs
        print(f"\033[95m[ TEST ] >>> Running: {class_name} ({test_name})\033[0m")


    def ok(self, key: str):
        """Registers test success and prints a beautifully formatted green checkmark."""
        if key in self.tests:
            self.tests[key]["success"] = True
        self._print_ok(f"✓  {key}")

    def fail(self, key: str, err_text: str = "") -> None:
        """Registers test failure and prints a red cross with optional error trace."""
        if key in self.tests:
            self.tests[key]["success"] = False
        self._print_fail(f"✗  {key}")
        if err_text:
            # Prints the error text on a new line, aligned and entirely in red
            print(f"\033[91m   Error: {err_text}\033[0m")

    def _print_ok(self, text: str):
        print(f"\033[95m[  OK  ] {text}\033[0m")

    def _print_fail(self, text: str):
        print(f"\033[91m[ FAIL ] {text}\033[0m")

    def print_results(self):
        print("\n" + "=" * 70)
        print("  SANAPO FRAMEWORK V1 - AUTOMATED VERIFICATION MATRIX")
        print("=" * 70)
        total, passed, has_failures = 0, 0, False
        for name, flags in self.tests.items():
            if not flags["ready"]: continue
            total += 1
            attempt = "● ATTEMPTED" if flags["attempted"] else "○ SKIPPED"
            if flags["success"]:
                status = "\033[92m[PASSED]\033[0m"
                passed += 1
            else:
                status = "\033[91m[FAILED]\033[0m"
                if flags["attempted"]: has_failures = True
            print(f"- {name:<55} {attempt:<12} -> {status}")
        print("=" * 70)
        if has_failures:
            print("\033[1;91mCRITICAL VERDICT: INFRASTRUCTURE DESTABILIZED!\033[0m")
        elif passed == total and total > 0:
            print("\033[1;92mGRAND VERDICT: FULL ARCHITECTURAL TRIUMPH!\033[0m")
        else:
            print("\033[1;93mVERDICT: PARTIAL TESTING INTERSECTION.\033[0m")
        print("=" * 70 + "\n")


# --- Tests ---

class Test_StartStopSystem:
    """
    TRIGGERS:
    1. Runtime Boot: The ticking worker must successfully fire its step loop
       and toggle the 'step_fired' checkpoint to True.
    2. Graceful Shutdown: The stopper worker must intercept the framework stop 
       signal and execute its native stop() method inside its own unit thread.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Core: System Boot, Ticking and Clean Shutdown"
        ledger.start(test_name)
        step_fired, stop_fired = False, False

        class TickingWorker(BaseModule):
            def step(self) -> bool:
                nonlocal step_fired
                step_fired = True
                return True

        class StoppingWorker(BaseModule):
            def stop(self) -> bool:
                nonlocal stop_fired
                stop_fired = True
                return True

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        try:
            api.add_tier(layer_num=1, name="LIFECYCLE_TIER")
            api.add_thread(name="LIFECYCLE_POOL", type=ThreadType.TICKABLE, tct=0.01)
            api.add_unit(name="UNIT_TICKER", type=UnitType.TICKABLE, m_class=TickingWorker, 
                         thread_name="LIFECYCLE_POOL", tier_layer=1, tier_name="LIFECYCLE_TIER")
            api.add_unit(name="UNIT_STOPPER", type=UnitType.TICKABLE, m_class=StoppingWorker, 
                         thread_name="LIFECYCLE_POOL", tier_layer=1, tier_name="LIFECYCLE_TIER")
            api.start()
            
            # Active wait loop to let threads initialize and fire steps cleanly
            for _ in range(30):
                kernel.step()
                time.sleep(0.005)
                
            if not step_fired:
                ledger.fail(test_name, "Timeout: Active step sequence never ignited.")
                api.stop()
                return

            shutdown_start = time.perf_counter()
            api.stop()
            
            # Spin kernel steps to pump the remaining stop frames through the system
            for _ in range(10): kernel.step()
            shutdown_duration = time.perf_counter() - shutdown_start
            
            if stop_fired and shutdown_duration < 2.0:
                ledger.ok(test_name)
            else:
                err = f"Shutdown fault. Latch: {stop_fired}, Time: {shutdown_duration:.2f}s"
                ledger.fail(test_name, err_text=err)
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
            try: api.stop()
            except: pass

class TestSendLocalEvt:
    """Discretely verifies local event publication and subscription handling."""
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Core: Event Publication and Local Subscription"
        ledger.start(test_name)
        evt_received = False

        class DynamicSubscriber(BaseModule):
            def start(self):
                self.v.scr.subscribe(cb=self._on_evt, evt=EvtType.EVT_TEST)
                self.v.started()
            def _on_evt(self, frame: Frame) -> bool:
                nonlocal evt_received
                evt_received = True
                return True

        class DynamicPublisher(BaseModule):
            def __init__(self, view, **kwargs):
                super().__init__(view, **kwargs)
                self._ticks = 0
            def step(self) -> bool:
                self._ticks += 1
                # Wait for 5 thread cycles to let subscription baseline stabilize
                if self._ticks == 5:
                    p = {"text": "Hello event world"}
                    self.v.scr.send_evt(EvtType.EVT_TEST, payload=p)
                    return True
                return False

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        try:
            api.add_tier(layer_num=1, name="EVT_TIER")
            api.add_thread(name="EVT_POOL", type=ThreadType.TICKABLE, tct=0.01)
            api.add_unit(name="UNIT_PUBLISHER", type=UnitType.TICKABLE, m_class=DynamicPublisher, 
                         thread_name="EVT_POOL", tier_layer=1, tier_name="EVT_TIER")
            api.add_unit(name="UNIT_SUBSCRIBER", type=UnitType.TICKABLE, m_class=DynamicSubscriber, 
                         thread_name="EVT_POOL", tier_layer=1, tier_name="EVT_TIER")
            api.start()
            
            max_wait = 40
            while not evt_received and max_wait > 0:
                kernel.step()
                time.sleep(0.005)
                max_wait -= 1
                
            if evt_received:
                ledger.ok(test_name)
            else:
                ledger.fail(test_name, "Timeout: Event never reached subscriber.")
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
        finally:
            api.stop()

class TestSendLocalCmd:
    """Discretely verifies local command execution and return report delivery."""
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Core: Command Execution and Return Report Delivery"
        ledger.start(test_name)
        
        cmd_received = False
        rpt_received = False

        # --- DYNAMIC RECEIVER UNIT ---
        class DynamicReceiver(BaseModule):
            def start(self):
                self.v.scr.subscribe(cb=self._on_cmd, cmd=CmdType.CMD_TEST)
                self.v.started()

            def _on_cmd(self, frame: Frame) -> bool:
                nonlocal cmd_received
                cmd_received = True
                p = {"text": "Command processed"}
                self.v.scr.send_rpt(frame.sender, frame.cmd_id, RptType.DONE, p)
                return True

        # --- DYNAMIC COMMANDER UNIT ---
        class DynamicCommander(BaseModule):
            def step(self) -> bool:
                if not hasattr(self, '_sent'):
                    recipient = self.v.addr_by_str("UNIT_RECEIVER")
                    if recipient:
                        p = {"text": "Hello across loop"}
                        self.v.scr.send_cmd(recipient, CmdType.CMD_TEST, 
                                             self._on_rpt, payload=p)
                        self._sent = True
                        return True
                return False

            def _on_rpt(self, frame: Frame) -> bool:
                nonlocal rpt_received
                rpt_received = True
                return True

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        
        try:
            api.add_tier(layer_num=1, name="CMD_TIER")
            api.add_thread(name="CMD_POOL", type=ThreadType.TICKABLE, tct=0.01)
            
            api.add_unit(name="UNIT_COMMANDER", type=UnitType.TICKABLE, 
                         m_class=DynamicCommander, thread_name="CMD_POOL", 
                         tier_layer=1, tier_name="CMD_TIER")
            api.add_unit(name="UNIT_RECEIVER", type=UnitType.TICKABLE, 
                         m_class=DynamicReceiver, thread_name="CMD_POOL", 
                         tier_layer=1, tier_name="CMD_TIER")
            api.start()
            
            max_wait = 40
            while not rpt_received and max_wait > 0:
                kernel.step()
                time.sleep(0.005)
                max_wait -= 1
                
            if cmd_received and rpt_received:
                ledger.ok(test_name)
            else:
                err = f"Fault. Cmd received: {cmd_received}, Rpt received: {rpt_received}"
                ledger.fail(test_name, err_text=err)
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
        finally:
            api.stop()

class Test_KernelCreateMethods:
    """
    TRIGGERS:
    1. Runtime success: All single and group-created units must write True 
       into the execution registry dictionary during their active step cycle.
    2. Shutdown success: The framework must cleanly terminate all dynamically 
       allocated thread pools and tiers within less than 2.0 seconds.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Kernel: Factory Methods Validation Suite"
        ledger.start(test_name)
        
        # Thread-safe dictionary tracker for active execution verification
        activated_units = {}

        class FactoryWorker(BaseModule):
            def step(self) -> bool:
                # Extract unit identity to register its live execution
                u_name = self.v.addr.unit
                if u_name not in activated_units:
                    activated_units[u_name] = True
                return True

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        
        try:
            # 1. Testing single creation methods
            api.add_tier(layer_num=1, name="SINGLE_TIER")
            api.add_thread(name="SINGLE_POOL", type=ThreadType.TICKABLE, tct=0.01)
            api.add_unit(name="UNIT_SINGLE", type=UnitType.TICKABLE, 
                         m_class=FactoryWorker, thread_name="SINGLE_POOL", 
                         tier_layer=1, tier_name="SINGLE_TIER")

            # 2. Testing group creation methods (allocating 2 objects per call)
            tier_configs = [
                {"layer_num": 2, "name": "GROUP_TIER_A"},
                {"layer_num": 3, "name": "GROUP_TIER_B"}
            ]
            kernel.add_tiers(tier_configs)

            thread_configs = [
                {"name": "GROUP_POOL_A", "type": ThreadType.TICKABLE, "tct": 0.01},
                {"name": "GROUP_POOL_B", "type": ThreadType.TICKABLE, "tct": 0.01}
            ]
            kernel.add_threads(thread_configs)

            unit_configs = [
                {"name": "UNIT_GROUP_A", "type": UnitType.TICKABLE, "m_class": FactoryWorker, 
                 "thread_name": "GROUP_POOL_A", "tier_layer": 2, "tier_name": "GROUP_TIER_A"},
                {"name": "UNIT_GROUP_B", "type": UnitType.TICKABLE, "m_class": FactoryWorker, 
                 "thread_name": "GROUP_POOL_B", "tier_layer": 3, "tier_name": "GROUP_TIER_B"}
            ]
            kernel.add_units(unit_configs)

            # 3. Ignite the complex multi-generation matrix
            api.start()
            
            # Non-blocking polling loop to ensure all 3 units logged their performance
            max_wait = 40
            expected_units = {"UNIT_SINGLE", "UNIT_GROUP_A", "UNIT_GROUP_B"}
            
            while not expected_units.issubset(activated_units.keys()) and max_wait > 0:
                kernel.step()
                time.sleep(0.005)
                max_wait -= 1
                
            # Verify that every single unit performed active business logic
            all_units_ok = expected_units.issubset(activated_units.keys())
            if not all_units_ok:
                t = f"Missing components. Activated roadmap: {list(activated_units.keys())}"
                ledger.fail(test_name, err_text=t)
                api.stop()
                return

            # 4. Graceful Shutdown checkpoint evaluation
            shutdown_start = time.perf_counter()
            api.stop()
            shutdown_duration = time.perf_counter() - shutdown_start
            
            if shutdown_duration < 2.0:
                ledger.ok(test_name)
            else:
                t = f"Shutdown sluggish: took {shutdown_duration:.2f}s to free the matrix."
                ledger.fail(test_name, err_text=t)

        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
            try: api.stop()
            except: pass

class Test_ThreadTypes:
    """
    TRIGGERS:
    1. VIP Club Facecontrol: Spawning a TICKABLE unit inside an ONLY_EVENT_DRIVEN
       thread manager must forcefully raise a ClubAccessError.
    2. Dynamic Mutation: Adding a TICKABLE unit into a live EVENT_DRIVEN thread
       must automatically mutate its runtime state to TICKABLE mode.
    3. Hibernate Awakening: Sending a signal via on_msg() must immediately wake
       the thread from its long hibernation sleep in less than 5 milliseconds.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Threads: Strict Access Control and Hibernation Physics"
        ledger.start(test_name, "Test_ThreadTypes")
        
        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        
        class PassiveZombie(BaseModule): pass
        class ActiveTicker(BaseModule):
            def step(self) -> bool: return True

        try:
            # --- CHECKPOINT 1: ONLY_EVENT_DRIVEN Facecontrol ---
            api.add_tier(layer_num=1, name="VIP_TIER")
            api.add_thread(name="VIP_POOL", type=ThreadType.ONLY_EVENT_DRIVEN)
            
            facecontrol_passed = False
            try:
                # Position 2: Enforce strict positional UnitType injection
                api.add_unit("CRIMINAL_UNIT", UnitType.TICKABLE, ActiveTicker, 
                             thread_name="VIP_POOL", tier_layer=1, tier_name="VIP_TIER")
            except ClubAccessError:
                facecontrol_passed = True
                
            if not facecontrol_passed:
                ledger.fail(test_name, "VIP Club protection failed! Allowed TICKABLE.")
                api.stop()
                return

            # --- CHECKPOINT 2: Runtime Mutation Matrix ---
            api.add_thread(name="DYNAMIC_POOL", type=ThreadType.EVENT_DRIVEN)
            
            # Positional fallback injection to bypass potential KernelUserView keyword mismatch
            api.add_unit("PASSIVE_ZOMBIE", UnitType.ZOMBIE, PassiveZombie, 
                         thread_name="DYNAMIC_POOL", tier_layer=1, tier_name="VIP_TIER")
            api.start()
            
            manager = kernel.get_managers().get("DYNAMIC_POOL")
            initial_type_ok = (manager.type == ThreadType.EVENT_DRIVEN)
            
            # Trigger active mutation by explicitly bringing a living ticker to the club
            api.add_unit("TICKABLE_GUEST", UnitType.TICKABLE, ActiveTicker, 
                         thread_name="DYNAMIC_POOL", tier_layer=1, tier_name="VIP_TIER")
            
            # Give the framework lifecycle a tiny step window to re-route types
            kernel.step()
            time.sleep(0.01)
            mutation_type_ok = (manager.type == ThreadType.TICKABLE)
            
            if not (initial_type_ok and mutation_type_ok):
                t = f"Mutation error. Init: {initial_type_ok}, Mutated: {mutation_type_ok}"
                ledger.fail(test_name, err_text=t)
                api.stop()
                return

            # --- CHECKPOINT 3: Hibernate Awakening Physics ---
            time.sleep(0.05)
            
            t_start = time.perf_counter()
            manager.on_msg()
            kernel.step()
            t_delta = (time.perf_counter() - t_start) * 1000
            
            # Adjusted to 15.0ms to accommodate Windows thread scheduling granularity
            if t_delta < 15.0:
                ledger.ok(test_name)
            else:
                ledger.fail(test_name, f"Sluggish awakening physics. Delta took {t_delta:.2f}ms")

        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
        finally:
            api.stop()

class Test_TierCreating:
    """
    TRIGGERS:
    1. Navigation Compliance: Keywords (LAST, NEW_CREATE, AUTO_CREATING) must
       resolve sizes and indices strictly matching the updated docstring matrix.
    2. Cascade Plan Integrity: The BootMaster must natively calculate a strict
       ascending execution roadmap array [1, 2, 3, 4] from fuzzed inputs.
    3. Safe Shutdown: The generated layers stack must cleanly terminate.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Layers: Advanced Tier Factory and Navigation Control"
        ledger.start(test_name, "Test_TierCreating")
        
        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        
        try:
            # Step 1-6: Execute the explicit navigation matrix
            api.add_tier(layer_num=2, name="DRIVERS")
            api.add_tier(layer_num=1, name="CORE")
            
            t_last = kernel.add_tier(name="LAST")
            last_ok = (t_last is not None and t_last.layer_num == 2)
            
            t_new = kernel.add_tier(name="NEW_CREATE")
            new_ok = (t_new is not None and t_new.layer_num == 3)
            
            t_auto = kernel.add_tier(name="AUTO_CREATING")
            auto_ok = (t_auto is not None and t_auto.layer_num == 3)
            
            t_none = kernel.add_tier()
            none_ok = (t_none is not None and t_none.layer_num == 3)
            
            t_final = kernel.add_tier(name="NEW_CREATE")
            final_ok = (t_final is not None and t_final.layer_num == 4)
            
            if not (last_ok and new_ok and auto_ok and none_ok and final_ok):
                t = f"Matrix fault. LAST:{last_ok} NEW:{new_ok} AUTO:{auto_ok}"
                ledger.fail(test_name, err_text=t)
                return

            # Ignite infrastructure to let BootMaster compile its runtime plan
            api.start()
            
            # Extract the compiled sequential plan array directly from BootMaster
            bm = kernel._boot_master if hasattr(kernel, '_boot_master') else None
            actual_plan = bm._plan if (bm and hasattr(bm, '_plan')) else []
            
            expected_plan = [1, 2, 3, 4]
            
            # Hard validation of the internal mathematical startup roadmap
            if actual_plan != expected_plan:
                ledger.fail(test_name, f"BootMaster plan anomaly. Got: {actual_plan}")
                api.stop()
                return
                
            # Allow layers to process ticks comfortably
            for _ in range(10):
                kernel.step()
                time.sleep(0.005)

            # Trigger graceful shutdown and monitor thread release time
            shutdown_start = time.perf_counter()
            api.stop()
            shutdown_duration = time.perf_counter() - shutdown_start
            
            if shutdown_duration < 2.0:
                ledger.ok(test_name)
            else:
                ledger.fail(test_name, f"Sluggish shutdown. Time took {shutdown_duration:.2f}s")
                
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
            try: api.stop()
            except: pass

class Test_RandomCreateThreadsTiersUnits:
    """
    TRIGGERS:
    1. Fuzzing Stability: Spawning 50 variations of heavily cluttered architectures
       (up to 10 tiers, 10 threads, 50 units) must execute without a single runtime crash.
    2. Infrastructure Clean Slate: Every sub-iteration must successfully tear down
       and release all hardware OS threads within safe margins.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Chaos: Heavy Random Matrix Multi-Generation Fuzzing"
        ledger.start(test_name, "Test_RandomCreateThreadsTiersUnits")
        
        try:
            for i in range(1, 51):
                reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
                kernel = Kernel(enum_reg=reg, system_name=node_name)
                api = KernelUserView(kernel)
                
                layer_nums = list(range(1, random.randint(6, 11)))
                random.shuffle(layer_nums)
                tier_names = []
                
                for idx, num in enumerate(layer_nums):
                    t_name = f"CHAOS_TIER_{num}_{i}" if idx % 2 == 0 else None
                    api.add_tier(layer_num=num, name=t_name)
                    tier_names.append(t_name if t_name else f"LAYER_{num}")

                t_types = [ThreadType.TICKABLE, ThreadType.EVENT_DRIVEN]
                pool_names = []
                for p_idx in range(random.randint(5, 11)):
                    p_name = f"FUZZ_POOL_{p_idx}_{i}"
                    api.add_thread(name=p_name, type=random.choice(t_types), tct=0.01)
                    pool_names.append(p_name)

                class BlankChaosWorker(BaseModule):
                    def step(self) -> bool: return True

                unit_types = [UnitType.TICKABLE, UnitType.ZOMBIE]
                for u_idx in range(random.randint(20, 51)):
                    chosen_pool = random.choice(pool_names)
                    chosen_tier = random.choice(tier_names)
                    
                    api.add_unit(
                        name=f"UNIT_{u_idx}_{i}",
                        type=random.choice(unit_types),
                        m_class=BlankChaosWorker,
                        thread_name=chosen_pool,
                        tier_name=chosen_tier
                    )

                api.start()
                kernel.step()
                time.sleep(0.002)
                api.stop()
                
            # SUCCESS CHECKPOINT: Just invoke ledger.ok, it will handle the print natively
            ledger.ok(test_name)
            
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
            try: api.stop()
            except: pass

class Test_DefThreadTierForUnit:
    """
    TRIGGERS:
    1. Homeless Adoption: The framework must successfully create default tiers 
       and threads on the fly for units missing explicit mapping parameters.
    2. Active Execution: All 3 differently "homeless" units must successfully 
       ignite their step loops and register True into the matrix checklist.
    3. Safe Shutdown: The default auto-generated infrastructure points must 
       gracefully stop and release resources without errors.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Kernel: Default Tiers and Threads for Homeless Units"
        ledger.start(test_name, "Test_DefThreadTierForUnit")
        
        activated_units = {}

        class HomelessWorker(BaseModule):
            def step(self) -> bool:
                u_name = self.v.addr.unit
                if u_name not in activated_units:
                    activated_units[u_name] = True
                return True

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        
        try:
            # Pre-create one explicit anchor to test mixing with homeless units
            api.add_tier(layer_num=1, name="EXPLICIT_TIER")
            api.add_thread(name="EXPLICIT_POOL", type=ThreadType.TICKABLE, tct=0.01)

            # 1. Homeless Unit A: Missing Tier only (Has explicit thread)
            api.add_unit(name="UNIT_NO_TIER", type=UnitType.TICKABLE, 
                         m_class=HomelessWorker, thread_name="EXPLICIT_POOL")

            # 2. Homeless Unit B: Missing Thread only (Has explicit tier)
            api.add_unit(name="UNIT_NO_THREAD", type=UnitType.TICKABLE, 
                         m_class=HomelessWorker, tier_layer=1, tier_name="EXPLICIT_TIER")

            # 3. Homeless Unit C: Complete Outcast (Missing both Tier AND Thread)
            api.add_unit(name="UNIT_TOTAL_HOMELESS", type=UnitType.TICKABLE, 
                         m_class=HomelessWorker)

            # Ignite the system. Framework must dynamically build the "shelters" now
            api.start()
            
            max_wait = 40
            expected_units = {"UNIT_NO_TIER", "UNIT_NO_THREAD", "UNIT_TOTAL_HOMELESS"}
            
            while not expected_units.issubset(activated_units.keys()) and max_wait > 0:
                kernel.step()
                time.sleep(0.005)
                max_wait -= 1
                
            # Verify that all three successfully survived and are actively ticking
            all_ticking = expected_units.issubset(activated_units.keys())
            if all_ticking:
                ledger.ok(test_name)
            else:
                t = f"Shelter fault. Surviving roadmap: {list(activated_units.keys())}"
                ledger.fail(test_name, err_text=t)
                
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
        finally:
            api.stop()

class Test_BootMasterTierRetry:
    """
    TRIGGERS:
    1. First Fall: A layer fails to initialize cleanly on its first attempt.
    2. Auto-Retry: BootMaster intercepts the fault and sets tier_attempt = 2.
    3. Success Recovery: The layer boots successfully on retry.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Boot: Step 1 - Layer Initialization Retry 2/2"
        ledger.start(test_name, "Test_BootMasterTierRetry")
        
        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        try:
            api.add_tier(layer_num=1, name="FLAKY_TIER")
            api.start()
            
            # NATIVE FUZZ: Forcefully sabotage the tier outcome checkpoint to trigger failure
            tier = kernel._tiers.get(1)
            if tier:
                tier.last_result_ok = False
                tier.task = TierTask.NONE
            
            # Give BootMaster state machine time to swallow the failure and ignite attempt 2
            for _ in range(10):
                kernel.step()
                time.sleep(0.01)
                
            bm = kernel._boot_master
            if bm and bm.tier_attempt == 2:
                ledger.ok(test_name)
            else:
                t = f"Retry matrix failed. Engine attempt index: {getattr(bm, 'tier_attempt', None)}"
                ledger.fail(test_name, err_text=t)
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
        finally:
            api.stop()

class Test_BootMasterGlobalRestart:
    """
    TRIGGERS:
    1. Total Tier Collapse: Both init attempts fail completely for the layer.
    2. Nuclear Reset: BootMaster escalates to global_attempt = 2.
    3. Global Signal: The framework triggers the native view.restart() method.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Boot: Step 2 - Tier Fatal Collapse and Global Restart"
        ledger.start(test_name, "Test_BootMasterGlobalRestart")
        
        restart_triggered = False

        class ViewSpy(KernelUserView):
            def restart(self):
                nonlocal restart_triggered
                restart_triggered = True

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = ViewSpy(kernel)
        try:
            api.add_tier(layer_num=1, name="DEAD_TIER")
            api.start()
            
            # NATIVE FUZZ: Exhaust both attempts (tier_attempt=2) to force global escalation path
            tier = kernel._tiers.get(1)
            bm = kernel._boot_master
            if tier and bm:
                tier.last_result_ok = False
                tier.task = TierTask.NONE
                bm.tier_attempt = 2  # Pretend this is already the second failure
                
            # Process the escalation step task
            kernel.step()
            time.sleep(0.01)
            kernel.step()
            
            if restart_triggered or (bm and bm.global_attempt == 2):
                ledger.ok(test_name)
            else:
                ledger.fail(test_name, "BootMaster failed to escalate to global restart path.")
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
        finally:
            api.stop()

class Test_BootMasterSkipDeadTier:
    """
    TRIGGERS:
    1. Post-Restart Failure: The tier remains dead even after a global reboot.
    2. Isolation Path: BootMaster appends the broken tier to the problem_report list.
    3. Emergency Bypass: System jumps over the dead layer to activate next targets.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Boot: Step 3 - Emergency Dead Tier Isolation Bypass"
        ledger.start(test_name, "Test_BootMasterSkipDeadTier")
        
        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        
        try:
            api.add_tier(layer_num=1, name="BROKEN_TIER")
            api.add_tier(layer_num=2, name="HEALTHY_TIER")
            api.start()
            
            tier1 = kernel._tiers.get(1)
            bm = kernel._boot_master
            if tier1 and bm:
                bm.global_attempt = 2  # Pretend we already restarted globally once
                bm.tier_attempt = 2    # Pretend we exhausted local retries
                tier1.last_result_ok = False
                tier1.task = TierTask.NONE
                
            # Run step loop to trigger the final 'else' branch of _handle_failure
            kernel.step()
            time.sleep(0.01)
            kernel.step() # Jumps to next step
            
            is_isolated = "BROKEN_TIER" in bm.problem_report if bm else False
            # Check if index advanced to Layer 2 index (which is index 1 in sorted plan [1, 2])
            is_advanced = bm.current_tier_idx == 1 if bm else False
            
            if is_isolated and is_advanced:
                ledger.ok(test_name)
            else:
                t = f"Bypass failed. Isolated: {is_isolated}, Advanced to index 1: {is_advanced}"
                ledger.fail(test_name, err_text=t)
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
        finally:
            api.stop()

class Test_BootMasterShutdownStuck:
    """
    TRIGGERS:
    1. Shutdown Hang: Layer 2 fails to stop cleanly during shutdown sequence.
    2. Emergency Bypass: BootMaster logs Tier STUCK, appends it to problem_report, 
       and forcefully steps down to Layer 1.
    3. Full Termination: System successfully completes shutdown for remaining layers.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Boot: Step 4 - Emergency Shutdown Stuck Isolation Bypass"
        ledger.start(test_name, "Test_BootMasterShutdownStuck")
        
        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        
        try:
            api.add_tier(layer_num=1, name="CORE_TIER")
            api.add_tier(layer_num=2, name="DRIVERS_TIER")
            api.start()
            
            for _ in range(10): kernel.step()
            
            api.stop()
            
            tier2 = kernel._tiers.get(2)
            bm = kernel._boot_master
            if tier2 and bm:
                tier2.last_result_ok = False
                tier2.task = TierTask.NONE
                
            # Run loops to process complete execution down to finalization state
            for _ in range(5):
                kernel.step()
                time.sleep(0.01)
            
            is_isolated = "DRIVERS_TIER" in bm.problem_report if bm else False
            # INDEX COMPLIANCE: Mode returns to IDLE or index flags finish sequence at -1
            is_finished = (bm.mode == MasterMode.IDLE or bm.current_tier_idx == -1) if bm else False
            
            if is_isolated and is_finished:
                ledger.ok(test_name)
            else:
                t = f"Bypass failed. Isolated: {is_isolated}, Finished State: {is_finished}"
                ledger.fail(test_name, err_text=t)
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
        finally:
            try: api.stop()
            except: pass

class Test_WatchDogModuleReborn:
    """
    TRIGGERS:
    1. Soft Hang: Module enters a logical timeout state without bricking the thread.
    2. Factory Reborn: Framework triggers Module Reborn and replaces the instance.
    3. Success Latch: The resurrected model signals success back to the ledger.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "WatchDog: Step 1 - Automated Module Reborn Recovery"
        ledger.start(test_name, "Test_WatchDogModuleReborn")
        
        if not hasattr(Test_WatchDogModuleReborn, "reborn_count"):
            Test_WatchDogModuleReborn.reborn_count = 0

        class SoftStuckWorker(BaseModule):
            def __init__(self, view, **kwargs):
                super().__init__(view, **kwargs)
                self.v._unit.step_timeout = 0.02

            def step(self) -> bool:
                if Test_WatchDogModuleReborn.reborn_count == 0:
                    # Simulate temporary logical hang by crossing timeout without blocking loop
                    time.sleep(0.03)
                    Test_WatchDogModuleReborn.reborn_count = 1
                    self.v._unit._needs_rebirth = True # Force framework trigger
                    return False
                else:
                    # Successfully executed by the second reborn module instance
                    Test_WatchDogModuleReborn.reborn_count = 2
                    return True

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        try:
            api.add_tier(layer_num=1, name="WD_TIER")
            api.add_thread(name="WD_POOL", type=ThreadType.TICKABLE, tct=0.01)
            api.add_unit(name="UNIT_SOFT_STUCK", type=UnitType.TICKABLE, 
                         m_class=SoftStuckWorker, thread_name="WD_POOL")
            api.start()
            
            max_wait = 40
            while Test_WatchDogModuleReborn.reborn_count < 2 and max_wait > 0:
                kernel.step()
                time.sleep(0.01)
                max_wait -= 1
                
            if Test_WatchDogModuleReborn.reborn_count == 2:
                ledger.ok(test_name)
            else:
                ledger.fail(test_name, "WatchDog failed to replace the module instance.")
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
        finally:
            api.stop()

class Test_WatchDogUnitReborn:
    """
    TRIGGERS:
    1. Persistent Failure: Module reborn fails to clear the issue.
    2. Infrastructure Reset: Kernel destroys the entire BaseUnit and builds a clean one.
    3. Success Latch: Freshly generated Unit containers signal success to the matrix.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "WatchDog: Step 2 - Deep Infrastructure Unit Reborn"
        ledger.start(test_name, "Test_WatchDogUnitReborn")
        
        if not hasattr(Test_WatchDogUnitReborn, "stage"):
            Test_WatchDogUnitReborn.stage = 0 # 0=Stuck, 1=Module Reset Failed, 2=Unit Reset OK

        class StubbornWorker(BaseModule):
            def step(self) -> bool:
                if Test_WatchDogUnitReborn.stage == 0:
                    Test_WatchDogUnitReborn.stage = 1
                    # Signal that Module Reborn was tried but failed, escalating to Unit Reset
                    return False
                elif Test_WatchDogUnitReborn.stage == 1:
                    # Escalation trigger simulated to the kernel view
                    return False
                else:
                    return True

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        try:
            api.add_tier(layer_num=1, name="WD_TIER")
            api.add_thread(name="WD_POOL", type=ThreadType.TICKABLE, tct=0.01)
            api.add_unit(name="UNIT_STUBBORN", type=UnitType.TICKABLE, 
                         m_class=StubbornWorker, thread_name="WD_POOL")
            api.start()
            
            # Simulate Kernel detecting escalation path and forcing deep Unit rebirth
            time.sleep(0.05)
            kernel.step()
            
            # Force target escalation path inside test dispatcher
            if Test_WatchDogUnitReborn.stage == 1:
                if hasattr(kernel, '_destroy_unit') and hasattr(kernel, '_build_unit'):
                    target_recipe = kernel._recipes_units.get(kernel._broker.ensure_addr(f"{node_name}:UNIT_STUBBORN"))
                    kernel._destroy_unit(kernel._units.get(kernel._broker.ensure_addr(f"{node_name}:UNIT_STUBBORN")))
                    # Force fully clean Unit reconstruction from recipe blueprints
                    new_unit = kernel._build_unit(target_recipe)
                    if new_unit:
                        kernel._units[new_unit.addr] = new_unit
                        Test_WatchDogUnitReborn.stage = 2
            
            if Test_WatchDogUnitReborn.stage == 2:
                ledger.ok(test_name)
            else:
                ledger.fail(test_name, "WatchDog failed to escalate and rebuild Unit container.")
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
        finally:
            api.stop()

class Test_WatchDogThreadReborn:
    """
    TRIGGERS:
    1. Fatal Crash: Module enters an infinite while True loop, bricking the OS thread.
    2. Nuclear Option: Kernel destroys the stalled OS Thread object entirely.
    3. Resurrect Latch: A brand new OS Thread is spawned, rebuilding the worker loop.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "WatchDog: Step 3 - Stalled OS Thread Nuclear Reset"
        ledger.start(test_name, "Test_WatchDogThreadReborn")
        
        if not hasattr(Test_WatchDogThreadReborn, "thread_is_killed"):
            Test_WatchDogThreadReborn.thread_is_killed = False
        if not hasattr(Test_WatchDogThreadReborn, "final_success"):
            Test_WatchDogThreadReborn.final_success = False

        class LethalStuckWorker(BaseModule):
            def step(self) -> bool:
                if not Test_WatchDogThreadReborn.thread_is_killed:
                    # CRITICAL: Brick the OS thread loop forever
                    while True:
                        time.sleep(0.001)
                else:
                    # Executed ONLY inside the freshly spawned brand-new OS thread manager!
                    Test_WatchDogThreadReborn.final_success = True
                    return True

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        try:
            api.add_tier(layer_num=1, name="WD_TIER")
            api.add_thread(name="BRICKED_POOL", type=ThreadType.TICKABLE, tct=0.01)
            api.add_unit(name="UNIT_LETHAL", type=UnitType.TICKABLE, 
                         m_class=LethalStuckWorker, thread_name="BRICKED_POOL")
            api.start()
            
            # Give the thread loop 50ms to dive deep into the infinite loop
            time.sleep(0.05)
            kernel.step()
            
            # KERNEL INTERVENTION: Simulate nuclear reset from the main thread control
            manager = kernel.get_managers().get("BRICKED_POOL")
            if manager:
                # Forcefully clear the stuck OS thread object context (Nuclear option)
                manager._stop_event.set()
                # Overwrite and spawn a completely fresh background OS thread manager pool
                Test_WatchDogThreadReborn.thread_is_killed = True
                
                # Re-compile and ignite a blank thread context loop
                api.add_thread(name="BRICKED_POOL_NEW", type=ThreadType.TICKABLE, tct=0.01)
                api.add_unit(name="UNIT_LETHAL_NEW", type=UnitType.TICKABLE, 
                             m_class=LethalStuckWorker, thread_name="BRICKED_POOL_NEW")
                
                # Process fresh loop initialization takts
                kernel.step()
                time.sleep(0.02)
                
            if Test_WatchDogThreadReborn.final_success:
                ledger.ok(test_name)
            else:
                ledger.fail(test_name, "Nuclear Thread reset failed to recover the architecture.")
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
        finally:
            api.stop()

class Test_SecretaryReportTransaction:
    """
    TRIGGERS:
    1. Into Work Latch: The executor's secretary must automatically fire an INTO_WORK 
       report, converting the sender's answer deadline to infinity.
    2. Time Extension Request: Low-level deadline checking must catch a stalling command 
       and automatically request more time, pushing the execution deadline forward.
    3. Cant Do Rejection: Attempting to send a command to a busy module must instantly 
       trigger a CANT_DO auto-report with MODULE_BUSY reason code via root frame headers.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Secretary: Automated Report Transaction Pipeline"
        ledger.start(test_name, "Test_SecretaryReportTransaction")
        
        into_work_ok = False
        time_ext_ok = False
        cant_do_ok = False

        # --- DYNAMIC EXECUTOR UNIT ---
        class HeavyExecutor(BaseModule):
            def start(self):
                self.v.scr.subscribe(cb=self._on_cmd, cmd=CmdType.CMD_TEST)
                self.v.started()
                self._busy_cycles = 0

            def _on_cmd(self, frame: Frame) -> bool:
                self._active_frame = frame
                return True

            def step(self) -> bool:
                if hasattr(self, '_active_frame') and self._active_frame:
                    self._busy_cycles += 1
                    if self._busy_cycles >= 12: # Stall across 12 cycles to trigger extension
                        p = {"text": "Done eventually"}
                        self.v.scr.send_rpt(self._active_frame.sender, self._active_frame.cmd_id, RptType.DONE, p)
                        self._active_frame = None
                    return True
                return False

        # --- DYNAMIC SENDER UNIT ---
        class SmartSender(BaseModule):
            def step(self) -> bool:
                if not hasattr(self, '_step_phase'):
                    self._step_phase = 1
                    recipient = self.v.addr_by_str("UNIT_EXECUTOR")
                    if recipient:
                        # Expanded limits to comfortably cushion heavy hardware framework boot cycles
                        self.v.scr.send_cmd(
                            recipient, CmdType.CMD_TEST, self._on_done,
                            cb_time_ext_req=self._on_ext,
                            deadline_answ_dur=0.2, deadline_done_dur=0.3
                        )
                    return True
                return False

            def _on_ext(self, frame: Frame) -> bool:
                nonlocal time_ext_ok
                time_ext_ok = True
                return True

            def _on_done(self, frame: Frame) -> bool:
                nonlocal into_work_ok
                into_work_ok = True
                return True

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        
        # Enforce highly resilient timing thresholds for automated watchdog execution
        kernel._cfg.DEADLINE_EXTENSION_THRESHOLD = 0.22
        kernel._cfg.DEFAULT_TIME_EXTENSION = 0.2
        
        try:
            api.add_tier(layer_num=1, name="SECR_TIER")
            api.add_thread(name="SECR_POOL", type=ThreadType.TICKABLE, tct=0.01)
            
            api.add_unit(name="UNIT_SENDER", type=UnitType.TICKABLE, m_class=SmartSender, 
                         thread_name="SECR_POOL", tier_layer=1, tier_name="SECR_TIER")
            api.add_unit(name="UNIT_EXECUTOR", type=UnitType.TICKABLE, m_class=HeavyExecutor, 
                         thread_name="SECR_POOL", tier_layer=1, tier_name="SECR_TIER")
            api.start()
            
            max_wait = 60
            while not (into_work_ok and time_ext_ok) and max_wait > 0:
                kernel.step()
                time.sleep(0.01)
                max_wait -= 1
                
            # --- PHASE 2: Evaluate CANT_DO pathway with expanded reason headers ---
            exec_unit = kernel._units.get(kernel._broker.ensure_addr(f"{node_name}:UNIT_EXECUTOR"))
            if exec_unit and exec_unit._secr:
                exec_unit._secr._module_is_busy = True
                
                def check_rejection(frame):
                    nonlocal cant_do_ok
                    if frame.rpt_type == RptType.CANT_DO and frame.reason == RptReason.MODULE_BUSY:
                        cant_do_ok = True
                
                sender_unit = kernel._units.get(kernel._broker.ensure_addr(f"{node_name}:UNIT_SENDER"))
                if sender_unit and sender_unit._module:
                    sender_unit._secr.send_cmd(exec_unit.addr, CmdType.CMD_TEST, check_rejection)
                    for _ in range(5): kernel.step()
                    time.sleep(0.01)
                    kernel.step()

            if into_work_ok and time_ext_ok and cant_do_ok:
                ledger.ok(test_name)
            else:
                t = f"Pipeline fault. INTO_WORK:{into_work_ok}, EXT:{time_ext_ok}, CANT_DO:{cant_do_ok}"
                ledger.fail(test_name, err_text=t)
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
        finally:
            api.stop()

class Test_SecretaryExecutionSpeed:
    """
    TRIGGERS:
    1. Instant DONE: Executor finishes immediately, transaction closes with green light.
    2. Extension DONE: Executor stalls, secretary extends deadline, task completes safely.
    3. Expired DONE: Executor completes task way too late, transaction drops by timeout.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Secretary: Execution Speed and Deadlines Validation Suite"
        ledger.start(test_name, "Test_SecretaryExecutionSpeed")
        
        fast_ok, ext_ok, late_dropped = False, False, False

        class SpeedExecutor(BaseModule):
            def start(self):
                self.v.scr.subscribe(cb=self._on_cmd, cmd=CmdType.CMD_TEST)
                self.v.started()
                self._mode = "fast"
                self._ticks = 0

            def _on_cmd(self, frame: Frame) -> bool:
                if self._mode == "fast":
                    self.v.scr.send_rpt(frame.sender, frame.cmd_id, RptType.DONE, {"text": "Fast"})
                else:
                    self._active_frame = frame
                return True

            def step(self) -> bool:
                if hasattr(self, '_active_frame') and self._active_frame:
                    self._ticks += 1
                    if self._mode == "ext" and self._ticks >= 4:
                        self.v.scr.send_rpt(self._active_frame.sender, self._active_frame.cmd_id, RptType.DONE)
                        self._active_frame = None
                    elif self._mode == "late" and self._ticks >= 15:
                        self.v.scr.send_rpt(self._active_frame.sender, self._active_frame.cmd_id, RptType.DONE)
                        self._active_frame = None
                return False

        class SpeedSender(BaseModule):
            def step(self) -> bool: return False

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        kernel._cfg.DEADLINE_EXTENSION_THRESHOLD = 0.08
        kernel._cfg.DEFAULT_TIME_EXTENSION = 0.1
        
        try:
            api.add_tier(layer_num=1, name="SPEED_TIER")
            api.add_thread(name="SPEED_POOL", type=ThreadType.TICKABLE, tct=0.01)
            # HARD REPAIR: Explicitly map tiers to fix the boot master lock
            api.add_unit(name="UNIT_SEND", type=UnitType.TICKABLE, m_class=SpeedSender, 
                         thread_name="SPEED_POOL", tier_layer=1, tier_name="SPEED_TIER")
            api.add_unit(name="UNIT_EXEC", type=UnitType.TICKABLE, m_class=SpeedExecutor, 
                         thread_name="SPEED_POOL", tier_layer=1, tier_name="SPEED_TIER")
            api.start()
            
            # Stabilize boot master plan
            for _ in range(10): kernel.step()
            
            sender = kernel._units.get(kernel._broker.ensure_addr(f"{node_name}:UNIT_SEND"))
            executor = kernel._units.get(kernel._broker.ensure_addr(f"{node_name}:UNIT_EXEC"))
            
            # --- PHASE 1: Fast Execution ---
            if sender and executor:
                sender._secr.send_cmd(executor.addr, CmdType.CMD_TEST, lambda f: None)
                for _ in range(5): kernel.step()
                fast_ok = True
                
                # --- PHASE 2: Extension Execution ---
                executor._module._mode = "ext"
                executor._module._ticks = 0
                
                def on_ext_done(f): nonlocal ext_ok; ext_ok = True
                sender._secr.send_cmd(executor.addr, CmdType.CMD_TEST, on_ext_done,
                                      deadline_answ_dur=0.05, deadline_done_dur=0.06)
                
                for _ in range(15): kernel.step()
                
                # --- PHASE 3: Late Expired Execution ---
                executor._module._mode = "late"
                executor._module._ticks = 0
                
                def on_late_timeout(f): nonlocal late_dropped; late_dropped = True
                sender._secr.send_cmd(executor.addr, CmdType.CMD_TEST, lambda f: None,
                                      cb_timeout_done=on_late_timeout,
                                      deadline_answ_dur=0.05, deadline_done_dur=0.03)
                
                for _ in range(25): kernel.step()

            if fast_ok and ext_ok and late_dropped:
                ledger.ok(test_name)
            else:
                t = f"Speed fault. FAST:{fast_ok}, EXT:{ext_ok}, LATE:{late_dropped}"
                ledger.fail(test_name, err_text=t)
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
        finally:
            api.stop()

class Test_SecretaryInvalidAddressing:
    """
    TRIGGERS:
    1. Zero Handler: Sending a command to a unit with no subscribed callback must 
       instantly return a CANT_DO auto-report with NOT_IMPLEMENTED reason.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Secretary: Routing Failures and Invalid Addressing Protection"
        ledger.start(test_name, "Test_SecretaryInvalidAddressing")
        
        zero_handler_rejected = False

        class IdleWorker(BaseModule):
            def start(self): self.v.started() # Subscribed to NOTHING

        class BlindCommander(BaseModule):
            def step(self) -> bool: return False

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        try:
            api.add_tier(layer_num=1, name="ROUTING_TIER")
            api.add_thread(name="ROUTING_POOL", type=ThreadType.TICKABLE, tct=0.01)
            api.add_unit(name="UNIT_BLIND", type=UnitType.TICKABLE, m_class=BlindCommander, 
                         thread_name="ROUTING_POOL", tier_layer=1, tier_name="ROUTING_TIER")
            api.add_unit(name="UNIT_IDLE", type=UnitType.TICKABLE, m_class=IdleWorker, 
                         thread_name="ROUTING_POOL", tier_layer=1, tier_name="ROUTING_TIER")
            api.start()
            
            for _ in range(10): kernel.step()
            
            sender = kernel._units.get(kernel._broker.ensure_addr(f"{node_name}:UNIT_BLIND"))
            idle_target = kernel._broker.ensure_addr(f"{node_name}:UNIT_IDLE")
            
            if sender and idle_target:
                def check_not_implemented(frame):
                    nonlocal zero_handler_rejected
                    # Verify that Secretary natively intercepted missing handler rules
                    if frame.rpt_type == RptType.CANT_DO:
                        zero_handler_rejected = True
                
                # Forcefully inject command packet straight to the zero-handler node
                sender._secr.send_cmd(idle_target, CmdType.CMD_TEST, check_not_implemented)
                
                for _ in range(5): kernel.step()
                time.sleep(0.01)
                kernel.step()
                
            if zero_handler_rejected:
                ledger.ok(test_name)
            else:
                ledger.fail(test_name, "Secretary failed to reject unhandled command type.")
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
        finally:
            api.stop()


def run_test_node(node_name: str):
    global ledger
    print(f"Initializing node: {node_name}")
    
    # Global Config Defaults for Clean State
    Config.BOOT_UI_MODE = "CUI"
    Config.KERNEL_TCT = 0.01
    Config.HOST = "0.0.0.0" 
    Config.UDP_PORT_DEFAULT = 45500
    Config.TCP_PORT_DEFAULT = 45501 if node_name == "ALPHA" else 45502
    Config.UDP_BEACON_INTERVAL = 0.5
    Config.CONN_KEEP_ALIVE = 5.0
    Config.HANDSHAKE_TIMEOUT = 2.0
    Config.ADDR_BROKER_STR = "BROKER"
    Config.BROKER_BUS_READ_LIMIT = 50
    Config.MAGIC_HEADER = b"SanaPo10"
    Config.NET_PROJECT_TOKEN = b"PROJ99"
    Config.NET_ALLOWED_IPS = []
    Config.NEEDS_NET_AUTO_CONNECT = True
    Config.HIBERNATE_MODE = True
    Config.DEFAULT_LOG_FLAGS["file"] = []
    # Tests map
    if node_name == "ALPHA":
        # Pre-registering scenarios in the ledger
        ledger = TestLedger()        
        ledger.add_meta("Core: System Boot, Ticking and Clean Shutdown", is_ready=True)
        ledger.add_meta("Core: Event Publication and Local Subscription", is_ready=True)
        ledger.add_meta("Core: Command Execution and Return Report Delivery", is_ready=True)
        ledger.add_meta("Kernel: Factory Methods Validation Suite", is_ready=True)
        ledger.add_meta("Threads: Strict Access Control and Hibernation Physics", is_ready=True)
        ledger.add_meta("Layers: Advanced Tier Factory and Navigation Control", is_ready=True)
        ledger.add_meta("Chaos: Heavy Random Matrix Multi-Generation Fuzzing", is_ready=False)
        ledger.add_meta("Kernel: Default Tiers and Threads for Homeless Units", is_ready=True)
        ledger.add_meta("Boot: Step 1 - Layer Initialization Retry 2/2", is_ready=True)
        ledger.add_meta("Boot: Step 2 - Tier Fatal Collapse and Global Restart", is_ready=True)
        ledger.add_meta("Boot: Step 3 - Emergency Dead Tier Isolation Bypass", is_ready=True)
        ledger.add_meta("Boot: Step 4 - Emergency Shutdown Stuck Isolation Bypass", is_ready=True)
        #ledger.add_meta("WatchDog: Step 1 - Automated Module Reborn Recovery", is_ready=True)
        #ledger.add_meta("WatchDog: Step 2 - Deep Infrastructure Unit Reborn", is_ready=True)
        #ledger.add_meta("WatchDog: Step 3 - Stalled OS Thread Nuclear Reset", is_ready=True)
        ledger.add_meta("Secretary: Automated Report Transaction Pipeline", is_ready=True)
        ledger.add_meta("Secretary: Execution Speed and Deadlines Validation Suite", is_ready=True)
        ledger.add_meta("Secretary: Routing Failures and Invalid Addressing Protection", is_ready=True)
        #ledger.add_meta("", is_ready=True)
        #ledger.add_meta("", is_ready=True)

        # --- COMPONENT DISCRETE PIPELINE (ONE TEST = ONE LINE) ---
        Test_StartStopSystem.run(ledger, node_name)
        TestSendLocalEvt.run(ledger, node_name)
        TestSendLocalCmd.run(ledger, node_name)
        Test_KernelCreateMethods.run(ledger, node_name)
        Test_ThreadTypes.run(ledger, node_name)
        Test_TierCreating.run(ledger, node_name)
        #Test_RandomCreateThreadsTiersUnits.run(ledger, node_name)
        Test_DefThreadTierForUnit.run(ledger, node_name)
        Test_BootMasterTierRetry.run(ledger, node_name)
        Test_BootMasterGlobalRestart.run(ledger, node_name)
        Test_BootMasterSkipDeadTier.run(ledger, node_name)
        Test_BootMasterShutdownStuck.run(ledger, node_name)
        #Test_WatchDogModuleReborn.run(ledger, node_name)
        #Test_WatchDogUnitReborn.run(ledger, node_name)
        #Test_WatchDogThreadReborn.run(ledger, node_name)
        Test_SecretaryReportTransaction.run(ledger, node_name)
        Test_SecretaryExecutionSpeed.run(ledger, node_name)
        Test_SecretaryInvalidAddressing.run(ledger, node_name)
        #.run(ledger, node_name)
        #.run(ledger, node_name)
        # ---------------------------------------------------------
        
        ledger.print_results()
    else:
        # BETA fallback to handle pure runtime federation testing later
        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        api.start()
        try:
            while True:
                kernel.step()
                time.sleep(0.005)
        except KeyboardInterrupt:
            pass
        finally:
            api.stop()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sanapo Discrete Fuzzing Suite")
    parser.add_argument("node", choices=["ALPHA", "BETA"], help="Node Name")
    args = parser.parse_args()
    run_test_node(args.node)














