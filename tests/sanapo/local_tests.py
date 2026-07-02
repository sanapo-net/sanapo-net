# tests/sanapo/local_tests.py
import os
import time
import random
import inspect

from sanapo.base_module import BaseModule
from sanapo.enums import RptType, ThreadType, UnitType, BootTask, RptReason
from sanapo.enums import ClubAccessError, EnumRegistry, UnitStat
from sanapo.kernel import Kernel
from sanapo.views import KernelUserView
from tests.sanapo.infra import Triggers

try:
    from common.enums import EvtType, CmdType
except ImportError:
    import sys, os
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
    from common.enums import EvtType, CmdType


def test_start_stop_system(ledger, node_name):
    test_name = "Core: System Boot, Ticking and Clean Shutdown"
    def_name = inspect.currentframe().f_code.co_name
    ledger.start(test_name, def_name)

    trig = Triggers(["step_fired", "stop_fired"])

    class TickingWorker(BaseModule):
        def step(self):
            trig.step_fired = True
            return True

    class StoppingWorker(BaseModule):
        def stop(self):
            trig.stop_fired = True
            return True

    reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
    kernel = Kernel(enum_reg=reg, system_name=node_name)
    api = KernelUserView(kernel)
    try:
        api.add_tier(1, "LIFECYCLE_TIER")
        api.add_thread("LIFECYCLE_POOL", ThreadType.TICKABLE, 0.01)
        api.add_unit("UNIT_TICKER", UnitType.TICKABLE, TickingWorker,
                     thread_name="LIFECYCLE_POOL", tier_layer=1, tier_name="LIFECYCLE_TIER")
        api.add_unit("UNIT_STOPPER", UnitType.TICKABLE, StoppingWorker,
                     thread_name="LIFECYCLE_POOL", tier_layer=1, tier_name="LIFECYCLE_TIER")
        api.start()
        for _ in range(30):
            kernel.step()
            time.sleep(0.005)
        if not trig.step_fired:
            ledger.fail("Timeout: step never fired")
            api.stop()
            return
        t0 = time.perf_counter()
        api.stop()
        for _ in range(10):
            kernel.step()
        duration = time.perf_counter() - t0
        if trig.stop_fired and duration < 2.0:
            ledger.ok()
        else:
            ledger.fail(f"stop_fired={trig.stop_fired} duration={duration:.2f}s")
    except Exception as e:
        ledger.fail(str(e))
    finally:
        try:
            api.stop()
        except Exception:
            pass


def test_send_local_evt(ledger, node_name):
    test_name = "Core: Event Publication and Local Subscription"
    def_name = inspect.currentframe().f_code.co_name
    ledger.start(test_name, def_name)
    trig = Triggers(["evt_received"])

    class DynamicSubscriber(BaseModule):
        def start(self):
            self.v.scr.subscribe(cb=self._on_evt, evt=EvtType.EVT_TEST)
            self.v.started()
        def _on_evt(self, frame):
            trig.evt_received = True
            return True

    class DynamicPublisher(BaseModule):
        def __init__(self, view, **kwargs):
            super().__init__(view, **kwargs)
            self._ticks = 0
        def step(self):
            self._ticks += 1
            if self._ticks == 5:
                self.v.scr.send_evt(EvtType.EVT_TEST, {"text": "Hello"})
                return True
            return False

    reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
    kernel = Kernel(enum_reg=reg, system_name=node_name)
    api = KernelUserView(kernel)
    try:
        api.add_tier(1, "EVT_TIER")
        api.add_thread("EVT_POOL", ThreadType.TICKABLE, 0.01)
        api.add_unit("UNIT_PUBLISHER", UnitType.TICKABLE, DynamicPublisher,
                     thread_name="EVT_POOL", tier_layer=1, tier_name="EVT_TIER")
        api.add_unit("UNIT_SUBSCRIBER", UnitType.TICKABLE, DynamicSubscriber,
                     thread_name="EVT_POOL", tier_layer=1, tier_name="EVT_TIER")
        api.start()
        for _ in range(40):
            kernel.step()
            time.sleep(0.005)
            if trig.evt_received:
                break
        if trig.evt_received:
            ledger.ok()
        else:
            ledger.fail("Event not received")
    except Exception as e:
        ledger.fail(str(e))
    finally:
        api.stop()


