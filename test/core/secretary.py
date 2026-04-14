from protocol import Frame
from enums import EvtType
from enums import Addr
from enums import MsgType



class SecretaryTest:
    def __init__ (self,
        address: Addr,
        name: str
    ):
        self.address = address

    def send_evt(self, evt_type: EvtType, payload: dict[str, any] = {}) -> None:
        """Broadcast an event to the system bus."""
        frame = Frame(
            msg_type=MsgType.EVENT,
            sender=self.address,
            evt_type=evt_type,
            payload=payload
        )
        print(frame)
