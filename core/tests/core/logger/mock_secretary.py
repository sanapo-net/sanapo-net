# core/tests/core/logger/mock_logger.py

from core.enums import Addr, MsgType, EvtType, CmdType, SysType, RptType
from core.protocol import Frame

class MockSecretary:
    funny_thing = [
        "My scream! Your scream! 🗣️",
        "My run! Your run! 🏃",
        "My cave! Your cave! 🏠",
        "My fire! Your fire! 🔥",
        "My meat! Your meat! 🍖",
        "My sleep! Your sleep! 😴",
        "My spirit! Your spirit! 👻",
    ]
    
    def __init__ (self,
        address: Addr,
        name: str
    ):
        self.address = address
        self.name = name

    def send_evt(self, evt_type: EvtType, payload: dict[str, any] = {}) -> None:
        frame = Frame(
            msg_type=MsgType.EVENT,
            sender=self.address,
            evt_type=evt_type,
            payload=payload
        )
        print(self.funny_thing)