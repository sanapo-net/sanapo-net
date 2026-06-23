# Документация sanapo Framework (текущая версия)

Фреймворк для построения модульных асинхронных систем на Python. Кодовая база находится в одном проекте с программой. Импорты выполняются напрямую из пакета `sanapo`.

# 1. Быстрый старт

# 1.1 Минимальное приложение: один юнит, запуск и остановка

```python
from sanapo.kernel import Kernel
from sanapo.views import KernelUserView
from sanapo.enums import EnumRegistry, UnitType

reg = EnumRegistry.create_default(evt_cls=MyEvents, cmd_cls=MyCommands)

kernel = Kernel(reg, system_name="MySystem")
view = KernelUserView(kernel)

view.add_unit(
    name="worker",
    type=UnitType.TICKABLE,
    m_class=MyModule,
    m_params={"interval": 1.0}
)

view.start()

try:
    while view.is_running:
    view.step()
except KeyboardInterrupt:
    view.stop()
```

# 1.2 Система с тремя юнитами, добавленными разными способами

```python
reg = EnumRegistry.create_default(evt_cls=MyEvents, cmd_cls=MyCommands)
kernel = Kernel(reg, system_name="NodeA")
view = KernelUserView(kernel)

view.add_thread(name="main", type=ThreadType.EVENT_DRIVEN)
view.add_thread(name="io", type=ThreadType.TICKABLE, tct=0.02)
view.add_tier(layer_num=1, name="core")
view.add_tier(layer_num=2, name="peripheral")

view.add_unit(
    name="logger",
    type=UnitType.SIGMA,
    m_class=LoggerModule,
    thread_name="main",
    tier_name="core"
)

view.add_unit(
    name="sensor",
    type=UnitType.TICKABLE,
    m_class=SensorModule,
    m_params={"rate": 0.5},
    thread_name="io",
    tier_layer=1
)

view.add_units([
    {
    "name": "actuator",
    "type": UnitType.TICKABLE,
    "m_class": ActuatorModule,
    "thread_name": "io",
    "tier_name": "peripheral",
    "manifest": {"role": "output", "tags": ["motor"]}
    }
])

view.start()
```

# 1.3 Две системы с тремя юнитами по сети

**Система A**
```python
reg = EnumRegistry.create_default(evt_cls=MyEvents, cmd_cls=MyCommands)

kernel_a = Kernel(reg, system_name="Alpha")
kernel_a._cfg.NET_BEACON = True
kernel_a._cfg.TCP_PORT_DEFAULT = 50000
kernel_a._cfg.NET_PASSWORD = b"shared_key"
kernel_a._cfg.NET_PROJECT_TOKEN = b"PROJ00"
kernel_a._cfg.HOST = "0.0.0.0"

view_a = KernelUserView(kernel_a)

view_a.add_thread(name="main")
view_a.add_tier(name="app")

view_a.add_units([
    {"name": "alpha_logger", "type": UnitType.SIGMA, "m_class": LoggerModule,
    "thread_name": "main", "tier_name": "app", "manifest": {"role": "logger", "is_public": True}},
    {"name": "alpha_worker", "type": UnitType.TICKABLE, "m_class": WorkerModule,
    "thread_name": "main", "tier_name": "app", "manifest": {"role": "worker", "tags": ["fast"]}},
    {"name": "alpha_monitor", "type": UnitType.ZOMBIE, "m_class": MonitorModule,
    "thread_name": "main", "tier_name": "app", "manifest": {"role": "monitor", "is_public": True}},
])

view_a.start()
```

