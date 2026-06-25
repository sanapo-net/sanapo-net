# sanapo Framework Documentation (current version)

Framework for building modular asynchronous systems in Python. The codebase is located in one project with the program. Imports are performed directly from the `sanapo` package.

# 1. Quick Start

# 1.1 Minimal application: one unit, startup and shutdown

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

# 1.2 System with three units added in different ways

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

# 1.3 Two systems with three units over the network

**System A**
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

**System B**
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

**Interaction example in Beta.CommanderModule (after on_net_ready):**
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
            .v.log.err(f"Job timeout from {frame.sender}")
```

# 2. Framework Components

# 2.1 Threads (Thread, ThreadManager)

Threads are groups of units executed sequentially in a single OS thread.

**Thread types (ThreadType):**
- **EVENT_DRIVEN** — thread sleeps while there are no messages. Wakes up when new frames appear in any unit's queue. Default.
- **TICKABLE** — thread runs constantly at a given tick rate (tct), does not sleep.

**Creating a thread:**
```python
view.add_thread(
    name="unique_name",           # mandatory unique identifier
    type=ThreadType.EVENT_DRIVEN, # thread type (default EVENT_DRIVEN)
    tct=0.01,                     # cycle time in seconds (default 0.005)
    tct_hiber=0.1,                # cycle time in hibernation (default 0.05)
    join_margin=1.0               # time margin when stopping the thread
)
```

If no threads are created manually, the system automatically creates a `DEFAULT` thread when adding the first unit without specifying `thread_name`.

**Moving a unit between threads:**
Not directly possible. The unit must be removed from one thread and recreated in another via `del_unit` + `add_unit`.

# 2.2 Tiers

Tiers manage the startup and shutdown order of unit groups. All units in a tier start simultaneously, and the system waits for the entire tier to be ready before moving to the next one.

**Creating a tier:**
```python
tier = view.add_tier(
    layer_num=1,          # numeric tier number (optional, auto-increment)
    name="business_logic" # string name (optional)
)
```

**Special names:**
- `"LAST"` — get the last existing tier. If no tiers exist — creates a new one.
- `"NEW_CREATE"` — force-create a new tier.
- `None` or `"AUTO_CREATING"` — automatic mode: if the last tier was created automatically — return it, otherwise create a new one.

# 2.3 Unit Types (UnitType)

- **TICKABLE** — on each tick, both the module's `step()` and the secretary's message processing are called. For active modules with computation and communication.
- **SIGMA** — the module's `step()` is NOT called, only the secretary works. The module reacts only to events/commands. For handler services.
- **ZOMBIE** — only the module's `step()` is called, the secretary does not work. For background tasks without network interaction.
- **UTILITY** — neither `step()` nor the secretary are called. Passive data storage or an object for manual control.

# 2.4 KernelUserView — public API of the kernel

**Lifecycle:**
```python
view.start()   # start the system (brings up network, threads, ignites tiers)
view.stop()    # stop the system (extinguishes tiers, threads, network)
view.restart() # restart (stop + start)
view.step()    # one step of the main loop (if not using loop)
view.loop()    # blocking loop (calls step while is_running)
```

**Adding a unit:**
```python
unit = view.add_unit(
    name="unit_name",           # unique unit name (string)
    type=UnitType.TICKABLE,     # unit type
    m_class=MyModuleClass,      # module class (not a string!)
    m_params={"key": "value"},  # parameters passed to the module constructor
    manifest={"role": "worker", # manifest values (on top of define_manifest)
    "is_public": True, "tags": ["tag1", "tag2"]},
    thread_name="thread_name",  # thread name (if absent — "DEFAULT" will be created)
    tier_name="tier_name",      # tier name
    tier_layer=1                # or tier number
)
```
Returns `BaseUnit` or `None` on error.

**Batch adding units:**
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
Returns a dictionary `{name: BaseUnit}`.

**Adding threads:**
```python
thread = view.add_thread(
    name="thread_name",
    type=ThreadType.EVENT_DRIVEN,
    tct=0.01,
    tct_hiber=0.1,
    join_margin=1.0
)
```
Returns `ThreadManager` or `None`.

```python
threads = view.add_threads([
    {"name": "main", "type": ThreadType.EVENT_DRIVEN},
    {"name": "io", "type": ThreadType.TICKABLE, "tct": 0.02}
])
```
Returns a dictionary `{name: ThreadManager}`.

**Adding tiers:**
```python
tier = view.add_tier(layer_num=1, name="init")
tier = view.add_tier(name="LAST")
```
Returns `Tier` or `None`.

```python
tiers = view.add_tiers([
    {"layer_num": 1, "name": "core"},
    {"layer_num": 2, "name": "peripheral"}
])
```
Returns a dictionary `{name: Tier}`.

**Deletion:**
```python
view.del_unit("unit_name") # or pass an Addr
view.del_thread("thread_name")
view.del_tier(layer_num=1)
view.del_tier(name="tier_name")
```
Return `bool`. A thread is only deleted if empty, a tier — only if empty.

**Universal setup method:**
```python
result = view.setup(
    threads=[{"name": "main"}],
    tiers=[{"layer_num": 1, "name": "app"}],
    units=[{"name": "u1", "type": UnitType.TICKABLE, "m_class": MyMod}]
)
```
Returns `{"threads": {...}, "tiers": {...}, "units": {...}}`.

**Properties:**
```python
view.log            # kernel logger (Logger)
view.translate      # translator function: translate("some.key", param=val)
view.is_running     # bool — whether the system is running
view.is_shutdowning # bool — in the process of stopping
view.is_rebooting   # bool — restart scheduled
```

# 2.5 UnitModuleView — API accessible to the module via self.v

**Quick references:**
```python
self.v.cfg  # Config — system configuration
self.v.log  # Logger — unit logger
self.v.scr  # Secretary — secretary for communications
self.v.addr # Addr — unit's own address
```

**State management:**
```python
self.v.started() # call at the end of start(), transitions to WORKING
self.v.sleep()   # transitions to SLEEPING (secretary is not polled, step is not called)
self.v.wakeup()  # returns from SLEEPING to WORKING
```

**Properties (read-only):**
```python
self.v.stat     # UnitStat — current status (CREATED, STARTING, WORKING, SLEEPING, STOPPING, STOPPED, HALTED, ...)
self.v.type     # UnitType — unit type (TICKABLE, SIGMA, ZOMBIE, UTILITY)
self.v.manifest # Manifest — unit passport (version, role, is_public, is_persistent, tags)
```

**Timeouts (can be changed):**
```python
self.v.start_timeout = 1.0 # time to execute start() (default 0.5 sec)
self.v.stop_timeout = 3.0  # time to execute stop() (default 2.0 sec)
self.v.step_timeout = 0.05 # expected duration of one step() (default 0.05 sec)
```
On setting, they are automatically validated: cannot be less than 1.5 * max(step_timeout, THREAD_TCT_DEFAULT).

**Address search (local and remote):**
```python
addr = self.v.addr_by_str("unit_name")

