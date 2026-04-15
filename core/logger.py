# core/logger.py
# This is draft of core/logger
# TODO move to config ?
# TODO for modules without secr, comfortable params
import datetime
import logging

from core.enums import EvtType, Logs
from core.secretary import Secretary
from core.protocol import Frame

class Logger:
    def __init__(self, secr: Secretary, console: bool = True, bus: bool = True):
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

    def set_secr(self, secr: Secretary) -> None:
        if not hasattr(self, "_secr") and isinstance(secr, Secretary):
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

    def err(self, text: str, frame: Frame | None = None, mask: str = "") -> None:
        if frame and mask:
            details = self._read_mapping(frame, mask)

            if details:
                text = f"{text} | {' '.join(details)}"
        self._output("ERR", text)

    def crit(self, text: str, frame: Frame | None = None, mask: str = "") -> None:
        if frame and mask:
            details = self._read_mapping(frame, mask)

            if details:
                text = f"{text} | {' '.join(details)}"
        self._output("CRITICAL", text)

    def wrn(self, text: str, frame: Frame | None = None, mask: str = "") -> None:
        if frame and mask:
            details = self._read_mapping(frame, mask)

            if details:
                text = f"{text} | {' '.join(details)}"
        self._output("WRN", text)

    def info(self, text: str, frame: Frame | None = None, mask: str = "") -> None:
        if frame and mask:
            details = self._read_mapping(frame, mask)

            if details:
                text = f"{text} | {' '.join(details)}"
        self._output("INFO", text)

    def debug(self, text: str, frame: Frame | None = None, mask: str = "") -> None:
        if frame and mask:
            details = self._read_mapping(frame, mask)

            if details:
                text = f"{text} | {' '.join(details)}"
        self._output("DEBUG", text)

# Example how use into module
# self.log = SmartLogger(self.secretary)
# TODO dont remember: logger must can work in "without secretary mode"