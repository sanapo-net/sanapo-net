# transport/adapters/__init__.py
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sanapo.protocol import Frame
    from sanapo.addr import Addr

class BaseAdapterTransport(ABC):
    """Standard interface for all communication channels."""
    def __init__(self, sanapo_addr: Addr, spec_addr: any, is_native: bool = True):
        self.sanapo_addr = sanapo_addr
        self.spec_addr = spec_addr
        self.is_native = is_native

    @abstractmethod
    def send(self, frame: Frame) -> bool: pass

    @abstractmethod
    def read(self) -> dict[str, any]: pass

    @abstractmethod
    def is_empty(self) -> bool: pass

    @abstractmethod
    def is_ready(self) -> bool: pass