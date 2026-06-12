import sys
import os
import time
import argparse

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sanapo.config import Config
from sanapo.enums import RptType, ThreadType, UnitType, EnumRegistry
from sanapo.kernel import Kernel
from sanapo.views import KernelUserView
from sanapo.base_unit import UnitModuleView
from sanapo.base_module import BaseModule
from sanapo.protocol import Frame
from sanapo.addr import Addr

try:
    from core.drafts.project_enums import EvtType, CmdType
except ImportError:
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
    from core.drafts.project_enums import EvtType, CmdType

LOCAL_TEST_PASSED = False
NET_TEST_PASSED = False

class NetSmokeWorker(BaseModule):
    def __init__(self, view, **kwargs):
        super().__init__(view, **kwargs)
        self.v: UnitModuleView = view
        self.local_sent = False

    def start(self):
        if "RECEIVER" in self.v.addr.unit:
            self.v.scr.subscribe(cb=self._on_cmd, cmd=CmdType.CMD_TEST)
        self.v.started()

    def step(self) -> bool:
        global LOCAL_TEST_PASSED
        # 1. Local command - Fires strictly ONCE via standard step loop
        if "COMMANDER" in self.v.addr.unit and not self.local_sent:
            recipient = self.v.addr_by_str("UNIT_RECEIVER")
            if recipient:
                t = f"\033[94m[{self.v.addr.system}:{self.v.addr.unit}]: sent LOCAL cmd\033[0m"
                print(t)
                p = {"text": f"Hello from local {self.v.addr.unit}"}
                self.v.scr.send_cmd(recipient, CmdType.CMD_TEST, self._on_local_rpt, payload=p)
                self.local_sent = True
                return True
        return False

    def on_net_connected(self, system_name: str) -> None:
        """Event-Driven Entry: Fired automatically when connection is ready."""
        if "COMMANDER" in self.v.addr.unit:
            recipient = Addr(system_name, "UNIT_RECEIVER")
            t = f"\033[93m[{self.v.addr.system}:{self.v.addr.unit}]: sent NETWORK cmd\033[0m"
            print(t)
            p = {"text": f"Hello across network from {self.v.addr.system}!"}
            self.v.scr.send_cmd(recipient, CmdType.CMD_TEST, self._on_net_rpt, payload=p)

    def _on_cmd(self, frame: Frame) -> bool:
        sys_from = f"{frame.sender.system}:{frame.sender.unit}"
        t = f"\033[95m[{self.v.addr.system}:UNIT_RECEIVER]: incoming cmd from [{sys_from}]\033[0m"
        print(t)
        p = {"text": f"Success response from {self.v.addr.system}"}
        self.v.scr.send_rpt(frame.sender, frame.cmd_id, RptType.DONE, p)
        return True

    def _on_local_rpt(self, frame: Frame) -> bool:
        global LOCAL_TEST_PASSED
        sys_from = f"{frame.sender.system}:{frame.sender.unit}"
        str_addr = f"[{self.v.addr.system}:{self.v.addr.unit}]"
        t = f"\033[92m✓ {str_addr}: got LOCAL rpt from [{sys_from}]\033[0m"
        print(t)
        LOCAL_TEST_PASSED = True
        return True

    def _on_net_rpt(self, frame: Frame) -> bool:
        global NET_TEST_PASSED
        sys_from = f"{frame.sender.system}:{frame.sender.unit}"
        str_addr = f"[{self.v.addr.system}:{self.v.addr.unit}]"
        t = f"\033[92m✓ {str_addr}: got NET rpt from [{sys_from}]\033[0m"
        print(t)
        NET_TEST_PASSED = True
        return True

    def stop(self):
        pass


def run_test_node(node_name: str):
    print(f"Initializing node: {node_name}")
    
    Config.SYSTEM_NAME = node_name
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
    Config.NET_PROJECT_TOKEN = b"PROJ00"
    Config.NET_ALLOWED_IPS = []
    Config.NEEDS_NET_AUTO_CONNECT = True
    Config.HIBERNATE_MODE = True

    # Build optimized framework registry in one single line
    reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
    
    kernel = Kernel(enum_reg=reg, system_name=node_name) 
    api = KernelUserView(kernel)
    
    api.add_tier(layer_num=1, name="SMOKE_TIER")
    api.add_thread(name="SMOKE_POOL", type=ThreadType.TICKABLE, tct=0.02)
    
    api.add_unit(name="UNIT_COMMANDER", type=UnitType.TICKABLE, m_class=NetSmokeWorker, thread_name="SMOKE_POOL", tier_layer=1, tier_name="SMOKE_TIER")
    api.add_unit(name="UNIT_RECEIVER", type=UnitType.TICKABLE, m_class=NetSmokeWorker, thread_name="SMOKE_POOL", tier_layer=1, tier_name="SMOKE_TIER")
    
    api.start() 
    print(f"Node {node_name} is fully running. Awaiting neighbor via UDP...")
    
    try:
        while not (LOCAL_TEST_PASSED and NET_TEST_PASSED):
            kernel.step() 
            time.sleep(0.005)
            
        print(f"\n\033[1;92m✓ [SUCCESS] All event-driven network smoke tests for node {node_name} PASSED!\033[0m")
        time.sleep(1.0)
        
    except KeyboardInterrupt:
        print("\nTest interrupted by user.")
    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        print("Stopping infrastructure...")
        api.stop()
        print(f"Node {node_name} stopped cleanly.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sanapo Network Smoke Test")
    parser.add_argument("node", choices=["ALPHA", "BETA"], help="Node Name")
    args = parser.parse_args()
    run_test_node(args.node)