**Система B**
```python
reg = EnumRegistry.create_default(evt_cls=MyEvents, cmd_cls=MyCommands)

kernel_b = Kernel(reg, system_name="Beta")
kernel_b._cfg.NET_BEACON = True
kernel_b._cfg.TCP_PORT_DEFAULT = 50000
kernel_b._cfg.NET_PASSWORD = b"shared_key"
kernel_b._cfg.NET_PROJECT_TOKEN = b"PROJ00"
kernel_b._cfg.HOST = "0.0.0.0"

view_b = KernelUserView(kernel_b)

view_b.add_thread(name="main")
view_b.add_tier(name="app")

view_b.add_units([
    {"name": "beta_logger", "type": UnitType.SIGMA, "m_class": LoggerModule,
    "thread_name": "main", "tier_name": "app", "manifest": {"role": "logger", "is_public": True}},
    {"name": "beta_worker", "type": UnitType.TICKABLE, "m_class": WorkerModule,
    "thread_name": "main", "tier_name": "app", "manifest": {"role": "worker", "tags": ["slow"]}},
    {"name": "beta_commander", "type": UnitType.SIGMA, "m_class": CommanderModule,
    "thread_name": "main", "tier_name": "app", "manifest": {"role": "commander", "is_public": True}},
])

view_b.start()
```

**Пример взаимодействия в модуле Beta.CommanderModule (после on_net_ready):**
```python
class CommanderModule(BaseModule):
    def on_net_ready(self, system_name: str):
        if system_name == "Alpha":
            workers = self.v.get_remote_addrs_by_role("worker")
        for addr in workers:
            self.v.scr.send_cmd(
                recipient=addr,
                cmd_type=MyCommands.DO_JOB,
                cb=self.on_job_response,
                payload={"task": "analyze"},
                deadline_answ_dur=0.3,
                deadline_done_dur=2.0
            )

    def on_job_response(self, frame):
        if frame.rpt_type == RptType.DONE:
            self.v.log.inf(f"Job done by {frame.sender}, result: {frame.payload}")
        elif frame.rpt_type == RptType.CANT_DO:
            self.v.log.wrn(f"Job refused by {frame.sender}, reason: {frame.reason}")
        elif frame.rpt_type == RptType.EXECUTION_TIMEOUT:
            self.v.log.err(f"Job timeout from {frame.sender}")
```

# 2. Компоненты фреймворка

# 2.1 Потоки (Thread, ThreadManager)

Потоки — это группы юнитов, выполняемых последовательно в одном потоке ОС.

**Типы потоков (ThreadType):**
- **EVENT_DRIVEN** — поток спит, пока нет сообщений. Просыпается при появлении новых фреймов в очереди любого юнита. По умолчанию.
- **TICKABLE** — поток работает постоянно с заданным тактом (tct), не засыпает.

**Создание потока:**
```python
view.add_thread(
    name="unique_name",           # обязательный уникальный идентификатор
    type=ThreadType.EVENT_DRIVEN, # тип потока (по умолчанию EVENT_DRIVEN)
    tct=0.01,                     # время цикла в секундах (по умолчанию 0.005)
    tct_hiber=0.1,                # время цикла в гибернации (по умолчанию 0.05)
    join_margin=1.0               # запас времени при остановке потока
)
```

Если не создать ни одного потока вручную, система автоматически создаст поток `DEFAULT` при добавлении первого юнита без указания `thread_name`.

**Смена юнита между потоками:**
Напрямую невозможно. Нужно удалить юнит из одного потока и создать заново в другом через `del_unit` + `add_unit`.

# 2.2 Слои (Tier)

Слои управляют порядком запуска и остановки групп юнитов. Все юниты слоя стартуют одновременно, и система ждёт готовности всего слоя перед переходом к следующему.

**Создание слоя:**
```python
tier = view.add_tier(
    layer_num=1,          # числовой номер слоя (опционально, автоинкремент)
    name="business_logic" # строковое имя (опционально)
)
```

**Специальные имена:**
- `"LAST"` — получить последний существующий слой. Если слоёв нет — создаст новый.
- `"NEW_CREATE"` — принудительно создать новый слой.
- `None` или `"AUTO_CREATING"` — автоматический режим: если последний слой был создан автоматически — вернуть его, иначе создать новый.

# 2.3 Типы юнитов (UnitType)

- **TICKABLE** — на каждом тике вызывается и `step()` модуля, и обработка сообщений секретарём. Для активных модулей с вычислениями и коммуникацией.
- **SIGMA** — `step()` модуля НЕ вызывается, работает только секретарь. Модуль реагирует только на события/команды. Для сервисов-обработчиков.
- **ZOMBIE** — вызывается только `step()` модуля, секретарь не работает. Для фоновых задач без сетевого взаимодействия.
- **UTILITY** — не вызывается ни `step()`, ни секретарь. Пассивное хранилище данных или объект для ручного управления.

