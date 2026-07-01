# tests/sanapo/network_tests.py
import time
import inspect

from sanapo.base_module import BaseModule
from sanapo.enums import UnitType, RptType, EnumRegistry, ConnState
from sanapo.kernel import Kernel
from sanapo.views import KernelUserView
from sanapo.protocol import Frame
from tests.sanapo.infra import Triggers, setup_config

try:
    from common.enums import EvtType, CmdType
except ImportError:
    import sys, os
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
    from common.enums import EvtType, CmdType



def test_network_auto_discovery(ledger, node_name, nodes):
    def_name = inspect.currentframe().f_code.co_name
    test_name = "Network: Auto-discovery and TCP Connection"
    if node_name == "ALPHA":
        ledger.start(test_name, def_name, nodes)
    else:
        ledger.start_assistent(test_name, def_name, nodes)

    triggers = Triggers(["manifest", "connected", "connect_ready"])

    class ConnectDetector(BaseModule):
        def start(self):
            return True
        def on_net_ready(self, system_name):
            triggers.connect_ready = True

    setup_config(node_name)
    reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
    kernel = Kernel(enum_reg=reg, system_name=node_name)
    api = KernelUserView(kernel)
    kernel._cfg.TCP_PORT_DEFAULT = 45501 if node_name == "ALPHA" else 45502
    # Для этого теста оставляем автообнаружение
    kernel._cfg.NET_BEACON = True
    kernel._cfg.NET_AUTO_CONNECT_BY_BEACON = True

    try:
        mnfst = {"is_public": True}
        api.add_unit("PUBLIC", UnitType.TICKABLE, BaseModule, manifest=mnfst)
        api.add_unit("CONNECT_DETECTOR", UnitType.TICKABLE, ConnectDetector)
        api.start()
        max_wait = 1500
        while not triggers.all_ok and max_wait > 0:
            kernel.step()
            time.sleep(0.005)
            if api._kernel._tcp_service._connections and not triggers.connected:
                triggers.connected = True
            if api._kernel._broker._remote_manifests and not triggers.manifest:
                triggers.manifest = True
            max_wait -= 1
        if node_name == "ALPHA":
            if triggers.all_ok:
                ledger.ok()
            else:
                ledger.fail(f"Timeout {triggers}")
            kernel._tcp_service.disconnect_all()
        else:
            ledger.start_finish_listener()
            while not ledger.check_finish():
                kernel.step()
                time.sleep(0.005)
            kernel._tcp_service.disconnect_all()
    except Exception as e:
        if node_name == "ALPHA":
            ledger.fail(str(e))
    finally:
        api.stop()
        while api.is_running:
            kernel.step()
            time.sleep(0.05)


def test_network_command_exchange(ledger, node_name, nodes):
    def_name = inspect.currentframe().f_code.co_name
    test_name = "Network: Command and Report Exchange"
    if node_name == "ALPHA":
        ledger.start(test_name, def_name, nodes)
    else:
        ledger.start_assistent(test_name, def_name, nodes)

    triggers = Triggers(["manifest", "connected", "connect_ready",
                         "local_cmd", "remote_cmd", "local_rpt", "remote_rpt"])

    class Commander(BaseModule):
        def start(self):
            self.local = self.v.addr.system
            self.remote = "BETA" if self.local == "ALPHA" else "ALPHA"
            return True
        def on_rpt(self, frame: Frame):
            if frame.rpt_type == RptType.DONE:
                if frame.sender.system == self.local:
                    triggers.local_rpt = True
                else:
                    triggers.remote_rpt = True
        def on_net_ready(self, sys_name) -> None:
            triggers.connect_ready = True
            for target_type, sys in [("local", self.local), ("remote", sys_name)]:
                target = self.v.addr_by_str(f"{sys}:REPORTER")
                if target:
                    p = {"data": f"hello from {self.v.addr} ({target_type})"}
                    self.v.scr.send_cmd(target, CmdType.CMD_TEST, self.on_rpt, payload=p)

    class Reporter(BaseModule):
        def start(self):
            self.v.scr.subscribe(cb=self.on_cmd, cmd=CmdType.CMD_TEST)
            self.local = self.v.addr.system
            self.remote = "BETA" if self.local == "ALPHA" else "ALPHA"
            return True
        def on_cmd(self, frame: Frame):
            if self.local == "ALPHA":
                if frame.sender.system == self.local:
                    triggers.local_cmd = True
                else:
                    triggers.remote_cmd = True
            self.v.scr.send_rpt(frame.sender, frame.cmd_id, RptType.DONE, frame.payload)

    setup_config(node_name)
    reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
    kernel = Kernel(enum_reg=reg, system_name=node_name)
    api = KernelUserView(kernel)
    kernel._cfg.TCP_PORT_DEFAULT = 45503 if node_name == "ALPHA" else 45504
    kernel._cfg.NET_BEACON = False
    kernel._cfg.NET_AUTO_CONNECT_BY_BEACON = False

    try:
        mnfst = {"is_public": True}
        api.add_unit("COMMANDER", UnitType.TICKABLE, Commander, manifest=mnfst)
        api.add_unit("REPORTER", UnitType.TICKABLE, Reporter, manifest=mnfst)
        api.start()
        
        if node_name == "ALPHA":
            kernel._tcp_service.connect_to("127.0.0.1", 45504)
            
        max_wait = 1500
        while not triggers.all_ok and max_wait > 0:
            kernel.step()
            time.sleep(0.005)
            if api._kernel._tcp_service._connections and not triggers.connected:
                triggers.connected = True
            if api._kernel._broker._remote_manifests and not triggers.manifest:
                triggers.manifest = True
            max_wait -= 1
            
        if node_name == "ALPHA":
            if triggers.all_ok:
                ledger.ok()
            else:
                ledger.fail(f"Timeout {triggers}")
            kernel._tcp_service.disconnect_all()
        else:
            ledger.start_finish_listener()
            while not ledger.check_finish():
                kernel.step()
                time.sleep(0.005)
            kernel._tcp_service.disconnect_all()
    except Exception as e:
        if node_name == "ALPHA":
            ledger.fail(str(e))
    finally:
        api.stop()
        while api.is_running:
            kernel.step()
            time.sleep(0.05)


