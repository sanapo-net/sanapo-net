import random
import pickle
import os
import ipaddress
from core.enums import TickInterval, Priority
from core.config import Config

class PersistentGenerator:
    """Base class with a private random instance for total isolation."""
    def __init__(self, name: str) -> None:
        self._seed_dir = "seeds"
        if not os.path.exists(self._seed_dir):
            os.makedirs(self._seed_dir)
        
        self._path = os.path.join(self._seed_dir, f"{name}.seed")
        # The own random
        self._rnd = random.Random()
        self._load_state()

    def _load_state(self) -> None:
        if os.path.exists(self._path):
            with open(self._path, 'rb') as f:
                state = pickle.load(f)
                # If in file dict, take key (for HostGenerator)
                if isinstance(state, dict):
                    self._rnd.setstate(state['rand_state'])
                    self._current_uid = state.get('uid', 100)
                else:
                    self._rnd.setstate(state)

    def _save_state(self, extra: dict = None) -> None:
        with open(self._path, 'wb') as f:
            if extra:
                extra['rand_state'] = self._rnd.getstate()
                pickle.dump(extra, f)
            else:
                pickle.dump(self._rnd.getstate(), f)

class FloatGenerator(PersistentGenerator):
    def __init__(self, name: str, min_val: float, max_val: float, peak: float) -> None:
        super().__init__(name)
        self._params = (min_val, max_val, peak)

    def next(self) -> float:
        val = self._rnd.triangular(*self._params)
        self._save_state()
        return round(val, 2)

class IPGenerator(PersistentGenerator):
    def __init__(self, name: str, network: str = "192.168.0.0/16") -> None:
        super().__init__(name)
        self._ips = list(ipaddress.ip_network(network).hosts())

    def next(self) -> str:
        ip = self._rnd.choice(self._ips)
        self._save_state()
        return str(ip)

class MACGenerator(PersistentGenerator):
    def __init__(self, name: str) -> None:
        super().__init__(name)

    def next(self) -> str:
        mac = ":".join(f"{self._rnd.randint(0, 255):02x}" for _ in range(6))
        self._save_state()
        return mac

class HostGenerator(PersistentGenerator):
    def __init__(self, name: str, start_uid: int = 100) -> None:
        self._current_uid = start_uid
        super().__init__(name)
        
        # 1. Intervals (DEFAULT - index 1 has weight 6)
        self._intervals = list(TickInterval)[:-2]
        self._int_weights = [5 if i == 1 else 1 for i in range(len(self._intervals))]
        
        # 2. Setting weights for timeouts from Config.ICMP_TIMEOUTS
        self._timeouts = Config.ICMP_TIMEOUTS
        self._timeout_weights = self._generate_timeout_weights()
        
        # Internal generators
        self._ip_gen = IPGenerator(f"{name}_internal_ip")
        self._mac_gen = MACGenerator(f"{name}_internal_mac")
        self._priorities = list(Priority)

    def _generate_timeout_weights(self) -> list[int]:
        """Generates weights: -1 (50%), 1st half (35%), 2nd half (15%)"""
        count = len(self._timeouts)
        weights = []
        mid = count // 2
        
        for i in range(count):
            if i == 0:
                weights.append(20)  # Weight for -1 (very common)
            elif i <= mid:
                weights.append(5)   # Weight for the first half
            else:
                weights.append(1)   # Weight for the "tail" of the list
        return weights

    def next(self) -> dict:
        uid = self._current_uid
        self._current_uid += 1
        
        # Selecting interval and timeout based on weights
        interval = self._rnd.choices(self._intervals, weights=self._int_weights, k=1)[0]
        timeout = self._rnd.choices(self._timeouts, weights=self._timeout_weights, k=1)[0]

        host_data = {
            "uid": uid,
            "ip": self._ip_gen.next(),
            "mac": self._mac_gen.next(),
            "icmp_interval": interval,
            "name": f"name_{uid}",
            "priority": self._rnd.choice(self._priorities),
            "icmp_timeout": float(timeout)
        }
        
        self._save_state(extra={'uid': self._current_uid})
        return host_data