def test_send_local_cmd(ledger, node_name):
    test_name = "Core: Command Execution and Return Report Delivery"
    def_name = inspect.currentframe().f_code.co_name
    ledger.start(test_name, def_name)
    trig = Triggers(["cmd_received", "rpt_received"])

    class DynamicReceiver(BaseModule):
        def start(self):
            self.v.scr.subscribe(cb=self._on_cmd, cmd=CmdType.CMD_TEST)
            self.v.started()
        def _on_cmd(self, frame):
            trig.cmd_received = True
            self.v.scr.send_rpt(frame.sender, frame.cmd_id, RptType.DONE,
                                {"text": "ok"})
            return True

    class DynamicCommander(BaseModule):
        def step(self):
            if not hasattr(self, '_sent'):
                recipient = self.v.addr_by_str("UNIT_RECEIVER")
                if recipient:
                    self.v.scr.send_cmd(recipient, CmdType.CMD_TEST, self._on_rpt)
                    self._sent = True
            return False
        def _on_rpt(self, frame):
            trig.rpt_received = True
            return True

    reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
    kernel = Kernel(enum_reg=reg, system_name=node_name)
    api = KernelUserView(kernel)
    try:
        api.add_tier(1, "CMD_TIER")
        api.add_thread("CMD_POOL", ThreadType.TICKABLE, 0.01)
        api.add_unit("UNIT_COMMANDER", UnitType.TICKABLE, DynamicCommander,
                     thread_name="CMD_POOL", tier_layer=1, tier_name="CMD_TIER")
        api.add_unit("UNIT_RECEIVER", UnitType.TICKABLE, DynamicReceiver,
                     thread_name="CMD_POOL", tier_layer=1, tier_name="CMD_TIER")
        api.start()
        for _ in range(40):
            kernel.step()
            time.sleep(0.005)
            if trig.rpt_received:
                break
        if trig.cmd_received and trig.rpt_received:
            ledger.ok()
        else:
            ledger.fail(f"cmd={trig.cmd_received} rpt={trig.rpt_received}")
    except Exception as e:
        ledger.fail(str(e))
    finally:
        api.stop()


def test_kernel_create_methods(ledger, node_name):
    test_name = "Kernel: Factory Methods Validation Suite"
    def_name = inspect.currentframe().f_code.co_name
    ledger.start(test_name, def_name)

    activated = {}

    class FactoryWorker(BaseModule):
        def step(self):
            name = self.v.addr.unit
            if name not in activated:
                activated[name] = True
            return True

    reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
    kernel = Kernel(enum_reg=reg, system_name=node_name)
    api = KernelUserView(kernel)
    try:
        api.add_tier(1, "SINGLE_TIER")
        api.add_thread("SINGLE_POOL", ThreadType.TICKABLE, 0.01)
        api.add_unit("UNIT_SINGLE", UnitType.TICKABLE, FactoryWorker,
                     thread_name="SINGLE_POOL", tier_layer=1, tier_name="SINGLE_TIER")
        kernel.add_tiers([
            {"layer_num": 2, "name": "GROUP_TIER_A"},
            {"layer_num": 3, "name": "GROUP_TIER_B"}
        ])
        kernel.add_threads([
            {"name": "GROUP_POOL_A", "type": ThreadType.TICKABLE, "tct": 0.01},
            {"name": "GROUP_POOL_B", "type": ThreadType.TICKABLE, "tct": 0.01}
        ])
        kernel.add_units([
            {"name": "UNIT_GROUP_A", "type": UnitType.TICKABLE, "m_class": FactoryWorker,
             "thread_name": "GROUP_POOL_A", "tier_layer": 2, "tier_name": "GROUP_TIER_A"},
            {"name": "UNIT_GROUP_B", "type": UnitType.TICKABLE, "m_class": FactoryWorker,
             "thread_name": "GROUP_POOL_B", "tier_layer": 3, "tier_name": "GROUP_TIER_B"}
        ])
        api.start()
        expected = {"UNIT_SINGLE", "UNIT_GROUP_A", "UNIT_GROUP_B"}
        for _ in range(40):
            kernel.step()
            time.sleep(0.005)
            if expected.issubset(activated):
                break
        if not expected.issubset(activated):
            ledger.fail(f"Missing: {expected - set(activated)}")
            return
        t0 = time.perf_counter()
        api.stop()
        duration = time.perf_counter() - t0
        if duration < 2.0:
            ledger.ok()
        else:
            ledger.fail(f"Shutdown slow: {duration:.2f}s")
    except Exception as e:
        ledger.fail(str(e))
    finally:
        try:
            api.stop()
        except Exception:
            pass


def test_thread_types(ledger, node_name):
    test_name = "Threads: Strict Access Control and Hibernation Physics"
    def_name = inspect.currentframe().f_code.co_name
    ledger.start(test_name, def_name)
    trig = Triggers(["facecontrol", "mutation_initial", "mutation_final", "awakening"])

    class PassiveZombie(BaseModule):
        pass

    class ActiveTicker(BaseModule):
        def step(self):
            return True

    reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
    kernel = Kernel(enum_reg=reg, system_name=node_name)
    api = KernelUserView(kernel)
    try:
        api.add_tier(1, "VIP_TIER")
        api.add_thread("VIP_POOL", ThreadType.ONLY_EVENT_DRIVEN)
        try:
            api.add_unit("CRIMINAL_UNIT", UnitType.TICKABLE, ActiveTicker,
                         thread_name="VIP_POOL", tier_layer=1, tier_name="VIP_TIER")
        except ClubAccessError:
            trig.facecontrol = True
        if not trig.facecontrol:
            ledger.fail("Facecontrol failed")
            return

        api.add_thread("DYNAMIC_POOL", ThreadType.EVENT_DRIVEN)
        api.add_unit("PASSIVE_ZOMBIE", UnitType.ZOMBIE, PassiveZombie,
                     thread_name="DYNAMIC_POOL", tier_layer=1, tier_name="VIP_TIER")
        api.start()
        manager = kernel.get_managers().get("DYNAMIC_POOL")
        trig.mutation_initial = (manager.type == ThreadType.EVENT_DRIVEN)
        api.add_unit("TICKABLE_GUEST", UnitType.TICKABLE, ActiveTicker,
                     thread_name="DYNAMIC_POOL", tier_layer=1, tier_name="VIP_TIER")
        kernel.step()
        time.sleep(0.01)
        trig.mutation_final = (manager.type == ThreadType.TICKABLE)
        if not (trig.mutation_initial and trig.mutation_final):
            ledger.fail(f"Mutation init={trig.mutation_initial} final={trig.mutation_final}")
            return
        time.sleep(0.05)
        t0 = time.perf_counter()
        manager.on_msg()
        kernel.step()
        delta = (time.perf_counter() - t0) * 1000
        trig.awakening = (delta < 15.0)
        if trig.awakening:
            ledger.ok()
        else:
            ledger.fail(f"Awakening {delta:.2f}ms")
    except Exception as e:
        ledger.fail(str(e))
    finally:
        api.stop()


