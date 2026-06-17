# sanapo/kernel_secretary.py
from __future__ import annotations
from typing import TYPE_CHECKING
from sanapo.secretary import Secretary
from sanapo.enums import SysType

if TYPE_CHECKING:
    from sanapo.kernel import Kernel
    from sanapo.message_broker import MessageBroker

class KernelSecretary(Secretary):
    """
    Specialized Secretary for the Kernel.
    Focused on SYSTEM signals but inherits full communication capabilities.
    """  

    def __init__(self, kernel: Kernel, broker: MessageBroker):
        super().__init__(
            address=kernel._addr,
            outbox=broker.bus,
            inbox=kernel._inbox,
            config=kernel._cfg,
            logger=kernel._log,
            evt_class=kernel._reg.evt,
            cmd_class=kernel._reg.cmd,
            resurrect_func=kernel.resurrect_frame
        )
        self._kernel = kernel
        self.auto_subscribe()

    # TODO del SUB UNSUB SUB_SETUP there
    def auto_subscribe(self) -> None:
        self._handlers_sys: dict[SysType, callable] = {
            SysType.NET_DISCONNECTED: self._kernel.on_net_disconnected,
            SysType.SUB: lambda frame: True,
            SysType.UNSUB: lambda frame: True,
            SysType.SUB_SETUP: lambda frame: True,
        }
