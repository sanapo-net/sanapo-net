# sanapo/base_module.py
from __future__ import annotations
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sanapo.logger import Logger
    from sanapo.config import Config
    from sanapo.enums import ModuleType
    from sanapo.secretary import Secretary

class BaseModule:
    def __init__(self, m_type: ModuleType, logger: Logger, secr: Secretary | None, config: Config):
        self.type = m_type
        self.log = logger
        self._secr = secr
        self._cfg = config
        self._is_running = True
        self._is_paused = False

    def step(self):
        """Method for TICKABLE modules. Overridden in the project."""
        pass

    def shutdown(self):
        """Soft shutdown (saving data, etc.)."""
        self._is_running = False

    def stop(self):
        """Forced cycle stop."""
        self._is_running = False

    def start(self):
        """For SIGMA/MASTER: start of the inner loop."""
        self._loop()

    def _loop(self):
        """Inner loop for standalone modules."""
        while self._is_running:
            if not self._is_paused:
                self.step()
            time.sleep(self._cfg.MODULE_TICK_TCT_DEFAULT)