# 2.4 KernelUserView — публичный API ядра

**Жизненный цикл:**
```python
view.start()    # запуск системы (поднимает сеть, потоки, зажигает слои)
view.stop()     # остановка системы (гасит слои, потоки, сеть)
view.restart()  # перезапуск (stop + start)
view.step()     # один шаг главного цикла (если не используешь loop)
view.loop()     # блокирующий цикл (вызывает step пока is_running)
```

**Добавление юнита:**
```python
unit = view.add_unit(
    name="unit_name",            # уникальное имя юнита (строка)
    type=UnitType.TICKABLE,      # тип юнита
    m_class=MyModuleClass,       # класс модуля (не строка!)
    m_params={"key": "value"},   # параметры, передаваемые в конструктор модуля
    manifest={"role": "worker",  # значения манифеста (поверх define_manifest)
    "is_public": True, "tags": ["tag1", "tag2"]},
    thread_name="thread_name",   # имя потока (если нет — будет создан "DEFAULT")
    tier_name="tier_name",       # имя слоя
    tier_layer=1                 # или номер слоя
)
```
Возвращает `BaseUnit` или `None` при ошибке.

**Массовое добавление юнитов:**
```python
units = view.add_units([
    {
        "name": "unit1",
        "type": UnitType.SIGMA,
        "m_class": Module1,
        "thread_name": "main",
        "tier_name": "app"
    },
    {
        "name": "unit2",
        "type": UnitType.TICKABLE,
        "m_class": Module2,
        "m_params": {"debug": True},
        "thread_name": "io",
        "tier_layer": 2
    }
])
```
Возвращает словарь `{name: BaseUnit}`.

**Добавление потоков:**
```python
thread = view.add_thread(
    name="thread_name",
    type=ThreadType.EVENT_DRIVEN,
    tct=0.01,
    tct_hiber=0.1,
    join_margin=1.0
)
```
Возвращает `ThreadManager` или `None`.

```python
threads = view.add_threads([
    {"name": "main", "type": ThreadType.EVENT_DRIVEN},
    {"name": "io", "type": ThreadType.TICKABLE, "tct": 0.02}
])
```
Возвращает словарь `{name: ThreadManager}`.

**Добавление слоёв:**
```python
tier = view.add_tier(layer_num=1, name="init")
tier = view.add_tier(name="LAST")
```
Возвращает `Tier` или `None`.

```python
tiers = view.add_tiers([
    {"layer_num": 1, "name": "core"},
    {"layer_num": 2, "name": "peripheral"}
])
```
Возвращает словарь `{name: Tier}`.

**Удаление:**
```python
view.del_unit("unit_name")      # или передать Addr
view.del_thread("thread_name")
view.del_tier(layer_num=1)
view.del_tier(name="tier_name")
```
Возвращают `bool`. Поток удаляется только если пуст, слой — только если пуст.

**Универсальный метод setup:**
```python
result = view.setup(
    threads=[{"name": "main"}],
    tiers=[{"layer_num": 1, "name": "app"}],
    units=[{"name": "u1", "type": UnitType.TICKABLE, "m_class": MyMod}]
)
```
Возвращает `{"threads": {...}, "tiers": {...}, "units": {...}}`.

**Свойства:**
```python
view.log             # логгер ядра (Logger)
view.translate       # функция-переводчик: translate("some.key", param=val)
view.is_running      # bool — запущена ли система
view.is_shutdowning  # bool — в процессе остановки
view.is_rebooting    # bool — запланирован перезапуск
```

# 2.5 UnitModuleView — API, доступный модулю через self.v

**Краткие ссылки:**
```python
self.v.cfg   # Config — конфигурация системы
self.v.log   # Logger — логгер юнита
self.v.scr   # Secretary — секретарь для коммуникаций
self.v.addr  # Addr — собственный адрес юнита
```

**Управление состоянием:**
```python
self.v.started()  # вызвать в конце start(), переводит в WORKING
self.v.sleep()    # переводит в SLEEPING (секретарь не опрашивается, step не вызывается)
self.v.wakeup()   # возвращает из SLEEPING в WORKING
```

