# tests/stress_test/mock_module.py
import time
import asyncio

from core.enums import EvtType, CmdType, RptType

class MockModule:
    def __init__(self, name, messenger, iter_path, work_p, send_p, responders):
        self.addr = name
        self.messenger = messenger
        self.responders = responders
        self.logs = []
        self.bus_overcrowded_count = 0
        
        # Разбор 4D-роли: M/O, S/A, C/R, H/L
        self.is_multithread = name[0] == 'M'
        self.is_async = name[1] == 'A'
        self.is_commander = name[2] == 'C'
        self.is_heavy = name[3] == 'H'

        # Инициализация SeededGenerator из utils.py
        from tests.utils import SeededGenerator
        self.gen_work = SeededGenerator(f"{iter_path}/{name}/work.seed", **work_p)
        self.gen_send = SeededGenerator(f"{iter_path}/{name}/send.seed", **send_p)
        self.gen_target = SeededGenerator(f"{iter_path}/{name}/target.seed", 0, 5)

    def log(self, frame, s_time=None, r_time=None):
        self.logs.append({
            "payload": frame.payload,
            "sender": frame.sender,
            "recipient": frame.recipient or self.addr,
            "sent_time": s_time,
            "received_time": r_time,
            "msg_type": frame.msg_type
        })

    def on_receive(self, frame):
        self.log(frame, r_time=time.perf_counter())
        
        if frame.evt_type == EvtType.BUS_IS_OVERCROWDED:
            self.bus_overcrowded_count += 1
            
        if frame.evt_type == EvtType.BUFFER_NEW_DATA:
            self.execute_logic()
            
        if frame.cmd_type == CmdType.CMD_TEST:
            self.handle_command(frame)

    def handle_command(self, frame):
        # 1. Реакция "В работе"
        self.messenger.send_rpt(frame.sender, RptType.INTO_WORK, cmd_id=frame.cmd_id)
        # 2. Имитация выполнения (10мс фиксировано)
        time.sleep(0.01) 
        # 3. Финальный рапорт
        f = self.messenger.send_rpt(frame.sender, RptType.DONE, cmd_id=frame.cmd_id, payload=f"done_{frame.cmd_id}")
        self.log(f, s_time=time.perf_counter())

    def execute_logic(self):
        # Имитация внутренней нагрузки
        delay = self.gen_work.next_ms()
        if not self.is_heavy: delay /= 5.0
        time.sleep(delay / 1000.0)

        # Шлем фоновое событие
        f_evt = self.messenger.send_evt(EvtType.EVT_TEST, payload=f"{self.addr}_evt_{time.time()}")
        self.log(f_evt, s_time=time.perf_counter())

        # Если Командир — шлем приказ
        if self.is_commander:
            target = self.responders[int(self.gen_target.next_ms() % len(self.responders))]
            f_cmd = self.messenger.send_cmd(
                target, CmdType.CMD_TEST, payload=f"cmd_{self.addr}",
                cb_done=lambda d: None, 
                cb_timeout_answ=lambda d: None, 
                cb_timeout_done=lambda d: None
            )
            self.log(f_cmd, s_time=time.perf_counter())