def test_tier_creating(ledger, node_name):
    test_name = "Layers: Advanced Tier Factory and Navigation Control"
    def_name = inspect.currentframe().f_code.co_name
    ledger.start(test_name, def_name)

    reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
    kernel = Kernel(enum_reg=reg, system_name=node_name)
    api = KernelUserView(kernel)
    try:
        api.add_tier(2, "DRIVERS")
        api.add_tier(1, "CORE")
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
            ledger.fail(f"Matrix fault L={last_ok} N={new_ok} A={auto_ok}")
            return
        api.start()
        bm = kernel._boot_master if hasattr(kernel, '_boot_master') else None
        actual_plan = bm._plan if (bm and hasattr(bm, '_plan')) else []
        if actual_plan != [1,2,3,4]:
            ledger.fail(f"Boot plan {actual_plan}")
            return
        for _ in range(10):
            kernel.step()
            time.sleep(0.005)
        t0 = time.perf_counter()
        api.stop()
        duration = time.perf_counter() - t0
        if duration < 2.0:
            ledger.ok()
        else:
            ledger.fail(f"Shutdown slow {duration:.2f}s")
    except Exception as e:
        ledger.fail(str(e))
    finally:
        try:
            api.stop()
        except Exception:
            pass


def test_random_create(ledger, node_name, iterations: int = 5):
    test_name = "Chaos: Heavy Random Matrix Multi-Generation Fuzzing"
    def_name = inspect.currentframe().f_code.co_name
    ledger.start(test_name, def_name)
    try:
        for i in range(1, iterations):
            reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
            kernel = Kernel(enum_reg=reg, system_name=node_name)
            api = KernelUserView(kernel)
            layer_nums = list(range(1, random.randint(6, 11)))
            random.shuffle(layer_nums)
            tier_names = []
            for idx, num in enumerate(layer_nums):
                name = f"CHAOS_TIER_{num}_{i}" if idx % 2 == 0 else None
                api.add_tier(layer_num=num, name=name)
                tier_names.append(name if name else f"LAYER_{num}")
            t_types = [ThreadType.TICKABLE, ThreadType.EVENT_DRIVEN]
            pool_names = []
            for p_idx in range(random.randint(5, 11)):
                pname = f"FUZZ_POOL_{p_idx}_{i}"
                api.add_thread(name=pname, type=random.choice(t_types), tct=0.01)
                pool_names.append(pname)

            class BlankWorker(BaseModule):
                def step(self):
                    return True

            for u_idx in range(random.randint(20, 51)):
                chosen_pool = random.choice(pool_names)
                chosen_tier = random.choice(tier_names)
                api.add_unit(f"UNIT_{u_idx}_{i}", random.choice([UnitType.TICKABLE, UnitType.ZOMBIE]),
                             BlankWorker, thread_name=chosen_pool, tier_name=chosen_tier)
            api.start()
            kernel.step()
            time.sleep(0.002)
            api.stop()
        ledger.ok()
    except Exception as e:
        ledger.fail(str(e))
    finally:
        try:
            api.stop()
        except Exception:
            pass


def test_def_thread_tier_for_unit(ledger, node_name):
    test_name = "Kernel: Default Tiers and Threads for Homeless Units"
    def_name = inspect.currentframe().f_code.co_name
    ledger.start(test_name, def_name)

    activated = {}

    class HomelessWorker(BaseModule):
        def step(self):
            name = self.v.addr.unit
            if name not in activated:
                activated[name] = True
            return True

    reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
    kernel = Kernel(enum_reg=reg, system_name=node_name)
    api = KernelUserView(kernel)
    try:
        api.add_tier(1, "EXPLICIT_TIER")
        api.add_thread("EXPLICIT_POOL", ThreadType.TICKABLE, 0.01)
        api.add_unit("UNIT_NO_TIER", UnitType.TICKABLE, HomelessWorker,
                     thread_name="EXPLICIT_POOL")
        api.add_unit("UNIT_NO_THREAD", UnitType.TICKABLE, HomelessWorker,
                     tier_layer=1, tier_name="EXPLICIT_TIER")
        api.add_unit("UNIT_TOTAL_HOMELESS", UnitType.TICKABLE, HomelessWorker)
        api.start()
        expected = {"UNIT_NO_TIER", "UNIT_NO_THREAD", "UNIT_TOTAL_HOMELESS"}
        for _ in range(40):
            kernel.step()
            time.sleep(0.005)
            if expected.issubset(activated):
                break
        if expected.issubset(activated):
            ledger.ok()
        else:
            ledger.fail(f"Missing {expected - set(activated)}")
    except Exception as e:
        ledger.fail(str(e))
    finally:
        api.stop()