def test_network_service_discovery(ledger, node_name, nodes):
    def_name = inspect.currentframe().f_code.co_name
    test_name = "Network: Full Service Discovery (Role + Tag)"
    if node_name == "ALPHA":
        ledger.start(test_name, def_name, nodes)
    else:
        ledger.start_assistent(test_name, def_name, nodes)

    triggers = Triggers(["connected", "manifest", "connect_ready",
                         "role_found", "tag_found", "role_cmd_ok", "tag_cmd_ok"])

    class Reporter(BaseModule):
        def start(self):
            self.v.scr.subscribe(cb=self._on_cmd, cmd=CmdType.CMD_TEST)
            return True
        def _on_cmd(self, frame):
            self.v.scr.send_rpt(frame.sender, frame.cmd_id, RptType.DONE, frame.payload)

    class FinderCommander(BaseModule):
        def start(self):
            self.local = self.v.addr.system
            self.remote = "BETA" if self.local == "ALPHA" else "ALPHA"
            return True
        def on_net_ready(self, sys_name):
            triggers.connect_ready = True
            role_addrs = self.v.get_remote_addrs_by_role("some_role1")
            if role_addrs:
                triggers.role_found = True
                self.v.scr.send_cmd(role_addrs[0], CmdType.CMD_TEST, self._on_role_done,
                                    payload={"text": "by_role"})
            tag_addrs = self.v.get_remote_addrs_by_tag("some_tag1")
            if tag_addrs:
                triggers.tag_found = True
                self.v.scr.send_cmd(tag_addrs[0], CmdType.CMD_TEST, self._on_tag_done,
                                    payload={"text": "by_tag"})
        def _on_role_done(self, frame):
            triggers.role_cmd_ok = True
        def _on_tag_done(self, frame):
            triggers.tag_cmd_ok = True

    setup_config(node_name)
    reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
    kernel = Kernel(enum_reg=reg, system_name=node_name)
    api = KernelUserView(kernel)
    kernel._cfg.TCP_PORT_DEFAULT = 45505 if node_name == "ALPHA" else 45506
    kernel._cfg.NET_BEACON = False
    kernel._cfg.NET_AUTO_CONNECT_BY_BEACON = False

    try:
        if node_name == "ALPHA":
            api.add_unit("COMMANDER", UnitType.TICKABLE, FinderCommander,
                         manifest={"is_public": True})
        else:
            api.add_unit("REPORTER-1", UnitType.TICKABLE, Reporter,
                         manifest={"is_public": True, "tags": ["some_tag1"], "role": "some_role1"})
            api.add_unit("REPORTER-2", UnitType.TICKABLE, BaseModule,
                         manifest={"is_public": True, "tags": ["some_tag2"], "role": "some_role2"})
        api.start()
        
        if node_name == "ALPHA":
            kernel._tcp_service.connect_to("127.0.0.1", 45506)
            
        max_wait = 1500
        while not triggers.all_ok and max_wait > 0:
            kernel.step()
            time.sleep(0.005)
            if api._kernel._tcp_service._connections and not triggers.connected:
                triggers.connected = True
            if api._kernel._broker._remote_manifests and not triggers.manifest:
                triggers.manifest = True
            max_wait -= 1
            
        if node_name == "ALPHA":
            if triggers.all_ok:
                ledger.ok()
            else:
                ledger.fail(f"Timeout {triggers}")
            kernel._tcp_service.disconnect_all()
        else:
            ledger.start_finish_listener()
            while not ledger.check_finish():
                kernel.step()
                time.sleep(0.005)
            kernel._tcp_service.disconnect_all()
    except Exception as e:
        if node_name == "ALPHA":
            ledger.fail(str(e))
    finally:
        api.stop()
        while api.is_running:
            kernel.step()
            time.sleep(0.05)


