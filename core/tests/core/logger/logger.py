# core/logger.py
# This is draft of core/logger
# TODO move to config ?
# TODO for modules without secr, comfortable params
import datetime
import logging

from core.enums import Addr, MsgType, EvtType, CmdType, SysType, RptType, MessageInitError, Logs
from core.protocol import Frame

class MockSecretary:
    def __init__ (self,
        address: Addr,
        name: str
    ):
        self.address = address
        self.name = name

    def send_evt(self, evt_type: EvtType, payload: dict[str, any] = {}) -> None:
        """Broadcast an event to the system bus."""
        frame = Frame(
            msg_type=MsgType.EVENT,
            sender=self.address,
            evt_type=evt_type,
            payload=payload
        )
        print(frame)

class Logger:
    def __init__(self, secr: MockSecretary, console: bool = True, bus: bool = True):
        # Recursion protection flag | Maybe add to flag matrix?
        self._is_logging = True

        self.secr = secr
        # Flag matrix
        self.flags = {
            "console": [Logs.CRIT, Logs.ERR, Logs.WRN, Logs.INFO, Logs.DEBUG],
            "message": [Logs.CRIT, Logs.ERR, Logs.WRN, Logs.INFO, Logs.DEBUG],
            "file": [Logs.CRIT, Logs.ERR, Logs.WRN, Logs.INFO, Logs.DEBUG],
        }
        # The levels put in the bus
        self.bus_levels = {
            "ERR": EvtType.ERR,
            "WRN": EvtType.WRN,
            "INFO": EvtType.LOG
        }

    def set_secr(self, secr: MockSecretary) -> None:
        if not hasattr(self, "_secr") and isinstance(secr, MockSecretary):
            self._secr = secr
            self._address = secr.address
        else:
            self.wrn(f"Detected second module set! Obj: {secr}.")

    def _get_time(self):
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _output(self, level: str, text: str, payload: dict = None):
        # Colors for formated msg in console logging
        defaulColor = "\033[0m" # white
        outputColors = {
            "ERR": "\033[31m",  # red
            "CRITICAL": "\033[31m", # red
            "WRN": "\033[33m",  # yellow
            "INFO": "\033[0m",  # white
            "DEBUG": "\033[90m" # gray
        }

        time_str = self._get_time()

        addr_name = self.secr.address.name if hasattr(self.secr, 'address') else "UNKNOWN"
        
        formatted_msg = f"[{time_str}] [{addr_name}] [{level}]: {text}"

        if not self._is_logging: return

        if self.flags["console"]:
            print(f"{outputColors[level]} {formatted_msg}.{defaulColor}")
        if self.flags["file"]:
            with open("system.log", "a", encoding="utf-8") as f:
                f.write(formatted_msg + "\n")
        if self.flags["message"] and level in self.bus_levels:
            evt = self.bus_levels[level]
            bus_payload = {"msg": text}
            if payload:
                bus_payload.update(payload)
            try:
                self.secr.send_evt(evt_type=evt, payload=bus_payload)
            except Exception:
                self._is_logging = False

    # ---- Log executing ----
    
    """
    Read mask and return formated msg 
    Function for remove repeating in functions under
    """
    def _read_mapping(self, frame: Frame | None = None, mask: str = "") -> list:
        details = []
        mapping = {
            "M": f"{frame.msg_type}.",
            "S": f"From:{frame.sender.name}.",
            "R": f"Recipient:{frame.recipient}.",
            "P": f"Payload:{frame.payload['text'] if (frame.payload) else 'N/А'}.",
            "D": f"Deadline:{frame.deadline}.",
            "T": f"Exit time:{frame.time_ext_req}.",
            "t": f"{frame.evt_type or frame.sys_type or frame.cmd_type or frame.rpt_type}.",
            "e": f"Evt:{frame.evt_type.value if frame.evt_type else 'N/A'}.",
            "s": f"Sys:{frame.sys_type.value if frame.sys_type else 'N/A'}.",
            "c": f"Cmd:{frame.cmd_type.value if frame.cmd_type else 'N/A'}.",
            "r": f"Rtp:{frame.rpt_type.value if frame.rpt_type else 'N/A'}.",
            "i": f"ID:{frame.cmd_id}.",
            "w": f"ID:{frame.reason}.",
        }
        for char in mask:
            mapping.get(char)
            details.append(mapping[char])
        return details

    def err(self, text: str, frame: Frame | None = None, mask: str = ""):
        if frame and mask:
            details = self._read_mapping(frame, mask)

            if details:
                text = f"{text} | {' '.join(details)}"
        self._output("ERR", text)

    def crit(self, text: str, frame: Frame | None = None, mask: str = ""):
        if frame and mask:
            details = self._read_mapping(frame, mask)

            if details:
                text = f"{text} | {' '.join(details)}"
        self._output("CRITICAL", text)

    def wrn(self, text: str, frame: Frame | None = None, mask: str = ""):
        if frame and mask:
            details = self._read_mapping(frame, mask)

            if details:
                text = f"{text} | {' '.join(details)}"
        self._output("WRN", text)

    def info(self, text: str, frame: Frame | None = None, mask: str = ""):
        if frame and mask:
            details = self._read_mapping(frame, mask)

            if details:
                text = f"{text} | {' '.join(details)}"
        self._output("INFO", text)

    def debug(self, text: str, frame: Frame | None = None, mask: str = ""):
        if frame and mask:
            details = self._read_mapping(frame, mask)

            if details:
                text = f"{text} | {' '.join(details)}"
        self._output("DEBUG", text)
        
secr = MockSecretary(Addr.KERNEL, "test")
frame = Frame(
    msg_type = MsgType.COMMAND,
    sender = Addr.KERNEL,
    payload = {"text": "TestThing"},
    sys_type = SysType.APP_STOP,
    evt_type = EvtType.EVT_TEST,
    cmd_type = CmdType.APP_STOP,
    rpt_type = RptType.CANT_DO,
    recipient = Addr.KERNEL,
    cmd_id = "1337",
    deadline = 0.5,
    time_ext_req = 15.9,
    reason = "6 + 7 = siiix seeeeven"
)
logger = Logger(secr)
# Again set logger protection test
logger.set_secr(secr)
logger.set_secr(secr)
logger.set_secr(secr)
logger.wrn("Doesnt have food", frame, "MSRDTPtescriw")
logger.info("Doesnt have food", frame, "MSRDPtTescriw")
logger.crit("Doesnt have food", frame, "MSRDPtTescriw")
logger.err("Doesnt have food", frame, "MSRDPtTescriw")
logger.debug("Doesnt have food", frame, "MSRDPtTescriw")
# Example how use into module
# self.log = SmartLogger(self.secretary)
# TODO dont remember: logger must can work in "without secretary mode"