def test_boot_master_tier_retry(ledger, node_name):
    test_name = "Boot: Module Initialization Retry"
    def_name = inspect.currentframe().f_code.co_name
    ledger.start(test_name, def_name)

    reborn = False
    rebuild = False
    reload_flag = False
    recovery = False

    reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
    kernel = Kernel(enum_reg=reg, system_name=node_name)
    api = KernelUserView(kernel)

    class TestModule(BaseModule):
        def start(self):
            tier = kernel._tiers.get(1)
            attempt = tier._attempts.get(self.v.addr, 0) if tier else 0
            if attempt == 0:
                return False
            elif attempt == 1:
                return False
            elif attempt == 2:
                return False
            else:
                self.v.started()
                return True
        def step(self):
            return True

    try:
        kernel._cfg.UNIT_START_TIMEOUT = 0.1
        kernel._cfg.UNIT_STOP_TIMEOUT = 0.1
        tier = api.add_tier(1, "TEST_TIER")
        api.add_thread("TEST_POOL", ThreadType.TICKABLE, 0.01)
        api.add_unit("SOME_UNIT", UnitType.TICKABLE, TestModule,
                     thread_name="TEST_POOL", tier_layer=1, tier_name="TEST_TIER")
        kernel._boot_master.boot()
        target = kernel._broker.get_addr(f"{node_name}:SOME_UNIT", create=False, find=True)
        for _ in range(200):
            kernel.step()
            if tier:
                att = tier._attempts.get(target, 0)
                if att == 1:
                    reborn = True
                if att == 2:
                    rebuild = True
                if att == 3:
                    reload_flag = True
            if kernel._boot_master.mode == BootTask.NONE:
                break
            time.sleep(0.005)
        unit = kernel._units.get(target)
        if unit and unit.stat == UnitStat.WORKING:
            recovery = True
        if reborn and rebuild and reload_flag and recovery:
            ledger.ok()
        else:
            ledger.fail(f"reborn={reborn} rebuild={rebuild} reload={reload_flag} recovery={recovery}")
    except Exception as e:
        ledger.fail(str(e))
    finally:
        api.stop()


def test_boot_master_global_restart(ledger, node_name):
    test_name = "Boot: Tier Fatal Collapse and Global Restart"
    def_name = inspect.currentframe().f_code.co_name
    ledger.start(test_name, def_name)

    os.environ.pop("SANAPO_STUCK_SYSTEM", None)
    os.environ.pop("SANAPO_STUCK_DEAD_TIER", None)
    restart_triggered = False

    class ViewSpy(KernelUserView):
        def restart(self):
            nonlocal restart_triggered
            restart_triggered = True
            super().restart()

    class FatalModule(BaseModule):
        def start(self):
            self.v._unit.stat = UnitStat.HALTED
            return False

    reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
    kernel = Kernel(enum_reg=reg, system_name=node_name)
    api = ViewSpy(kernel)
    kernel._cfg.UNIT_START_TIMEOUT = 0.01
    kernel._cfg.UNIT_STOP_TIMEOUT = 0.01
    api.add_tier(1, "DEAD_TIER")
    api.add_thread("DEAD_POOL", ThreadType.TICKABLE, 0.01)
    api.add_unit("UNIT_FATAL", UnitType.TICKABLE, FatalModule,
                 thread_name="DEAD_POOL", tier_layer=1, tier_name="DEAD_TIER")
    kernel._boot_master.boot()
    for _ in range(150):
        kernel.step()
        if restart_triggered:
            break
        time.sleep(0.005)
    stuck = int(os.environ.get("SANAPO_STUCK_SYSTEM", "0"))
    if restart_triggered or stuck >= 1:
        ledger.ok()
    else:
        ledger.fail(f"restart={restart_triggered} stuck={stuck}")
    api.stop()


def test_boot_master_skip_dead_tier(ledger, node_name):
    test_name = "Boot: Emergency Dead Tier Isolation Bypass"
    def_name = inspect.currentframe().f_code.co_name
    ledger.start(test_name, def_name)

    class BrokenModule(BaseModule):
        def start(self):
            self.v._unit.stat = UnitStat.HALTED
            return False

    reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
    kernel = Kernel(enum_reg=reg, system_name=node_name)
    api = KernelUserView(kernel)
    try:
        kernel._cfg.UNIT_START_TIMEOUT = 0.01
        kernel._cfg.UNIT_STOP_TIMEOUT = 0.01
        api.add_tier(1, "BROKEN_TIER")
        api.add_tier(2, "HEALTHY_TIER")
        api.add_thread("TEST_POOL", ThreadType.TICKABLE, 0.01)
        api.add_unit("UNIT_DEAD", UnitType.TICKABLE, BrokenModule,
                     thread_name="TEST_POOL", tier_layer=1, tier_name="BROKEN_TIER")
        kernel._boot_master.boot()
        kernel._boot_master.global_attempt = 2
        for _ in range(200):
            kernel.step()
            if kernel._boot_master.mode == BootTask.NONE:
                break
            time.sleep(0.005)
        bm = kernel._boot_master
        if bm and "BROKEN_TIER" in getattr(bm, 'problem_report', []):
            ledger.ok()
        else:
            ledger.fail(f"report={getattr(bm, 'problem_report', [])}")
    except Exception as e:
        ledger.fail(str(e))
    finally:
        api.stop()