def test_network_handshake_integrity(ledger, node_name, nodes):
    def_name = inspect.currentframe().f_code.co_name
    test_name = "Network: Handshake integrity (token-meta exchange)"
    if node_name == "ALPHA":
        ledger.start(test_name, def_name, nodes)
    else:
        ledger.start_assistent(test_name, def_name, nodes)

    triggers = Triggers(["server_sent_meta", "client_sent_meta", 
                         "server_got_meta", "client_got_meta",
                         "both_done"])

    class HandshakeMonitor(BaseModule):
        def start(self):
            self._role = "handshake_role"
            return True
            
        def on_net_ready(self, sys_name):
            try:
                addrs = self.v.get_remote_addrs_by_role(self._role)
                if addrs:
                    if self.v.addr.system == "ALPHA":
                        triggers.client_got_meta = True
                    else:
                        triggers.server_got_meta = True
            except Exception:
                pass
            
            try:
                broker = self.v._unit._broker
                for addr_str, manifest in broker._local_manifests.items():
                    if hasattr(manifest, 'role') and manifest.role == self._role:
                        if self.v.addr.system == "ALPHA":
                            triggers.client_sent_meta = True
                        else:
                            triggers.server_sent_meta = True
                        break
            except Exception:
                pass
            
            if triggers.server_got_meta and triggers.server_sent_meta and \
               triggers.client_got_meta and triggers.client_sent_meta:
                triggers.both_done = True

    setup_config(node_name)
    reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
    kernel = Kernel(enum_reg=reg, system_name=node_name)
    api = KernelUserView(kernel)
    kernel._cfg.TCP_PORT_DEFAULT = 45507 if node_name == "ALPHA" else 45508

    try:
        if node_name == "ALPHA":
            api.add_unit("CLIENT_UNIT", UnitType.TICKABLE, HandshakeMonitor,
                         manifest={"is_public": True, "role": "handshake_role"})
        else:
            api.add_unit("SERVER_UNIT", UnitType.TICKABLE, HandshakeMonitor,
                         manifest={"is_public": True, "role": "handshake_role"})
        api.start()
        
        if node_name == "ALPHA":
            max_wait = 1500
            while not triggers.both_done and max_wait > 0:
                kernel.step()
                time.sleep(0.005)
                if not triggers.client_got_meta:
                    try:
                        addrs = api._kernel._broker._remote_manifests
                        for addr_str, manifest in addrs.items():
                            if manifest.get("role") == "handshake_role":
                                triggers.client_got_meta = True
                                break
                    except Exception:
                        pass
                
                if not triggers.client_sent_meta:
                    try:
                        for addr_str, manifest in api._kernel._broker._local_manifests.items():
                            if hasattr(manifest, 'role') and manifest.role == "handshake_role":
                                triggers.client_sent_meta = True
                                break
                    except Exception:
                        pass
                
                if triggers.client_got_meta and triggers.client_sent_meta:
                    triggers.both_done = True
                    
                max_wait -= 1
                
            if triggers.both_done:
                ledger.ok()
            else:
                ledger.fail(f"Triggers: {triggers}")
            kernel._tcp_service.disconnect_all()
        else:
            ledger.start_finish_listener()
            while not ledger.check_finish() and not triggers.both_done:
                kernel.step()
                time.sleep(0.005)
                
                if not triggers.server_got_meta:
                    try:
                        addrs = api._kernel._broker._remote_manifests
                        for addr_str, manifest in addrs.items():
                            if manifest.get("role") == "handshake_role":
                                triggers.server_got_meta = True
                                break
                    except Exception:
                        pass
                
                if not triggers.server_sent_meta:
                    try:
                        for addr_str, manifest in api._kernel._broker._local_manifests.items():
                            if hasattr(manifest, 'role') and manifest.role == "handshake_role":
                                triggers.server_sent_meta = True
                                break
                    except Exception:
                        pass
                
                if triggers.server_got_meta and triggers.server_sent_meta:
                    triggers.both_done = True
                    
            kernel._tcp_service.disconnect_all()
    except Exception as e:
        if node_name == "ALPHA":
            ledger.fail(str(e))
    finally:
        api.stop()
        while api.is_running:
            kernel.step()
            time.sleep(0.05)
