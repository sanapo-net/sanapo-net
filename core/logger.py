# core/logger.py
from __future__ import annotations

import datetime
import logging

from core.enums import EvtType, Addr
from core.protocol import Frame

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from core.secretary import Secretary
    from core.config import Config

class Logger:
    def __init__(self, addr: Addr, config: Config, secr: Secretary | None = None):
        # TODO Check in future: Recursion protection if will be some problems in Kernel and LoggerApp
        self.secr = secr
        self.addr = addr
        self.cfg = config
        logging.basicConfig(level=logging.DEBUG, force=True, format='%(levelname)s:%(message)s')

    def _get_time(self):
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

    def _output(self, level: EvtType, text: str, frame: Frame | None = None, mask: str = ""):
        # Default color (white) for formated msg
        default_color = "\033[0m"

        # Variables that need to get by same key | Color/logging level
        output_vars = {
            EvtType.ERR: ["\033[31m", logging.error],
            EvtType.CRIT: ["\033[31m", logging.critical],
            EvtType.WRN: ["\033[33m", logging.warning],
            EvtType.MSG: ["\033[0m", logging.info],
            EvtType.LOG: ["\033[90m", logging.debug],
        }

        time_str = self._get_time()
        
        self.addr if self.addr else "UNKNOWN"
        logging.info(f"Address name:{self.addr}")
        formatted_msg = ""
        if frame and not mask:
            formatted_msg = f"[{time_str}] [{level}] [{self.addr}]: {text}."
            bus_payload = {"frame": frame}
            if frame.payload:
                bus_payload.update(frame.payload)
        elif frame and mask:
            details = self._read_mapping(frame, mask)
            if details:
                text = f"{text} | {' '.join(details)}"
            formatted_msg = f"[{time_str}] [{level}] [{self.addr}]: {text}."
        elif not frame and mask:
            logging.error("Frame is None")
        else:
            bus_payload = {"text": f"{text} | {level} | {time_str} | {self.addr}"}




        if level in self.cfg.DEFAULT_LOG_FLAGS["console"]:
            output_vars[level][1](f"{output_vars[level][0]} {formatted_msg}.{default_color}")
        if level in self.cfg.DEFAULT_LOG_FLAGS["file"]:
            with open("system.log", "a", encoding="utf-8") as f:
                f.write(formatted_msg + "\n")
        if level in self.cfg.DEFAULT_LOG_FLAGS["message"] and level in EvtType and self.secr:
            bus_payload = {"text": frame.payload, "frame": frame}

            if frame.payload:
                bus_payload.update(frame.payload)
            try:
                self.secr._log_push(evt_type=level, payload=bus_payload)
            except Exception:
                pass

    # ---- Log executing ----
    
    def _read_mapping(self, frame: Frame, mask: str = "") -> list:
        """ Read mask and return formated msg """
        details = []
        mapping = {
            "M": f"{frame.msg_type} | ",
            "S": f"From:{frame.sender.name} |",
            "R": f"Recipient:{frame.recipient} | ",
            "P": f"Payload:{frame.payload['text'] if (frame.payload) else 'N/А'} |",
            "D": f"Deadline:{frame.deadline} |",
            "T": f"Exit time:{frame.time_ext_req} |",
            "t": f"{frame.evt_type or frame.sys_type or frame.cmd_type or frame.rpt_type} |",
            "e": f"Evt:{frame.evt_type.value if frame.evt_type else 'N/A'} |",
            "s": f"Sys:{frame.sys_type.value if frame.sys_type else 'N/A'} |",
            "c": f"Cmd:{frame.cmd_type.value if frame.cmd_type else 'N/A'} |",
            "r": f"Rtp:{frame.rpt_type.value if frame.rpt_type else 'N/A'} |",
            "i": f"ID:{frame.cmd_id} |",
            "w": f"Reason:{frame.reason} |",
        }
        for char in mask:
            mapping.get(char)
            details.append(mapping[char])
        return details

    def err(self, text: str, frame: Frame | None = None, mask: str = "") -> None:
        self._output(level=EvtType.ERR, text=text, frame=frame, mask=mask)

    def crt(self, text: str, frame: Frame | None = None, mask: str = "") -> None:
        self._output(EvtType.CRIT, text=text, frame=frame, mask=mask)

    def wrn(self, text: str, frame: Frame | None = None, mask: str = "") -> None:
        self._output(EvtType.WRN, text=text, frame=frame, mask=mask)

    def inf(self, text: str, frame: Frame | None = None, mask: str = "") -> None:
        self._output(EvtType.MSG, text=text, frame=frame, mask=mask)

    def dbg(self, text: str, frame: Frame | None = None, mask: str = "") -> None:
        self._output(EvtType.LOG, text=text, frame=frame, mask=mask)
