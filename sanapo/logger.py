# core/logger.py
from __future__ import annotations
import json
import inspect
import logging
import threading
from enum import Enum
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import TYPE_CHECKING


from sanapo.addr import Addr
from sanapo.protocol import Frame
from sanapo.enums import Logs

if TYPE_CHECKING:
    from sanapo.config import Config
    from sanapo.translator import Translator

class Logger:
    _print_lock = threading.Lock()
    def __init__(self, addr: Addr | str, config: Config, translator: Translator) -> None:
        if isinstance(addr, Addr):
            self._addr = addr.unit
        elif isinstance(addr, str):
            self._addr = addr
        else:
            self._addr = "UNKNOWN"
        self._cfg = config
        self._translator: Translator = translator

        self.file_handler = RotatingFileHandler(
            "sanapo.log", maxBytes=5*1024*1024, backupCount=5, encoding='utf-8'
        )
        
    def _output(self, level: Logs, text: str, frame: Frame | None = None, mask: str = "",
                **kwargs) -> None:
         
        translated_text = self._translator.translate(text, **kwargs)      
        COLORS = {
            "crt": "\033[41m\033[37m", # white on red
            "err": "\033[91m",         # red
            "wrn": "\033[93m",         # yellow
            "inf": "\033[92m",         # green
            "dbg": "\033[94m",         # blue
            "end": "\033[0m"           # default
        }

        trc_str = ""
        if level in [Logs.CRT, Logs.ERR]:
            caller = inspect.stack()[3]
            filename = caller.filename.split('/')[-1]
            lineno = caller.lineno
            trc_str = f" ({filename}:{lineno})"

        time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        msk_str = self._read_mapping(frame, mask)
        log_str = f"{time_str} {level.value} {self._addr}: {translated_text}{trc_str}{msk_str}."

        # Console.
        if level in self._cfg.DEFAULT_LOG_FLAGS["console"]:
            c_bgn = COLORS.get(level.value, "")
            c_end = COLORS.get('end', "")
            with self._print_lock:
                print(c_bgn + log_str + c_end)
                
        # File (string).
        if level in self._cfg.DEFAULT_LOG_FLAGS["file"]:
            self.file_handler.emit(logging.LogRecord(
                self._addr, logging.INFO, "", 0, log_str, None, None
            ))

        # Message (json).
        if level in self._cfg.DEFAULT_LOG_FLAGS["message"] and frame:
            record = {"log": log_str, "raw": frame.to_dict()}
            path_file_jsonl = self._cfg.PATH_LOGS + "traffic.jsonl"
            with open(path_file_jsonl, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    
    def _read_mapping(self, frame: Frame, mask: str = "") -> list:
        """ Read mask and return formated msg """
        if not frame and mask:
            self._output(Logs.ERR, "Called loggings with mask, buh without frame")
            return "[err_get_text_by_mask]"
        if frame and mask:
            details = ""
            msg_type = ""
            if "M" in mask:
                sub_type = (frame.evt_type or frame.sys_type or frame.cmd_type or frame.rpt_type).value
                sub_type_str = sub_type if sub_type else "unknown"
                msg_type = f"{frame.msg_type}.{sub_type_str}"
            mapping = {
                "M": msg_type,
                "S": f"From:{frame.sender.name}",
                "R": f"Recipient:{frame.recipient}",
                "P": f"Payload: {frame.payload.get('text', 'N/A')}",
                "D": f"Deadline:{frame.deadline}",
                "T": f"Exit time:{frame.time_ext_req}",
                "i": f"ID:{frame.cmd_id}",
                "w": f"Reason:{frame.reason}",
            }
            for char in mask:
                details += "|" + mapping[char]
            return details
        else:
            return ""

    def err(self, text: str, frame: Frame | None = None, mask: str = "", **kwargs) -> None:
        self._output(Logs.ERR, text, frame, mask, **kwargs)

    def crt(self, text: str, frame: Frame | None = None, mask: str = "", **kwargs) -> None:
        self._output(Logs.CRT, text, frame, mask, **kwargs)

    def wrn(self, text: str, frame: Frame | None = None, mask: str = "", **kwargs) -> None:
        self._output(Logs.WRN, text, frame, mask, **kwargs)

    def inf(self, text: str, frame: Frame | None = None, mask: str = "", **kwargs) -> None:
        self._output(Logs.INF, text, frame, mask, **kwargs)

    def dbg(self, text: str, frame: Frame | None = None, mask: str = "", **kwargs) -> None:
        self._output(Logs.DBG, text, frame, mask, **kwargs)