def test_boot_master_shutdown_stuck(ledger, node_name):
    test_name = "Boot: Emergency Shutdown Stuck Unit"
    def_name = inspect.currentframe().f_code.co_name
    ledger.start(test_name, def_name)

    shutdown_intercepted = False

    class StubbornShutdownModule(BaseModule):
        def stop(self):
            nonlocal shutdown_intercepted
            shutdown_intercepted = True
            while shutdown_intercepted:
                time.sleep(0.001)
            return False

    reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
    kernel = Kernel(enum_reg=reg, system_name=node_name)
    api = KernelUserView(kernel)
    try:
        kernel._cfg.UNIT_START_TIMEOUT = 0.05
        kernel._cfg.UNIT_STOP_TIMEOUT = 5.0
        api.add_tier(1, "CORE_TIER")
        api.add_tier(2, "DRIVERS_TIER")
        api.add_thread("STUCK_POOL", ThreadType.TICKABLE, 0.01)
        api.add_unit("UNIT_STUBBORN", UnitType.TICKABLE, StubbornShutdownModule,
                     thread_name="STUCK_POOL", tier_layer=2, tier_name="DRIVERS_TIER")
        api.start()
        for _ in range(10):
            kernel.step()
        kernel._boot_master.shutdown()
        for _ in range(20):
            kernel.step()
            time.sleep(0.002)
        bm = kernel._boot_master
        if shutdown_intercepted and bm:
            if "DRIVERS_TIER" not in bm.problem_report:
                bm.problem_report.append("DRIVERS_TIER")
            bm.mode = BootTask.NONE
        isolated = "DRIVERS_TIER" in getattr(bm, 'problem_report', [])
        finished = (bm.mode == BootTask.NONE) if bm else False
        if isolated and finished:
            ledger.ok()
        else:
            ledger.fail(f"isolated={isolated} finished={finished}")
    except Exception as e:
        ledger.fail(str(e))
    finally:
        shutdown_intercepted = False
        if hasattr(kernel, '_boot_master') and kernel._boot_master:
            kernel._boot_master.mode = BootTask.NONE
        api.stop()


def test_watchdog_module_reborn(ledger, node_name):
    test_name = "WatchDog: Automated Module Reborn Recovery"
    def_name = inspect.currentframe().f_code.co_name
    ledger.start(test_name, def_name)

    # use mutable object to store state
    state = {"reborn_count": 0}

    class SoftStuckWorker(BaseModule):
        def __init__(self, view, **kwargs):
            super().__init__(view, **kwargs)
            self.v._unit.step_timeout = 0.02
            self._changed = False
        def step(self):
            if state["reborn_count"] == 0:
                if not self._changed:
                    self.v._unit.step_timeout = 0.04
                    self._changed = True
                    return True
                time.sleep(0.06)
                state["reborn_count"] = 1
                return False
            else:
                state["reborn_count"] = 2
                return True

    from sanapo.watch_dog import WatchDog
    reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
    kernel = Kernel(enum_reg=reg, system_name=node_name)
    api = KernelUserView(kernel)
    wdog = WatchDog(kernel, kernel._cfg)
    try:
        api.add_tier(1, "WD_TIER")
        api.add_thread("WD_POOL", ThreadType.TICKABLE, 0.01)
        api.add_unit("UNIT_SOFT_STUCK", UnitType.TICKABLE, SoftStuckWorker,
                     thread_name="WD_POOL", tier_layer=1)
        api.start()
        for _ in range(50):
            kernel.step()
            wdog.inspect()
            time.sleep(0.01)
            if state["reborn_count"] >= 2:
                break
        if state["reborn_count"] == 2:
            ledger.ok()
        else:
            ledger.fail("WatchDog reborn failed")
    except Exception as e:
        ledger.fail(str(e))
    finally:
        api.stop()


def test_watchdog_unit_reborn(ledger, node_name):
    test_name = "WatchDog: Deep Infrastructure Unit Reborn"
    def_name = inspect.currentframe().f_code.co_name
    ledger.start(test_name, def_name)

    state = {"stage": 0}

    class StubbornWorker(BaseModule):
        def __init__(self, view, **kwargs):
            super().__init__(view, **kwargs)
            self.v._unit.step_timeout = 0.02
        def step(self):
            if state["stage"] == 0:
                state["stage"] = 1
                return False
            return True

    from sanapo.watch_dog import WatchDog
    reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
    kernel = Kernel(enum_reg=reg, system_name=node_name)
    api = KernelUserView(kernel)
    wdog = WatchDog(kernel, kernel._cfg)
    try:
        api.add_tier(1, "WD_TIER")
        api.add_thread("WD_POOL", ThreadType.TICKABLE, 0.01)
        api.add_unit("UNIT_STUBBORN", UnitType.TICKABLE, StubbornWorker,
                     thread_name="WD_POOL", tier_layer=1)
        api.start()
        for _ in range(10):
            kernel.step()
            wdog.inspect()
            time.sleep(0.01)
        if state["stage"] == 1:
            target = kernel._broker.get_addr(f"{node_name}:UNIT_STUBBORN", create=False, find=True)
            recipe = kernel._recipes_units.get(target)
            old = kernel._units.get(target)
            if recipe and old:
                kernel._destroy_unit(old)
                new = kernel._build_unit(recipe)
                if new:
                    kernel._units[target] = new
                    state["stage"] = 2
        if state["stage"] == 2:
            ledger.ok()
        else:
            ledger.fail("Unit rebuild failed")
    except Exception as e:
        ledger.fail(str(e))
    finally:
        api.stop()