systems = self.v.get_active_systems()
# Returns ("Alpha", "Beta")

remote_units = self.v.get_remote_addrs_by_sys("Alpha")
# Returns ["alpha_logger", "alpha_worker", "alpha_monitor"]

addrs = self.v.get_remote_addrs_by_role("logger")
# Returns [Addr("Alpha:alpha_logger"), Addr("Beta:beta_logger")]

addrs = self.v.get_remote_addrs_by_tag("fast")
# Returns addresses of all remote units with the "fast" tag
```

# 2.6 BaseModule — writing a module

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
        self.v.log.inf(f"Connection established with {system_name}")

    def on_net_disconnected(self, system_name: str):
        self.v.log.wrn(f"Connection lost with {system_name}")

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

# 2.7 Secretary — communication API (self.v.scr)

# 2.7.1 Subscriptions

```python
self.v.scr.subscribe(callback, cmd=SomeEnum.CMD_TYPE)
self.v.scr.subscribe(callback, evt=SomeEnum.EVT_TYPE)

self.v.scr.unsubscribe(cmd=SomeEnum.CMD_TYPE)
self.v.scr.unsubscribe(evt=SomeEnum.EVT_TYPE)

self.v.scr.configure_subscriptions(
events={
    MyEvents.ERROR: self.on_error,
    MyEvents.DATA_READY: self.on_data
},
commands={
    MyCommands.RESET: self.handle_reset,
    MyCommands.PING: self.handle_ping,
    MyCommands.SHUTDOWN: self.handle_shutdown
}
)
```

# 2.7.2 Sending events

```python
success = self.v.scr.send_evt(
    MyEvents.TEMPERATURE_ALARM,
    payload={"sensor": "sensor_1", "temp": 95.0}
)
```
Returns `bool`. The event will be received by all subscribed modules (including remote ones, if their manifest allows receiving this event).

# 2.7.3 Sending commands with full control

```python
cmd_id = self.v.scr.send_cmd(
    recipient=target_addr,                # Addr of the recipient
    cmd_type=MyCommands.DO_TASK,          # command type (Enum)
    cb=self.default_handler,              # default callback (for all stages)
    cb_done=self.on_success,              # when DONE is received
    cb_canttodo=self.on_refuse,           # when CANT_DO is received
    cb_timeout_answ=self.on_no_reaction,  # reaction timeout (no INTO_WORK/CANT_DO)
    cb_timeout_done=self.on_exec_timeout, # execution timeout (no DONE)
    cb_time_ext_req=self.on_time_ext,     # when executor requested an extension
    deadline_answ_dur=0.2,                # timeout for work acceptance confirmation (sec)
    deadline_done_dur=2.0,                # timeout for full execution (sec)
    payload={"key": "value"}              # arbitrary data
)
```
Returns `bool`. The command identifier can be obtained from `frame.cmd_id` in callbacks.

**Command protocol:**
1: The commander sends `CMD`.
2: The executor immediately sends `INTO_WORK` (or `CANT_DO`).
3: The executor sends `DONE` (or `CANT_DO`) upon completion.
4: If the execution deadline is approaching, the executor automatically requests `TIME_EXTENSION_REQUEST`. The commander automatically extends `deadline_done` by `DEFAULT_TIME_EXTENSION` (0.2 sec).
5: If `deadline_answ` expires — `cb_timeout_answ` is called.
6: If `deadline_done` expires — `cb_timeout_done` is called.

# 2.7.4 Sending reports (responses to commands)

```python
self.v.scr.send_rpt(
    recipient=frame.sender,   # whom we are replying to
    cmd_id=frame.cmd_id,      # command identifier
    rpt_type=RptType.DONE,    # report type
    payload={"result": "ok"}, # result data
    time_ext_req=None,        # extension request (only with TIME_EXTENSION_REQUEST)
    reason=None               # refusal reason (only with CANT_DO)
)
```

**Report types (RptType) that the executor SENDS:**

- **INTO_WORK** — sent automatically by the executor's secretary. Confirms that the command has been accepted for execution. The module is marked as busy (if single-threaded). The commander resets `deadline_answ` to infinity.

- **DONE** — work successfully completed. Sent explicitly from the module. The commander's `cb_done` is called. The command is removed from tracking.

- **CANT_DO** — the executor cannot execute the command. Must specify `reason`:
```python
RptReason.MODULE_BUSY     # module is busy with another command
RptReason.NOT_IMPLEMENTED # no handler for this command type
RptReason.EXEC_EXCEPTION  # exception during execution
```
The commander's `cb_canttodo` is called.

- **TIME_EXTENSION_REQUEST** — request for additional time. Sent automatically by the secretary when less than `DEADLINE_EXTENSION_THRESHOLD` (0.05 sec) remains until the deadline. The commander's `cb_time_ext_req` is called.

**Report types GENERATED LOCALLY by the commander:**

- **REACTION_TIMEOUT** — `deadline_answ` expired, the executor responded with neither `INTO_WORK` nor `CANT_DO`. `cb_timeout_answ` is called.

- **EXECUTION_TIMEOUT** — `deadline_done` expired, work not completed. `cb_timeout_done` is called.

The executor NEVER sends `REACTION_TIMEOUT` and `EXECUTION_TIMEOUT` — they are created locally by the commander's secretary.

# 2.7.5 Deadline modification

```python
self.v.scr.modify_deadline(cmd_id, add_to_deadline=2.0)
```
Adds the specified number of seconds to the command execution deadline. Works only for outgoing commands (commander).

# 2.7.6 Manual multithreading setup

```python
self.v.scr._has_thread_pool = True
```
Set to `True` if the module uses its own threads. Then the secretary will not block the reception of new commands with the `_module_is_busy` flag.

# 2.7.7 Multi-reading of incoming messages

```python
self.v.scr._multi_reading = True
```
If `True`, in a single `_step()` call the secretary reads up to `UNIT_BUS_READ_LIMIT` messages (default 20), instead of just one.

# 2.7.8 Task duration logging

```python
self.v.scr._log_task_duration_mode = True
```
Enables/disables logging of the execution time of each processed frame.

# 2.8 Logger — logging (self.v.log)

```python
self.v.log.dbg("debug message with {var}", var=42)
self.v.log.inf("info message")
self.v.log.wrn("warning: {detail}", detail="low memory")
self.v.log.err("error occurred: {e}", e=exception)
self.v.log.crt("critical failure!")
```

**Log levels (Logs):**
- `DBG` — debug information
- `INF` — informational message
- `WRN` — warning
- `ERR` — error
- `CRT` — critical error

Logs are written to the console and to the file `sanapo.log` (rotation: 5 MB, 5 files). Log path: `logs/`.

# 3. Network Configuration Between Systems

**Config parameters that must be set BEFORE start():**
```python
kernel._cfg.SYSTEM_NAME = "MyNode"   # unique system name
kernel._cfg.NET_BEACON = True        # enable UDP beacon
kernel._cfg.TCP_PORT_DEFAULT = 50000 # port for TCP connections
kernel._cfg.UDP_PORT_DEFAULT = 50000 # port for UDP beacons
kernel._cfg.NET_PASSWORD = b"shared_secret"      # password for XOR traffic encryption
kernel._cfg.NET_PROJECT_TOKEN = b"PROJ00"        # project token (foreign beacon filter)
kernel._cfg.HOST = "0.0.0.0"                     # interface for listening
kernel._cfg.NET_ALLOWED_IPS = ["192.168.1.0/24"] # list of allowed IPs (empty = all)
kernel._cfg.NET_AUTO_CONNECT_BY_BEACON = True    # auto-connect on beacon detection
kernel._cfg.NET_MULTI_CONNECT_IN = True  # allow multiple incoming connections
kernel._cfg.NET_MULTI_CONNECT_OUT = True # allow multiple outgoing connections
kernel._cfg.NET_PROJECT_MONO = True      # strict project token verification
kernel._cfg.CONN_KEEP_ALIVE = True       # keep connection alive
kernel._cfg.CONN_KEEP_ALIVE_MAX = 30.0   # idle time before ping (sec)
kernel._cfg.HANDSHAKE_TIMEOUT = 5.0      # handshake timeout
kernel._cfg.CONN_WAIT_ANSW_MAX = 3.0     # response waiting timeout on connection
```

**Manual connection:**
```python
kernel._tcp_service.connect_to("192.168.1.10", 50000)
```

**Manual disconnection:**
```python
kernel._tcp_service.disconnect_addr(("192.168.1.10", 50000))
kernel._tcp_service.disconnect_all()
```

**Connection check:**
```python
kernel._tcp_service.is_conn_alive("Beta")
kernel._tcp_service.is_conn_alive_addr(("192.168.1.10", 50000))
```

# 4. Configuration (Main Config Parameters)

```python
from sanapo.config import Config

cfg = Config()
cfg.KERNEL_TCT = 0.002         # kernel cycle time
cfg.UNIT_START_TIMEOUT = 0.5   # unit start timeout
cfg.UNIT_STOP_TIMEOUT = 2.0    # unit stop timeout
cfg.UNIT_STEP_TIMEOUT = 0.05   # expected step duration
cfg.THREAD_TCT_DEFAULT = 0.005 # default thread tick
cfg.THREAD_TCT_HIBERNATE_DEFAULT = 0.05 # thread tick in hibernation
cfg.THREAD_JOIN_MARGIN = 1.0   # margin on thread join
cfg.WATCHDOG_TCT = 1.0         # watchdog check interval
cfg.FW_SUTDOWN_TIMEOUT = 5.0   # total system shutdown timeout
cfg.BOOT_UI_MODE = "CUI"       # "CUI" (console) or "GUI" (window)
```