**Свойства (только чтение):**
```python
self.v.stat      # UnitStat — текущий статус (CREATED, STARTING, WORKING, SLEEPING, STOPPING, STOPPED, HALTED, ...)
self.v.type      # UnitType — тип юнита (TICKABLE, SIGMA, ZOMBIE, UTILITY)
self.v.manifest  # Manifest — паспорт юнита (version, role, is_public, is_persistent, tags)
```

**Таймауты (можно менять):**
```python
self.v.start_timeout = 1.0  # время на выполнение start() (по умолчанию 0.5 сек)
self.v.stop_timeout = 3.0   # время на выполнение stop() (по умолчанию 2.0 сек)
self.v.step_timeout = 0.05  # ожидаемая длительность одного step() (по умолчанию 0.05 сек)
```
При установке автоматически валидируются: не могут быть меньше чем 1.5 * max(step_timeout, THREAD_TCT_DEFAULT).

**Поиск адресов (локальные и удалённые):**
```python
addr = self.v.addr_by_str("unit_name")

systems = self.v.get_active_systems()
# Возвращает ("Alpha", "Beta")

remote_units = self.v.get_remote_addrs_by_sys("Alpha")
# Возвращает ["alpha_logger", "alpha_worker", "alpha_monitor"]

addrs = self.v.get_remote_addrs_by_role("logger")
# Возвращает [Addr("Alpha:alpha_logger"), Addr("Beta:beta_logger")]

addrs = self.v.get_remote_addrs_by_tag("fast")
# Возвращает адреса всех удалённых юнитов с тегом "fast"

```

# 2.6 BaseModule — написание модуля

```python
from sanapo.base_module import BaseModule

class MyModule(BaseModule):
    def start(self):
        self.v.scr.subscribe(self.on_cmd_ping, cmd=MyCommands.PING)
        self.v.started()
        return True

    def step(self):
        pass

    def stop(self):
        return True

    def on_net_ready(self, system_name: str):
        self.v.log.inf(f"Связь установлена с {system_name}")

    def on_net_disconnected(self, system_name: str):
        self.v.log.wrn(f"Связь потеряна с {system_name}")

    def define_manifest(self):
        return {
            "version": "1.0.0",
            "role": "worker",
            "is_public": True,
            "tags": ["fast", "critical"]
        }

    def on_cmd_ping(self, frame):
        self.v.scr.send_rpt(
            frame.sender, frame.cmd_id,
            RptType.DONE,
            payload={"pong": True}
        )
```

# 2.7 Secretary — API коммуникаций (self.v.scr)

# 2.7.1 Подписки

```python
self.v.scr.subscribe(callback, cmd=SomeEnum.CMD_TYPE)
self.v.scr.subscribe(callback, evt=SomeEnum.EVT_TYPE)

self.v.scr.unsubscribe(cmd=SomeEnum.CMD_TYPE)
self.v.scr.unsubscribe(evt=SomeEnum.EVT_TYPE)

self.v.scr.configure_subscriptions(
    events={
        MyEvents.ERROR: self.on_error,
        MyEvents.D  ATA_READY: self.on_data
    },
    commands={
        MyCommands.RESET: self.handle_reset,
        MyCommands.PING: self.handle_ping,
        MyCommands.SHUTDOWN: self.handle_shutdown
    }
)
```

# 2.7.2 Отправка событий

```python
success = self.v.scr.send_evt(
    MyEvents.TEMPERATURE_ALARM,
    payload={"sensor": "sensor_1", "temp": 95.0}
)
```
Возвращает `bool`. Событие получат все подписавшиеся модули (включая удалённые, если их манифест разрешает приём этого события).

# 2.7.3 Отправка команд с полным контролем