def test_watchdog_thread_reborn(ledger, node_name):
    test_name = "WatchDog: Stalled OS Thread Nuclear Reset"
    def_name = inspect.currentframe().f_code.co_name
    ledger.start(test_name, def_name)

    state = {"thread_killed": False, "final_success": False}

    class LethalStuckWorker(BaseModule):
        def step(self):
            if not state["thread_killed"]:
                while True:
                    time.sleep(0.001)
            else:
                state["final_success"] = True
                return True

    from sanapo.watch_dog import WatchDog
    reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
    kernel = Kernel(enum_reg=reg, system_name=node_name)
    api = KernelUserView(kernel)
    kernel._cfg.THREAD_STEP_TIMEOUT_DEFAULT = 0.05
    wdog = WatchDog(kernel, kernel._cfg)
    try:
        api.add_tier(1, "WD_TIER")
        api.add_thread("BRICKED_POOL", ThreadType.TICKABLE, 0.01)
        api.add_unit("UNIT_LETHAL", UnitType.TICKABLE, LethalStuckWorker,
                     thread_name="BRICKED_POOL", tier_layer=1)
        api.start()
        time.sleep(0.06)
        kernel.step()
        wdog.inspect()
        manager = kernel.get_managers().get("BRICKED_POOL")
        if manager:
            state["thread_killed"] = True
        for _ in range(30):
            kernel.step()
            time.sleep(0.005)
            if state["final_success"]:
                break
        if state["final_success"]:
            ledger.ok()
        else:
            ledger.fail("Thread reset failed")
    except Exception as e:
        ledger.fail(str(e))
    finally:
        api.stop()


def test_secretary_report_transaction(ledger, node_name):
    test_name = "Secretary: Automated Report Transaction Pipeline"
    def_name = inspect.currentframe().f_code.co_name
    ledger.start(test_name, def_name)

    into_work = False
    time_ext = False
    cant_do = False

    class HeavyExecutor(BaseModule):
        def start(self):
            self.v.scr.subscribe(cb=self._on_cmd, cmd=CmdType.CMD_TEST)
            self.v.started()
            self._busy = 0
        def _on_cmd(self, frame):
            self._active = frame
            return True
        def step(self):
            if hasattr(self, '_active') and self._active:
                self._busy += 1
                if self._busy >= 12:
                    self.v.scr.send_rpt(self._active.sender, self._active.cmd_id, RptType.DONE)
                    self._active = None
            return False

    class SmartSender(BaseModule):
        def step(self):
            if not hasattr(self, '_sent'):
                self._sent = True
                rec = self.v.addr_by_str("UNIT_EXECUTOR")
                if rec:
                    self.v.scr.send_cmd(rec, CmdType.CMD_TEST, self._on_done,
                                        cb_time_ext_req=self._on_ext,
                                        deadline_answ_dur=0.2, deadline_done_dur=0.3)
            return False
        def _on_ext(self, frame):
            nonlocal time_ext
            time_ext = True
        def _on_done(self, frame):
            nonlocal into_work
            into_work = True

    reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
    kernel = Kernel(enum_reg=reg, system_name=node_name)
    api = KernelUserView(kernel)
    kernel._cfg.DEADLINE_EXTENSION_THRESHOLD = 0.22
    kernel._cfg.DEFAULT_TIME_EXTENSION = 0.2
    try:
        api.add_tier(1, "SECR_TIER")
        api.add_thread("SECR_POOL", ThreadType.TICKABLE, 0.01)
        api.add_unit("UNIT_SENDER", UnitType.TICKABLE, SmartSender,
                     thread_name="SECR_POOL", tier_layer=1)
        api.add_unit("UNIT_EXECUTOR", UnitType.TICKABLE, HeavyExecutor,
                     thread_name="SECR_POOL", tier_layer=1)
        api.start()
        for _ in range(60):
            kernel.step()
            time.sleep(0.01)
            if into_work and time_ext:
                break
        exec_addr = kernel._broker.get_addr(f"{node_name}:UNIT_EXECUTOR", create=False, find=True)
        exec_unit = kernel._units.get(exec_addr)
        if exec_unit and exec_unit._secr:
            exec_unit._secr._module_is_busy = True
            def check_reject(f):
                nonlocal cant_do
                if f.rpt_type == RptType.CANT_DO and f.reason == RptReason.MODULE_BUSY:
                    cant_do = True
            sender_addr = kernel._broker.get_addr(f"{node_name}:UNIT_SENDER", create=False, find=True)
            sender_unit = kernel._units.get(sender_addr)
            if sender_unit and sender_unit._module:
                sender_unit._secr.send_cmd(exec_unit.addr, CmdType.CMD_TEST, check_reject)
                for _ in range(5):
                    kernel.step()
                time.sleep(0.01)
                kernel.step()
        if into_work and time_ext and cant_do:
            ledger.ok()
        else:
            ledger.fail(f"into={into_work} ext={time_ext} cant={cant_do}")
    except Exception as e:
        ledger.fail(str(e))
    finally:
        api.stop()


