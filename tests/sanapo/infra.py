import os
import gc
import time
import shutil
import socket
import threading
from datetime import datetime

from sanapo.config import Config
from sanapo.enums import RptType, ThreadType, UnitType, BootTask, RptReason
from sanapo.enums import ClubAccessError, EnumRegistry, UnitStat
from sanapo.kernel import Kernel
from sanapo.views import KernelUserView
from sanapo.base_module import BaseModule
from sanapo.protocol import Frame
from sanapo.addr import Addr

try:
    from common.enums import EvtType, CmdType
except ImportError:
    import sys
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
    from common.enums import EvtType, CmdType

class Triggers:
    def __init__(self, triggers_list: list = None):
        if triggers_list is None:
            triggers_list = []
        self._triggers = dict.fromkeys(triggers_list, False)
        self._total_count = len(self._triggers)
        self._true_count = 0

    def __getattr__(self, name):
        if name in self._triggers:
            return self._triggers[name]
        raise AttributeError(f"Trigger '{name}' not exist")

    def __setattr__(self, name, value):
        if name in ("_triggers", "_total_count", "_true_count"):
            super().__setattr__(name, value)
        elif name in self._triggers:
            if not isinstance(value, bool):
                raise TypeError("Trigger value must be bool")
            if self._triggers[name] != value:
                self._triggers[name] = value
                self._true_count += 1 if value else -1
                status = "ok" if value else "fail"
                stats = f" ({self._true_count}/{self._total_count})"
                now_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                print(f'\033[95m{now_str} Trigger "{name}" - {status}{stats}\033[0m')
        else:
            raise AttributeError(f"Cannot create trigger '{name}'")

    @property
    def all_ok(self) -> bool:
        return self._true_count == self._total_count

    def _to_string(self) -> str:
        pairs = " ".join(f"{k}={int(v)}" for k, v in self._triggers.items())
        return f"Triggers: {pairs}"

    def __str__(self):
        return self._to_string()

    def __repr__(self):
        return self._to_string()