```python
cmd_id = self.v.scr.send_cmd(
    recipient=target_addr,                 # Addr получателя
    cmd_type=MyCommands.DO_TASK,           # тип команды (Enum)
    cb=self.default_handler,               # колбэк по умолчанию (для всех этапов)
    cb_done=self.on_success,               # когда получен DONE
    cb_canttodo=self.on_refuse,            # когда получен CANT_DO
    cb_timeout_answ=self.on_no_reaction,   # таймаут реакции (не было INTO_WORK/CANT_DO)
    cb_timeout_done=self.on_exec_timeout,  # таймаут выполнения (не было DONE)
    cb_time_ext_req=self.on_time_ext,      # когда исполнитель запросил продление
    deadline_answ_dur=0.2,                 # таймаут на подтверждение взятия в работу (сек)
    deadline_done_dur=2.0,                 # таймаут на полное выполнение (сек)
    payload={"key": "value"}               # произвольные данные
)
```
Возвращает `bool`. Идентификатор команды можно получить из `frame.cmd_id` в колбэках.

**Протокол команды:**
1: Командир отправляет `CMD`.
2: Исполнитель сразу шлёт `INTO_WORK` (или `CANT_DO`).
3: Исполнитель шлёт `DONE` (или `CANT_DO`) по завершении.
4: Если приближается дедлайн выполнения, исполнитель автоматически запрашивает `TIME_EXTENSION_REQUEST`. Командир автоматически продлевает `deadline_done` на `DEFAULT_TIME_EXTENSION` (0.2 сек).
5: Если `deadline_answ` истёк — вызывается `cb_timeout_answ`.
6: Если `deadline_done` истёк — вызывается `cb_timeout_done`.

# 2.7.4 Отправка отчётов (ответов на команды)

```python
self.v.scr.send_rpt(
    recipient=frame.sender,    # кому отвечаем
    cmd_id=frame.cmd_id,       # идентификатор команды
    rpt_type=RptType.DONE,     # тип отчёта
    payload={"result": "ok"},  # данные результата
    time_ext_req=None,         # запрос продления (только с TIME_EXTENSION_REQUEST)
    reason=None                # причина отказа (только с CANT_DO)
)
```

**Типы отчётов (RptType), которые ОТПРАВЛЯЕТ исполнитель:**

- **INTO_WORK** — отправляется автоматически секретарём исполнителя. Подтверждает, что команда взята в работу. Модуль помечается как занятый (если однопоточный). Командир сбрасывает `deadline_answ` в бесконечность.

- **DONE** — работа успешно завершена. Отправляется явно из модуля. У командира вызывается `cb_done`. Команда удаляется из отслеживания.

- **CANT_DO** — исполнитель не может выполнить команду. Нужно указать `reason`:
```python
RptReason.MODULE_BUSY      # модуль занят другой командой
RptReason.NOT_IMPLEMENTED  # нет обработчика для этого типа команды
RptReason.EXEC_EXCEPTION   # исключение при выполнении
```
У командира вызывается `cb_canttodo`.

- **TIME_EXTENSION_REQUEST** — запрос дополнительного времени. Отправляется автоматически секретарём, когда до дедлайна осталось меньше `DEADLINE_EXTENSION_THRESHOLD` (0.05 сек). У командира вызывается `cb_time_ext_req`.

**Типы отчётов, которые ГЕНЕРИРУЮТСЯ ЛОКАЛЬНО командиром:**

- **REACTION_TIMEOUT** — истёк `deadline_answ`, исполнитель не ответил ни `INTO_WORK`, ни `CANT_DO`. Вызывается `cb_timeout_answ`.

- **EXECUTION_TIMEOUT** — истёк `deadline_done`, работа не завершена. Вызывается `cb_timeout_done`.

Исполнитель НИКОГДА не отправляет `REACTION_TIMEOUT` и `EXECUTION_TIMEOUT` — они создаются локально секретарём командира.

# 2.7.5 Модификация дедлайна

```python
self.v.scr.modify_deadline(cmd_id, add_to_deadline=2.0)
```
Добавляет указанное количество секунд к дедлайну выполнения команды. Работает только для исходящих команд (командир).

# 2.7.6 Ручная установка многопоточности

```python
self.v.scr._has_thread_pool = True
```
Установить в `True`, если модуль использует собственные потоки. Тогда секретарь не будет блокировать приём новых команд флагом `_module_is_busy`.

# 2.7.7 Мульти-чтение входящих

```python
self.v.scr._multi_reading = True
```
Если `True`, за один вызов `_step()` секретарь читает до `UNIT_BUS_READ_LIMIT` сообщений (по умолчанию 20), а не одно.