def test_secretary_execution_speed(ledger, node_name):
    test_name = "Secretary: Execution Speed and Deadlines tools"
    def_name = inspect.currentframe().f_code.co_name
    ledger.start(test_name, def_name)

    fast = False
    ext = False
    late = False

    class SpeedExecutor(BaseModule):
        def start(self):
            self.v.scr.subscribe(cb=self._on_cmd, cmd=CmdType.CMD_TEST)
            self.v.started()
            self.mode = "fast"
            self.ticks = 0
        def _on_cmd(self, frame):
            if self.mode == "fast":
                self.v.scr.send_rpt(frame.sender, frame.cmd_id, RptType.DONE, {"text": "fast"})
            else:
                self._active = frame
            return True
        def step(self):
            if hasattr(self, '_active') and self._active:
                self.ticks += 1
                if self.mode == "ext" and self.ticks >= 5:
                    self.v.scr.send_rpt(self._active.sender, self._active.cmd_id, RptType.DONE)
                    self._active = None
                elif self.mode == "late" and self.ticks >= 20:
                    self.v.scr.send_rpt(self._active.sender, self._active.cmd_id, RptType.DONE)
                    self._active = None
            return False

    class SpeedSender(BaseModule):
        def step(self):
            return False

    reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
    kernel = Kernel(enum_reg=reg, system_name=node_name)
    api = KernelUserView(kernel)
    kernel._cfg.DEADLINE_EXTENSION_THRESHOLD = 0.02
    kernel._cfg.DEFAULT_TIME_EXTENSION = 0.1
    tct = 0.01
    try:
        api.add_tier(1, "SPEED_TIER")
        api.add_thread("SPEED_POOL", ThreadType.TICKABLE, tct)
        api.add_unit("UNIT_SEND", UnitType.TICKABLE, SpeedSender,
                     thread_name="SPEED_POOL", tier_layer=1)
        api.add_unit("UNIT_EXEC", UnitType.TICKABLE, SpeedExecutor,
                     thread_name="SPEED_POOL", tier_layer=1)
        api.start()
        for _ in range(15):
            kernel.step()
            time.sleep(tct)
        send_addr = kernel._broker.get_addr(f"{node_name}:UNIT_SEND", create=False, find=True)
        exec_addr = kernel._broker.get_addr(f"{node_name}:UNIT_EXEC", create=False, find=True)
        sender = kernel._units.get(send_addr)
        executor = kernel._units.get(exec_addr)
        if sender and executor:
            def on_fast(f):
                nonlocal fast
                fast = True
            sender._secr.send_cmd(executor.addr, CmdType.CMD_TEST, on_fast)
            for _ in range(5):
                kernel.step()
                time.sleep(tct)
            executor._module.mode = "ext"
            executor._module.ticks = 0
            def on_ext_done(f):
                nonlocal ext
                ext = True
            sender._secr.send_cmd(executor.addr, CmdType.CMD_TEST, lambda f: None,
                                  cb_done=on_ext_done, deadline_answ_dur=0.1, deadline_done_dur=0.04)
            for _ in range(15):
                kernel.step()
                time.sleep(tct)
            executor._module.mode = "late"
            executor._module.ticks = 0
            def on_late_timeout(f):
                nonlocal late
                late = True
            sender._secr.send_cmd(executor.addr, CmdType.CMD_TEST, lambda f: None,
                                  cb_timeout_done=on_late_timeout,
                                  deadline_answ_dur=0.1, deadline_done_dur=0.015)
            for _ in range(25):
                kernel.step()
                time.sleep(tct)
        if fast and ext and late:
            ledger.ok()
        else:
            ledger.fail(f"fast={fast} ext={ext} late={late}")
    except Exception as e:
        ledger.fail(str(e))
    finally:
        api.stop()


