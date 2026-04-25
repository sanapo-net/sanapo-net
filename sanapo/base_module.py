# sanapo/base_module.py
from __future__ import annotations
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sanapo.logger import Logger
    from sanapo.config import Config
    from sanapo.enums import UnitType
    from sanapo.secretary import Secretary

class BaseModule:
    def __init__(self, m_type: UnitType, logger: Logger, secr: Secretary | None, config: Config):
        self.type = m_type
        self.log = logger
        self._secr = secr
        self._cfg = config
        self._is_running = True
        self._is_paused = False

    def step(self):
        pass

    def stop(self):
        pass

    def start(self):
        pass

