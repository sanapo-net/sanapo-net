# sanapo/kernel_secretary.py
from __future__ import annotations
from typing import TYPE_CHECKING
from sanapo.secretary import Secretary
from sanapo.enums import SysType

if TYPE_CHECKING:
    from sanapo.kernel import Kernel
    from sanapo.protocol import Frame
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

    def auto_subscribe(self) -> None:
        pass

    def _process_system(self, frame: Frame) -> bool:
        """
        Kernel-level system message orchestration.
        """
        if super()._process_system(frame):
            return True

        if frame.sys_type == SysType.NET_CONNECTED:
            remote_sys = frame.payload.get("sys_name")
            self._kernel.handle_new_federation(remote_sys)
            return True
            
        elif frame.sys_type == SysType.REG_UNIT:
            manifest_data = frame.payload.get("manifest")
            self._kernel.register_remote_unit(manifest_data)
            return True

        return False
