# main.py
from core.enums import Addr
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
tools.settings = SettingsManager(tools, kernel.get_secr)
tools.buffer = BufferManager(tools, kernel.get_secr)

