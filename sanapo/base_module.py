# sanapo/base_module.py
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sanapo.base_unit import UnitModuleView

class BaseModule:
    def __init__(self, u: UnitModuleView, **params):
        self._u: UnitModuleView = u
        self._is_running = True
        self._is_paused = False

    def define_manifest(self) -> dict:
        """The module itself describes its characteristics."""
        """
        return {
            "version": "2.4.1",      # Specific module version
            "tags": {"some_teg",...},# Skill Tags
            "role": "default",       # Role in system
            "is_public": True,       # Can module be public
            "is_persistent": True    # Save module to dump for restarting
        }
        """
        return {}
    
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
        self._u.started()
        pass
