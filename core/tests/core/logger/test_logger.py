# core/tests/core/logger/test_logger.py

from core.enums import Addr, MsgType, EvtType, CmdType, SysType, RptType
from core.protocol import Frame
from core.tests.core.logger.mock_secretary import MockSecretary
from core.logger import Logger
from core.config import Config

secr = MockSecretary(Addr.KERNEL, "test")
logger = Logger(Config)

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
# Again set logger protection test
cocknballs = 0

for cocknballs in range(0, 2):
    if cocknballs == 1:
        logger = Logger(Config, secr)
    logger.wrn("Im a warning", frame, "MSRDTPtescriw")
    logger.info("Just information", frame, "MSRDPtTescriw")
    logger.crit("im wanna eat some shit", frame, "MSRDPtTescriw")
    logger.err("Im error, bro", frame, "MSRDPtTescriw")
    logger.debug("Debugging yaaaa", frame, "MSRDPtTescriw")


