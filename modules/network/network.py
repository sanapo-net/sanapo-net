# modules/network/network.py
from __future__ import annotations
import copy

from sanapo.base_module import BaseModule
from modules.network.device import Device
from modules.network.iface import Iface
from modules.network.link import Link
from common.enums import DeviceType, Priority, IfaceType

class Network(BaseModule):
    """Manages the network topology, generates snapshots, and keeps the real state.
    
    Acts as a ZOMBIE unit within the sanapo framework ecosystem.
    """
    
    def __init__(self, unit_view, uid: int, name: str = "", name_u: str = ""):
        # Initialize the sanapo framework module state
        super().__init__(unit_view)
        
        self.uid = uid
        self.name = name
        self.name_u = name_u
        
        # Live mirrors of reality topology graph
        self.devices: dict[int, Device] = {}
        self.ifaces: dict[int, Iface] = {}
        self.links: dict[int, Link] = {}
        
        # Internal auto-increment counters for node generation
        self.last_device_uid = 0
        self.last_iface_uid = 0
        self.last_link_uid = 0
        
        # Snapshot cache and versioning architecture
        self.snapshot_ver = 0
        self.snapshot_dict: dict = {}
        self.snapshot_full: Network | None = None
        
        # Initial boot snapshot generation
        self._update_snapshots()

    def define_manifest(self) -> dict:
        """Overrides framework manifest to describe persistent network capability."""
        manifest = super().define_manifest()
        manifest.update({
            "version": "1.0.0",
            "role": "network_topology_mirror",
            "is_public": True,
            "is_persistent": True
        })
        return manifest

    def step(self):
        """Zombie unit type - no periodic loop actions needed, logic is event-driven."""
        pass

    def _update_snapshots(self):
        """Rebuilds both light and full snapshots and bumps the version."""
        self.snapshot_ver += 1
        
        # 1. Rebuild light flat dict snapshot for fast background scanners
        light_table = {}
        for uid, iface in self.ifaces.items():
            light_table[uid] = {
                "uid": iface.uid,
                "device_uid": iface.device.uid if iface.device else None,
                "device_name": iface.device.name if iface.device else "",
                "ip": iface.ip,
                "mac": iface.mac,
                "icmp_interval": iface.icmp_interval,
                "icmp_timeout": iface.icmp_timeout,
                "opened_ports": copy.copy(iface.opened_ports)
            }
        self.snapshot_dict = {"ver": self.snapshot_ver, "tab": light_table}
        
        # 2. Rebuild deep full snapshot with strict recursion safety gates
        old_dict = self.snapshot_dict
        old_full = self.snapshot_full
        self.snapshot_dict = {}
        self.snapshot_full = None
        
        self.snapshot_full = copy.deepcopy(self)
        
        self.snapshot_dict = old_dict
        self.snapshot_full = old_full

    # === Device Management ===

    def add_device(self, type: DeviceType, priority: Priority, name: str = "", name_u: str = "") -> Device:
        self.last_device_uid += 1
        dev = Device(uid=self.last_device_uid, type=type, priority=priority, name=name, name_u=name_u)
        self.devices[dev.uid] = dev
        self._update_snapshots()
        return dev

    def edit_device_by_uid(self, uid: int, **kwargs) -> bool:
        """Updates allowed properties of a device and syncs snapshots."""
        if uid not in self.devices:
            return False
            
        dev = self.devices[uid]
        allowed_fields = {"type", "priority", "name", "name_u", "tags", "os", "brand", "dname"}
        
        modified = False
        for key, value in kwargs.items():
            if key in allowed_fields:
                setattr(dev, key, value)
                modified = True
                
        if modified:
            self._update_snapshots()
        return modified

    def del_device_by_uid(self, uid: int) -> bool:
        if uid not in self.devices:
            return False
            
        dev = self.devices[uid]
        for iface in list(dev.ifaces):
            self.del_iface_by_uid(iface.uid)
            
        del self.devices[uid]
        self._update_snapshots()
        return True

    # === Interface Management ===

    def add_iface(self, device: Device, type: IfaceType, speed: int, max_links: int = 1, name: str = "", ip: str = "", mac: str = "") -> Iface:
        self.last_iface_uid += 1
        
        if "wifi" in type.value and max_links == 1:
            max_links = 512
            
        iface = Iface(uid=self.last_iface_uid, type=type, speed=speed, device=device, name=name, ip=ip, mac=mac)
        iface.max_links = max_links 
        
        self.ifaces[iface.uid] = iface
        device.ifaces.append(iface)
        
        self._update_snapshots()
        return iface

    def edit_iface_by_uid(self, uid: int, **kwargs) -> bool:
        """Updates allowed properties of an interface and recalculates internal intervals if needed."""
        if uid not in self.ifaces:
            return False
            
        iface = self.ifaces[uid]
        allowed_fields = {
            "type", "speed", "name", "name_u", "ip", "mac", 
            "ip_is_dynamic", "mac_is_dynamic", "icmp_timeout", 
            "icmp_interval", "max_links"
        }
        
        modified = False
        old_type = iface.type
        
        for key, value in kwargs.items():
            if key in allowed_fields:
                setattr(iface, key, value)
                modified = True
                
        if modified:
            # Re-trigger time intervals calculation if the physical media type changed
            if "type" in kwargs and kwargs["type"] != old_type:
                iface.__post_init__()
            self._update_snapshots()
        return modified

    def del_iface_by_uid(self, uid: int) -> bool:
        if uid not in self.ifaces:
            return False
            
        iface = self.ifaces[uid]
        for link in list(iface.links):
            self.del_link_by_uid(link.uid)
            
        if iface.device:
            iface.device.ifaces.remove(iface)
            
        del self.ifaces[uid]
        self._update_snapshots()
        return True

    # === Link Management ===

    def add_link(self, iface1: Iface, iface2: Iface, priority: Priority = Priority.LOW, name: str = "") -> Link:
        """Creates a link with strict duplicate and capacity validation gates."""
        # 1. Duplication gate
        for existing_link in iface1.links:
            if iface2 in existing_link.ifaces:
                raise ValueError(f"Link between interface {iface1.uid} and {iface2.uid} already exists.")

        # 2. Capacity gate
        if len(iface1.links) >= getattr(iface1, 'max_links', 1):
            raise ValueError(f"Interface {iface1.uid} has reached its maximum links limit.")
            
        if len(iface2.links) >= getattr(iface2, 'max_links', 1):
            raise ValueError(f"Interface {iface2.uid} has reached its maximum links limit.")

        # 3. Deployment
        self.last_link_uid += 1
        link = Link(uid=self.last_link_uid, ifaces=[iface1, iface2], priority=priority, name=name, type=IfaceType.UNKNOWN)
        
        self.links[link.uid] = link
        self._update_snapshots()
        return link

    def edit_link_by_uid(self, uid: int, **kwargs) -> bool:
        """Updates allowed metadata of a frozen link using object.__setattr__ shortcut."""
        if uid not in self.links:
            return False
            
        link = self.links[uid]
        allowed_fields = {"priority", "name"} # Physical attributes (speed/type) are strictly locked
        
        modified = False
        for key, value in kwargs.items():
            if key in allowed_fields:
                # Safely write to frozen instance metadata properties
                object.__setattr__(link, key, value)
                modified = True
                
        if modified:
            self._update_snapshots()
        return modified

    def del_link_by_uid(self, uid: int) -> bool:
        if uid not in self.links:
            return False
            
        link = self.links[uid]
        for iface in link.ifaces:
            if link in iface.links:
                iface.links.remove(link)
                
        del self.links[uid]
        self._update_snapshots()
        return True
