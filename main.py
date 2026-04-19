# main.py
from __future__ import annotations

from core.config import Config
from core.kernel import Kernel
from core.settings.settings_manager import SettingsManager
from core.buffer.buffer_manager import BufferManager
from core.network.network_manager import Network

class Tools:
    """Data proxy object for modules"""
    config = Config()
    settings: SettingsManager = None
    buffer: BufferManager = None
    network: Network = None

tools = Tools
kernel = Kernel(tools)
tools.settings = SettingsManager(tools, kernel.setup_module_environment)
tools.buffer = BufferManager(tools, kernel.setup_module_environment)