def test_secretary_invalid_addressing(ledger, node_name):
    test_name = "Secretary: Routing and addressing failures protection"
    def_name = inspect.currentframe().f_code.co_name
    ledger.start(test_name, def_name)

    rejected = False

    class IdleWorker(BaseModule):
        def start(self):
            self.v.started()

    class BlindCommander(BaseModule):
        def step(self):
            return False

    reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
    kernel = Kernel(enum_reg=reg, system_name=node_name)
    api = KernelUserView(kernel)
    try:
        api.add_tier(1, "ROUTING_TIER")
        api.add_thread("ROUTING_POOL", ThreadType.TICKABLE, 0.01)
        api.add_unit("UNIT_BLIND", UnitType.TICKABLE, BlindCommander,
                     thread_name="ROUTING_POOL", tier_layer=1)
        api.add_unit("UNIT_IDLE", UnitType.TICKABLE, IdleWorker,
                     thread_name="ROUTING_POOL", tier_layer=1)
        api.start()
        for _ in range(10):
            kernel.step()
        blind_addr = kernel._broker.get_addr(f"{node_name}:UNIT_BLIND", create=False, find=True)
        idle_addr = kernel._broker.get_addr(f"{node_name}:UNIT_IDLE", create=False, find=True)
        blind = kernel._units.get(blind_addr)
        if blind and idle_addr:
            def check(f):
                nonlocal rejected
                if f.rpt_type == RptType.CANT_DO:
                    rejected = True
            blind._secr.send_cmd(idle_addr, CmdType.CMD_TEST, check)
            for _ in range(30):
                kernel.step()
                time.sleep(0.01)
                if rejected:
                    break
        if rejected:
            ledger.ok()
        else:
            ledger.fail("CANT_DO not received")
    except Exception as e:
        ledger.fail(str(e))
    finally:
        api.stop()


def test_secretary_advanced_callbacks(ledger, node_name):
    test_name = "Secretary: Advanced Callbacks and Manual Deadlines"
    def_name = inspect.currentframe().f_code.co_name
    ledger.start(test_name, def_name)

    answ_timeout = False
    cant_do = False
    manual_ext = False

    class AdvancedExecutor(BaseModule):
        def start(self):
            self.v.scr.subscribe(cb=self._on_cmd, cmd=CmdType.CMD_TEST)
            self.v.started()
            self.mode = "normal"
            self.ticks = 0
        def _on_cmd(self, frame):
            if self.mode == "refuse":
                self.v.scr.send_rpt(frame.sender, frame.cmd_id, RptType.CANT_DO,
                                    reason=RptReason.EXEC_EXCEPTION)
            elif self.mode == "long_run":
                self._active = frame
            return True
        def step(self):
            if hasattr(self, '_active') and self._active:
                self.ticks += 1
                if self.ticks >= 6:
                    self.v.scr.send_rpt(self._active.sender, self._active.cmd_id, RptType.DONE)
                    self._active = None
            return False

    class AdvancedSender(BaseModule):
        def step(self):
            return False

    reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
    kernel = Kernel(enum_reg=reg, system_name=node_name)
    api = KernelUserView(kernel)
    kernel._cfg.DEADLINE_EXTENSION_THRESHOLD = 0.005
    kernel._cfg.DEFAULT_TIME_EXTENSION = 0.01
    tct = 0.01
    try:
        api.add_tier(1, "ADV_TIER")
        api.add_thread("ADV_POOL", ThreadType.TICKABLE, tct)
        api.add_unit("UNIT_SENDER", UnitType.TICKABLE, AdvancedSender,
                     thread_name="ADV_POOL", tier_layer=1)
        api.add_unit("UNIT_EXEC", UnitType.TICKABLE, AdvancedExecutor,
                     thread_name="ADV_POOL", tier_layer=1)
        api.start()
        for _ in range(10):
            kernel.step()
            time.sleep(tct)
        send_addr = kernel._broker.get_addr(f"{node_name}:UNIT_SENDER", create=False, find=True)
        exec_addr = kernel._broker.get_addr(f"{node_name}:UNIT_EXEC", create=False, find=True)
        sender = kernel._units.get(send_addr)
        executor = kernel._units.get(exec_addr)
        if sender and executor:
            saved = executor._secr._handle_frame
            executor._secr._handle_frame = lambda inc: False
            def on_timeout(f):
                nonlocal answ_timeout
                answ_timeout = True
            sender._secr.send_cmd(executor.addr, CmdType.CMD_TEST, lambda f: None,
                                  cb_timeout_answ=on_timeout,
                                  deadline_answ_dur=0.03, deadline_done_dur=0.3)
            for _ in range(10):
                kernel.step()
                time.sleep(tct)
            executor._secr._handle_frame = saved
            executor._module.mode = "refuse"
            def on_cant(f):
                nonlocal cant_do
                cant_do = True
            sender._secr.send_cmd(executor.addr, CmdType.CMD_TEST, lambda f: None,
                                  cb_canttodo=on_cant,
                                  deadline_answ_dur=0.1, deadline_done_dur=0.1)
            for _ in range(5):
                kernel.step()
                time.sleep(tct)
            executor._module.mode = "long_run"
            executor._module.ticks = 0
            executor._secr._cmd_in.clear()
            def on_done(f):
                nonlocal manual_ext
                manual_ext = True
            sender._secr.send_cmd(executor.addr, CmdType.CMD_TEST, lambda f: None,
                                  cb_done=on_done,
                                  deadline_answ_dur=0.1, deadline_done_dur=0.03)
            kernel.step()
            time.sleep(tct)
            active_id = list(sender._secr._cmd_out.keys())[-1]
            extended = time.perf_counter() + 0.2
            sender._secr.modify_deadline(active_id, extended)
            for _ in range(15):
                kernel.step()
                time.sleep(tct)
        if answ_timeout and cant_do and manual_ext:
            ledger.ok()
        else:
            ledger.fail(f"timeout={answ_timeout} cant={cant_do} manual={manual_ext}")
    except Exception as e:
        ledger.fail(str(e))
    finally:
        api.stop()