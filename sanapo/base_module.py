# sanapo/base_module.py
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sanapo.base_unit import UnitModuleView

class BaseModule:
    def __init__(self, unit_view: UnitModuleView):
        self.v: UnitModuleView = unit_view

    def define_manifest(self) -> dict:
        """The module itself describes its characteristics.
        
        Returns default manifest values. Subclasses may override this method
        to provide custom manifest data.
        """
        return {
            "version": "1.0.0",
            "role": "default",
            "is_public": False,
            "is_persistent": True
        }
    
    def on_net_connected(self, system_name: str):
        """Callback fired automatically when a network link is established."""
        pass

    def on_net_disconnected(self, system_name: str):
        """Callback fired automatically when a network link is lost."""
        pass
    
    def step(self):
        """Doings for every step here"""
        pass

    def stop(self):
        """Save/close resurses here"""
        pass

    def start(self):
        """Open/load resurses here, preparings and setup unit-params"""
        # For custom values, update them:
        # self._u.start_timeout = 0.5
        # self._u.stop_timeout = 2
        # self._u.step_timeout = 0.2
        self.v.started()
        pass

    def __repr__(self) -> str:
        cls_name = self.__class__.__name__
        parent_name = self.__class__.__base__.__name__
        obj_id = f"0x{id(self):X}"
        addr_info = getattr(self.v, 'addr', self.v)
        return f"<{cls_name}:{parent_name} addr={addr_info} id={obj_id}>"
    
    def __str__(self) -> str:
        cls_name = self.__class__.__name__
        addr_info = getattr(self.v, 'addr', self.v)
        return f"Module({cls_name} {addr_info})"