class TestLedger:
    def __init__(self, node_name: str = "ALPHA"):
        self.executed_tests = {}
        self.node_name = node_name
        self.sync_port = 45599
        self._current_class = "Test"
        self._current_test = "Unknown"
        self._current_nodes = []
        self._finish_received = False
        self._finish_lock = threading.Lock()

    def _now_str(self):
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    def start(self, test_name: str, class_name: str, nodes: list = None):
        print(f"\033[95m{self._now_str()} [ TEST ] >>> {test_name}\033[0m")
        self._current_class = class_name
        self._current_test = test_name
        self._current_nodes = nodes if nodes else []
        if nodes and len(nodes) > 1:
            self._global_barrier(class_name, "READY", nodes, as_server=True)
        dump_path = "consist_dump"
        try:
            shutil.rmtree(dump_path, ignore_errors=True)
            for ext in ("dump.json", "dump.bak", "dump.tmp"):
                p = f"{dump_path}_{ext}"
                if os.path.exists(p):
                    os.remove(p)
        except Exception:
            pass
        gc.collect()

    def start_assistent(self, test_name: str, class_name: str,
                        nodes: list = None, timeout: float = 20.0):
        print(f"\033[95m{self._now_str()} [ TEST ] >>> {test_name}\033[0m")
        self._current_class = class_name
        self._current_test = test_name
        self._current_nodes = nodes if nodes else []
        if nodes and len(nodes) > 1:
            self._global_barrier(class_name, "READY", nodes, timeout, as_server=False)

    def ok(self):
        self.executed_tests[self._current_test] = True
        print(f"\033[95m{self._now_str()} [  OK  ] ✓  {self._current_class}\033[0m")
        if self._current_nodes and len(self._current_nodes) > 1:
            self._global_barrier(self._current_class, "FINISHED", self._current_nodes, as_server=False)

    def fail(self, err_text: str = ""):
        self.executed_tests[self._current_test] = False
        print(f"\033[91m{self._now_str()} [ FAIL ] ✗  {self._current_class}\033[0m")
        if err_text:
            print(f"\033[91m{self._now_str()}    Error: {err_text}\033[0m")
        if self._current_nodes and len(self._current_nodes) > 1:
            self._global_barrier(self._current_class, "FINISHED", self._current_nodes, as_server=False)

    def start_finish_listener(self):
        """Launch a background thread that waits for FINISHED signal from ALPHA."""
        if not self._current_nodes or len(self._current_nodes) <= 1:
            return
        self._finish_received = False
        def listen():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(('127.0.0.1', self.sync_port))
                s.listen(1)
                s.settimeout(1.0)
                while not self._finish_received:
                    try:
                        conn, _ = s.accept()
                        data = conn.recv(1024).decode()
                        conn.close()
                        parts = data.split(":")
                        if len(parts) == 3 and parts[1] == self._current_class and parts[2] == "FINISHED":
                            remote_node = parts[0]
                            if remote_node in self._current_nodes and remote_node != self.node_name:
                                with self._finish_lock:
                                    self._finish_received = True
                    except socket.timeout:
                        continue
                    except OSError:
                        break
        threading.Thread(target=listen, daemon=True).start()

    def check_finish(self) -> bool:
        """Return True if FINISHED signal has been received."""
        with self._finish_lock:
            return self._finish_received

    def print_results(self):
        print("\n" + "=" * 70)
        print("  SANAPO FRAMEWORK V1 - AUTOMATED VERIFICATION MATRIX")
        print("=" * 70)
        total = 0
        passed = 0
        has_failures = False
        for name, success in self.executed_tests.items():
            total += 1
            status = "\033[92m[PASSED]\033[0m" if success else "\033[91m[FAILED]\033[0m"
            if not success:
                has_failures = True
            else:
                passed += 1
            print(f"- {name:<55} -> {status}")
        print("=" * 70)
        if has_failures:
            print("\033[1;91mCRITICAL VERDICT: INFRASTRUCTURE DESTABILIZED!\033[0m")
        elif passed == total and total > 0:
            print("\033[1;92mGRAND VERDICT: FULL ARCHITECTURAL TRIUMPH!\033[0m")
        else:
            print("\033[1;93mVERDICT: NO TESTS WERE EXECUTED.\033[0m")
        print("=" * 70 + "\n")

    def _clear_udp_sys_buffer(self, sock: socket.socket):
        old_timeout = sock.gettimeout()
        try:
            sock.setblocking(False)
            while True:
                sock.recvfrom(65535)
        except BlockingIOError:
            pass
        finally:
            sock.settimeout(old_timeout)

    def _global_barrier(self, class_name: str, phase: str, nodes: list,
                        timeout: float = 120.0, as_server: bool = None) -> bool:
        """
        Generic synchronization barrier.
        If as_server is True, this node acts as server (waits for connections).
        If as_server is False, this node connects to the server.
        If None, legacy behavior: ALPHA is server, others are clients.
        """
        expected = set(nodes)
        collected = {self.node_name}
        sync_port = self.sync_port
        print(f"\033[95m{self._now_str()} [ SYNC ] {self.node_name} {phase} for {class_name}\033[0m")
        start_time = time.time()

        if as_server is None:
            is_server = (self.node_name == "ALPHA")
        else:
            is_server = as_server

        if is_server:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(('127.0.0.1', sync_port))
                s.listen(1)
                s.settimeout(1.0)
                while len(collected) < len(expected):
                    if time.time() - start_time > timeout:
                        print(f"\033[91m{self._now_str()} [ SYNC ] TIMEOUT {class_name}\033[0m")
                        return False
                    try:
                        conn, _ = s.accept()
                        data = conn.recv(1024).decode()
                        conn.close()
                        parts = data.split(":")
                        if len(parts) == 3 and parts[1] == class_name and parts[2] == phase:
                            remote_node = parts[0]
                            if remote_node in expected and remote_node != self.node_name:
                                collected.add(remote_node)
                    except socket.timeout:
                        continue
                    except OSError:
                        continue
        else:
            connected = False
            while not connected:
                if time.time() - start_time > timeout:
                    print(f"\033[91m{self._now_str()} [ SYNC ] TIMEOUT {class_name}\033[0m")
                    return False
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.settimeout(1.0)
                        s.connect(('127.0.0.1', sync_port))
                        msg = f"{self.node_name}:{class_name}:{phase}"
                        s.sendall(msg.encode())
                        connected = True
                        print(f"\033[95m{self._now_str()} [ SYNC ] {self.node_name} sent message\033[0m")
                except (ConnectionRefusedError, OSError, socket.timeout):
                    time.sleep(0.5)
                    continue

        print(f"\033[95m{self._now_str()} [ SYNC ] ALL {phase} for {class_name}\033[0m")
        return True


def setup_config(node_name: str):
    Config.BOOT_UI_MODE = "CUI"
    Config.KERNEL_TCT = 0.01
    Config.HOST = "0.0.0.0"
    Config.UDP_PORT_DEFAULT = 45500
    Config.TCP_PORT_DEFAULT = 45501 if node_name == "ALPHA" else 45502
    Config.UDP_BEACON_INTERVAL = 1.0
    Config.CONN_KEEP_ALIVE = 20.0
    Config.HANDSHAKE_TIMEOUT = 5.0
    Config.ADDR_BROKER_STR = "BROKER"
    Config.BROKER_BUS_READ_LIMIT = 50
    Config.MAGIC_HEADER = b"SanaPo10"
    Config.NET_PROJECT_TOKEN = b"PROJ00"
    Config.NET_ALLOWED_IPS = []
    Config.NET_AUTO_CONNECT = True
    Config.HIBERNATE_MODE = False
    Config.DEFAULT_LOG_FLAGS["file"] = []