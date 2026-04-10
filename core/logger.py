# core/logger.py
# This is draft of core/logger
# TODO move to config ?
# TODO for modules without secr, comfortable params
import datetime
import logging

from core.enums import EvtType
from core.secretary import Secretary
from core.protocol import Frame

class Logger:
    def __init__(self, secr: Secretary, console: bool = True, bus: bool = True):
        self.secr = secr
        # Flag matrix
        self.flags = {
            "CONSOLE": console,
            "SEND_EVT": bus,
            "FILE": True
        }
        # The levels put in the bus
        self.bus_levels = {
            "ERR": EvtType.ERR,
            "WRN": EvtType.WRN,
            "INFO": EvtType.LOG
        }

    def set_secr(self, secr: Secretary) -> None:
        if self._secr is None and isinstance(secr, Secretary):
            self._secr = secr
            self._address = secr.address
        else:
            pass # TODO fix err vet

    def _get_time(self):
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _output(self, level: str, text: str, payload: dict = None):
        time_str = self._get_time()
        
        addr_name = self.secr.address.name if hasattr(self.secr, 'address') else "UNKNOWN"
        
        formatted_msg = f"[{time_str}] [{addr_name}] [{level}]: {text}"

        if self.flags["CONSOLE"]:
            print(formatted_msg)
        if self.flags["FILE"]:
            with open("system.log", "a", encoding="utf-8") as f:
                f.write(formatted_msg + "\n")
        if self.flags["SEND_EVT"] and level in self.bus_levels:
            evt = self.bus_levels[level]
            bus_payload = {"msg": text}
            if payload:
                bus_payload.update(payload)
            try:
                self.secr.send_evt(evt_type=evt, payload=bus_payload)
            except Exception:
                pass
    
    def crit(self, text: str, **kwargs):  self._output("CRITICAL", text, kwargs)
    def err(self, text: str, **kwargs):   self._output("ERR", text, kwargs)
    def wrn(self, text: str, **kwargs):   self._output("WRN", text, kwargs)
    def info(self, text: str, **kwargs):  self._output("INFO", text, kwargs)
    def debug(self, text: str):           self._output("DEBUG", text)

# Example how use into module
# self.log = SmartLogger(self.secretary)
# TODO add "." to every text
# TODO dont remember: logger must can work in "without secretary mode"
# TODO self._log.info(text, frame, "MSRPDTtescriw")
"""
===MAP OF CHARS:===
M Frame.msg_type 
S Frame.sender
R Frame.recipient
P Frame.payload["text"]
D Frame.deadline
T Frame.time_ext_req
t Frame.evt_type or sys_type or cmd_type or rpt_type (subType)
e Frame.evt_type
s Frame.sys_type
c Frame.cmd_type
r Frame.rpt_type
i Frame.cmd_id
w Frame.reason # Why ?
add to text 

def err(self, text: str, frame: Any = None, mask: str = ""):
    if frame and mask:
        details = []
        mapping = {
            "S": f"From:{frame.sender.name}",
            "r": f"Type:{frame.rpt_type.value if frame.rpt_type else 'N/A'}",
            "i": f"ID:{frame.cmd_id}",
            "e": f"Evt:{frame.evt_type.value if frame.evt_type else 'N/A'}",
        }
        for char in mask:
            mapping.get(char)
            details.append(mapping[char])
        if details:
            text = f"{text} | {' '.join(details)}"
    self._output("ERR", text)
"""

# TODO make to logging for secont set_secr()
"""
    def set_module(self, module: any) -> None:
        if self._module is not None:
            self._module = module
        else:
            self._log.err(f"Detected second module set! Obj: {module}")
"""
# TODO protect against recursion 
# (logging of sending error is logged by sending, but the error and .... loop)
"""
    def __init__(self, secretary):
        self.secr = secretary
        self._is_logging = False # flag protection

    def _output(self, level, text, payload=None):
        if getattr(self, '_is_logging', False): return # flag protection
        try:
            self._is_logging = True
            # ... output logic ...
        finally:
            self._is_logging = False
"""