# 2.7.8 Логирование длительности задач

```python
self.v.scr._log_task_duration_mode = True
```
Включает/выключает логирование времени выполнения каждого обработанного фрейма.

# 2.8 Logger — логирование (self.v.log)

```python
self.v.log.dbg("debug message with {var}", var=42)
self.v.log.inf("info message")
self.v.log.wrn("warning: {detail}", detail="low memory")
self.v.log.err("error occurred: {e}", e=exception)
self.v.log.crt("critical failure!")
```

**Уровни логирования (Logs):**
= `DBG` — отладочная информация
= `INF` — информационное сообщение
= `WRN` — предупреждение
= `ERR` — ошибка
= `CRT` — критическая ошибка

Логи пишутся в консоль и в файл `sanapo.log` (ротация: 5 МБ, 5 файлов). Путь к логам: `logs/`.

# 3. Настройка сети между системами

**Параметры Config, которые нужно выставить ДО start():**
```python
kernel._cfg.SYSTEM_NAME = "MyNode"               # уникальное имя системы
kernel._cfg.NET_BEACON = True                    # включить UDP-маяк
kernel._cfg.TCP_PORT_DEFAULT = 50000             # порт для TCP-соединений
kernel._cfg.UDP_PORT_DEFAULT = 50000             # порт для UDP-маяков
kernel._cfg.NET_PASSWORD = b"shared_secret"      # пароль для XOR-шифрования трафика
kernel._cfg.NET_PROJECT_TOKEN = b"PROJ00"        # токен проекта (фильтр чужих маяков)
kernel._cfg.HOST = "0.0.0.0"                     # интерфейс для прослушивания
kernel._cfg.NET_ALLOWED_IPS = ["192.168.1.0/24"] # список разрешённых IP (пустой = все)
kernel._cfg.NET_AUTO_CONNECT_BY_BEACON = True    # авто-подключение при обнаружении маяка
kernel._cfg.NET_MULTI_CONNECT_IN = True          # разрешить множественные входящие
kernel._cfg.NET_MULTI_CONNECT_OUT = True         # разрешить множественные исходящие
kernel._cfg.NET_PROJECT_MONO = True              # строгая проверка токена проекта
kernel._cfg.CONN_KEEP_ALIVE = True               # держать соединение активным
kernel._cfg.CONN_KEEP_ALIVE_MAX = 30.0           # простой до пинга (сек)
kernel._cfg.HANDSHAKE_TIMEOUT = 5.0              # таймаут рукопожатия
kernel._cfg.CONN_WAIT_ANSW_MAX = 3.0             # таймаут ожидания ответа при подключении
```

**Ручное подключение:**
```python
kernel._tcp_service.connect_to("192.168.1.10", 50000)
```

**Ручное отключение:**
```python
kernel._tcp_service.disconnect_addr(("192.168.1.10", 50000))
kernel._tcp_service.disconnect_all()
```

**Проверка соединения:**
```python
kernel._tcp_service.is_conn_alive("Beta")
kernel._tcp_service.is_conn_alive_addr(("192.168.1.10", 50000))
```

# 4. Конфигурация (основные параметры Config)

```python
from sanapo.config import Config

cfg = Config()
cfg.KERNEL_TCT = 0.002         # время цикла ядра
cfg.UNIT_START_TIMEOUT = 0.5   # таймаут старта юнита
cfg.UNIT_STOP_TIMEOUT = 2.0    # таймаут остановки юнита
cfg.UNIT_STEP_TIMEOUT = 0.05   # ожидаемая длительность шага
cfg.THREAD_TCT_DEFAULT = 0.005 # такт потока по умолчанию
cfg.THREAD_TCT_HIBERNATE_DEFAULT = 0.05 # такт потока в гибернации
cfg.THREAD_JOIN_MARGIN = 1.0   # запас при join потока
cfg.WATCHDOG_TCT = 1.0         # период проверки вотчдога
cfg.FW_SUTDOWN_TIMEOUT = 5.0   # общий таймаут остановки системы
cfg.BOOT_UI_MODE = "CUI"       # "CUI" (консоль) или "GUI" (окно)
```