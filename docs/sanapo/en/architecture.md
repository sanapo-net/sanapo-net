# sanapo Framework Architecture Description


## Contents:

- [General Features](#general-features) — brief description of the concept, units, kernel, networking, and lifecycle.
- [Addresses](#addresses) — structure of module address (system:name) and its role.
- [Unit](#unit) — isolated computing unit with types, states, and pseudo-cycle.
- [Module](#module) — user code (inherits BaseModule), entry points start/stop.
- [Secretary](#secretary) — communication interface: commands, events, reports, subscriptions.
- [Logger](#logger) — logging to console/file with levels and built-in translator.
- [Threads](#threads) — thread management, types, runner agent, hibernation.
- [Tiers](#tiers) — groups of units that start and stop together in order.
- [Kernel](#kernel) — main orchestrator, registries, lifecycle, persistence, network callbacks.
- [Boot Master](#boot-master) — controls startup and shutdown by tiers with visualization.
- [Watchdog](#watchdog) — monitors stuck threads and performs forced reset.
- [Message Broker](#message-broker) — message routing, local and remote routes.
- [Transport Adapters](#transport-adapters) — delivery abstractions (queue, TCP and others).
- [Protocols](#protocols) — Frame structure, serialization, validation, network specifics.
- [Manifest](#manifest) — unit passport (role, tags, publicity, version).
- [UDP Services: Beacon and Listener](#udpservicesservicesbeaconandandlistener) — LAN discovery via UDP beacons.
- [TCP Service](#tcp-service) — reliable connections between systems, handshake, encryption.
- [User Interfaces](#user-interfaces) — facades for application programmers (KernelUserView, UnitModuleView).
- [Miscellaneous](#miscellaneous) — additional modules, many questionable for v2:
    - [Module Config](#module-config) — framework settings.
    - [Module Enums](#module-enums) — named constants for type safety.
    - [Class EnumRegistry](#class-enumregistry) — registration of user Enums for serialization.
    - [Boot Visualization](#boot-visualization) — GUI/CUIprogressbars(untested).
    - [Class BriefEnumMixin](#class-briefenummixin) — unused, simplifieslogs.
    - [Class Translator](#class-translator) — localization(questionable).
    - [E-mail Transport and Service](#e-mail-transport-and-service) — unused, proof of concept.
    - [Restrictive Interfaces (views)](#restrictive-interfaces-views) — internal View classes (questionable).


## General Features
The sanapo framework is built around the idea of isolated computing units — units that communicate through a thread-safe message bus. Each unit lives inside a thread (one of many), inside a tier (one of many), and knows nothing about the others directly — only through addresses and messages. The Kernel orchestrates the creation, startup, shutdown, and destruction of all components. The application programmer writes only modules (inheriting from BaseModule) and configures the system through KernelUserView. Everything else is the framework's responsibility.

The system can be either standalone or networked with other sanapo systems via TCP (on top of UDP beacons for discovery). Network connections are established automatically when the project token and password match. Modules can search for remote units by roles and tags, sending them commands and events just like local ones.

System lifecycle: configuration → boot (BootMaster) → operation (Kernel.step loop) → shutdown (BootMaster.shutdown) → completion.

[Contents](#contents)


## Addresses
_(class `Addr`)_

For each module to be able to send and receive messages to other modules — they need addresses.
A module's address consists of two parts: the system name and its own name. As a string, it looks like two strings joined by a colon.
Modules written by application programmers must have their own names; the instance of a program built on the sanapo framework also has a name. An address is formed from these two names. It is implemented as an object and can be output and parsed as a string.
A valid address applies only to modules that have their own secretary, with a couple of exceptions inside the framework.

[Contents](#contents)


## Unit
_(class `BaseUnit`)_

This is the target entity in a program based on the sanapo framework. The unit's purpose: to provide the necessary environment and services for a single module.

_module_ — here, an instance of a class written by the application developer and inherited from `BaseModule`.

A unit can contain a secretary (`Secretary`), a logger (`Logger`), a manifest (`Manifest`), the class written by the application programmer inherited from [`BaseModule`](#module), and an instance of that class.

_pseudocycle_ — here, an evolutionarily reduced internal loop inside the unit, implemented as the `step` method, which is constantly called in turn by the [manager's agent](#threads) of the thread in which the unit resides.

There are 4 unit types:
- **`TICKABLE`** — the most active unit type. Has a secretary, sends and receives messages, has a logger, has its own pseudocycle.
- **`ZOMBIE`** — a unit type that can send and receive messages but does not have its own pseudocycle; it is essentially managed by the secretary — the secretary calls the unit's callbacks when corresponding messages arrive.
- **`SIGMA`** — an independent unit, has no secretary, neither receives nor sends messages, has its own working pseudocycle, has a logger.
- **`UTILITY`** — the simplest unit type, has no secretary, has no pseudocycle. It differs from an object not included in the sanapo framework kernel in that it has its own named logger and access to infrastructure. It is intended for calling methods directly via reference and other atomic operations, or for acting as a companion to another unit in the same thread.

Units are created only inside the [`Kernel`](#kernel) with registration in the [`MessageBroker`](#message-broker) through methods available to the application programmer via `KernelUserView`.

A unit has multiple operating modes from the `UnitStat` class, from `CREATING` to `DESTROYED`. In `SLEEPING` mode, the pseudocycle of units that have a pseudocycle does not execute; for example, in `SLEEPING` mode, a `TICKABLE` unit operates similarly to a `SIGMA` unit in `WORKING` mode. During sleep, shutdown, or when stopped, the secretary does not process incoming messages.

A unit has an assigned maximum execution time for one pass of the `step` method, which the unit can change. If a unit executes the `step` method longer than the specified time, it will be noticed by the [watchdog](#watchdog) service, after which measures will be applied.

A unit also has assigned durations for executing the `start` and `stop` methods; exceeding these timeouts also results in measures being applied.

A unit stores the class written by the application programmer and the parameters passed by them when adding the unit through `KernelUserView` methods.

During its initialization, the unit creates an instance of the stored class (in context: `module`) with the stored parameters. It can also recreate such an instance.

The unit intermediary manipulates the module and the [secretary](#secretary): calls the `step` methods of both according to the unit type and state map, calls the module's startup and shutdown methods, callbacks for connection or disconnection of other network systems based on the sanapo framework, creates, destroys, and recreates the module.

A unit can mutate — change its type on the fly; a special method exists for this.

[Contents](#contents)


## Module
_(class `BaseModule`)_

The user works with the sanapo framework by writing classes whose instances are then added to the system. The module is where the application programmer's code logic meets the sanapo framework logic.

All added objects must be of classes inherited from the base class `BaseUnit`.

An instance of this class receives methods and some properties of other framework objects. Primarily these are `UnitModuleView`, `BaseUnit`, `Manifest`, `Logger`, `Secretary`. Access to the latter three depends on the specified type of the [unit](#unit) being created when it is added.

The module must have `start` and `stop` methods as mandatory. This is where the module's startup logic is described, for example connecting to files, networks, loading data from a database, calculations, and so on.

The module can subscribe to events and commands within the system and beyond via the secretary.
In the module, one can change the maximum durations for executing the `start`, `stop`, and `step` methods, change the module's manifest data, and more.

[Contents](#contents)


## Secretary
_(class `Secretary`)_

The secretary is the interface for communication between units.

Units can send commands, events, reports, and system messages.

_callback_ — here, a method that is called by the secretary according to the correspondence table **message-type -- method** of the module or unit, passing the message as the sole parameter.

When sending an event, the unit simply specifies the event type from a list created during the development of a program built on the sanapo framework, specifies the payload as a dictionary, and sends this message, which goes to the [message broker](#message-broker).

When sending a report, the unit specifies the recipient's address (which must match the address of the commander unit, taken from the sender field of the message containing the command), the command ID — which is taken from the message containing the command, the report type, and the reason in case of problems.

When sending a command, the commander unit specifies the addressee (executor unit), the command type, the payload, and callbacks. A common callback can be specified for all, or individual callbacks for each report type, for cases of refusal to execute or missed execution deadlines for example, with a common callback for the rest. All callbacks are called with a single parameter — the body of the report message. The command ID is generated automatically by the secretary.
The commander unit can also specify command execution deadlines and command reaction deadlines in the command, and extend deadlines independently or upon request from the executor unit.

Upon receiving a message (any: system, report, command, event), the unit's secretary checks whether the unit has such a message type in its subscriptions (the correspondence table **message-type -- method**); if so — it calls that method, passing the message to it.

If the secretary has no subscription for such a message — an error or warning is logged. If it is a report, then the history of sent commands is also checked to see if a command with such an ID was sent; if so — it is a report for a command that is no longer relevant, the report is ignored, a warning is written to the log; if no such command existed — an error is written to the log.

Reports for irrelevant commands do not reach the unit.

All commands must receive a response in the form of a report, even if the command was not executed.
Before starting work after receiving a command, so that the commander unit understands it has been heard, the executor unit must send a report that it has accepted the command and is starting work. This is a report of type `INTO_WORK`, and the executor unit's secretary sends such a report to the commander unit after reading the message with the command **automatically**, after which it calls the unit's method necessary for execution.

If the executor unit receives a message with a command while the unit has already started work on a previous command and has not yet sent a `DONE` report, the secretary sends a `CANT_DO` report with reason `MODULE_BUSY` to the commander unit **automatically**; the executor unit does not even know that such a command came to it. Sending the command again, if necessary, is the commander's concern, but the commander knows that the unit is busy.

If the executor unit's module is written by the application programmer for multi-threaded execution — the module sets the corresponding flag in the secretary during its startup (specified by the application programmer in the `start` method). If this flag is set, the secretary does not automatically send a busy report to the commander unit.

If the executor unit receives a message with an unknown command — the secretary sends a `CANT_DO` report with reason `NOT_IMPLEMENTED` **automatically**.

The unit is automatically subscribed to system messages by the secretary during initialization.
The unit is forcibly subscribed by the secretary to manipulations with this unit: shutdown, startup, sleep, work, recreation, destruction, mutation, as well as the most important network events: system readiness to work with a new network system and connection loss with a system.

All message transmissions and callbacks are thread-safe.

[Contents](#contents)


## Logger
_(class `Logger`)_

Writes logs to the console and to a file. The level for console output and file writing is defined separately in the configuration.
In framework version 2, individual logger configuration for each object is planned.
The logger has a built-in [l18n translator](#translator-class)

[Contents](#contents)


## Threads
_(class `ThreadManager`)_

One of the features that significantly lowers the entry barrier for application programmers to start creating multi-threaded applications based on the sanapo framework.
Since communication between units is thread-safe, modules can be placed in different threads. For this, the sanapo framework provides a service for "placing" units in different threads. The application programmer only needs to specify the thread name when calling the thread addition method on the kernel's user interface `KernelUserView`. Later, when adding a unit, the user-programmer only needs to specify the name of the thread in which they want to place the unit. The unit will run in a separate thread identifiable by name.

A user can add any number of units to a single thread. There can be any number of threads. Limitations may be related to the operating system of the computing machine.

A unit can be created without specifying a thread at all — such a unit will be placed in a common thread for those units that were not assigned a thread name.

Threads have their own states. States are created for controlling its operation: CREATED, STARTING, WORKING, RELOADING, JOINING, JOINED, HALTED.
Primarily, this necessity is driven by the functionality described in the [boot master](#boot-master) and the [watchdog](#watchdog).

A thread has a runner agent — a loop in a separate operating system thread that calls the `step` methods of its working units in turn. Units, depending on their type and state, call the `step` methods of modules and secretaries.
The runner agent has its own thread-safe message queue through which the manager communicates with the runner agent. Through this queue, the manager issues commands for manipulations regarding units/modules.

Threads have three types:
- `TICKABLE` — common for all unit types
- `EVENT_DRIVEN` — a club for `ZOMBIE` and `UTILITY`
- `ONLY_EVENT_DRIVEN` — a closed club for `ZOMBIE` and `UTILITY`

A `TICKABLE` thread spins its loop endlessly, calling `step` on all units where possible, in turn.

An `EVENT_DRIVEN` thread sleeps while it contains only `ZOMBIE` and `UTILITY` type units. When the loop is not spinning, the corresponding operating system thread does not waste processor time on computations and interrupts. When a unit of a different type enters the thread — the thread starts behaving like a `TICKABLE` thread, first writing a warning to the log that a unit of a different type has entered a thread intended for `ZOMBIE` and `UTILITY`. If the "alien" unit is destroyed or recognized as dead by the sanapo framework (in case of its hang), or is removed from the thread by end-user actions or logic embedded by the application programmer — then such a thread will resume operating in its normal mode — without a loop, but upon message arrival to units, performing a one-time job to enable message processing and callback execution. Processor idle is ensured through `Event` objects.

An `ONLY_EVENT_DRIVEN` thread behaves like `EVENT_DRIVEN` when it contains only `ZOMBIE` and `UTILITY` type units and does not admit units of other types. When attempting to add units of other types — an error is logged and the add action is ignored.

Threads have a hibernation mode — if no payload has been executed for a config-defined time interval, the thread enters hibernation mode if it is currently operating as `TICKABLE`: the loop slows down to the tick level defined in the configuration.
Payload activity is determined by the runner agent reading the boolean flags (`bool`) returned by the units' `step` methods, which in turn receive this flag from the module's `step` method or set it to `True` themselves, depending on the currently performed work and processes.

A thread can be stopped (`join` operation), started, or reloaded by the [watchdog](#watchdog) and the [boot master](#boot-master).

[Contents](#contents)


## Tiers
_(class `Tier`)_

A tier is a group of units that start and stop together. Tiers are arranged in an order defined by a numerical number (layer_num). The [BootMaster](#boot-master) ignites tiers sequentially: first tier 1, then tier 2, and so on.
Internally, a tier starts all its units, and the units start their modules. Until all units of a tier transition to WORKING (or fall off by timeout), the next tier will not begin startup.

**In case of problems during startup**

    If during tier startup some module hangs (unit startup takes too long), the tier calls the module recreation method. In the main thread, the tier sets the corresponding flag on the unit through a simultaneous function call, while the shutdown, creation, and startup process is executed in the kernel's thread.

    If module recreation does not happen or it hangs, and module recreation does not help — the tier calls the kernel's method to create a new unit in the system.

    If module and unit recreation did not help and the problem persists — the tier attempts to restart the thread in which the unit runs: if there are no already successfully started units in the thread — a thread restart occurs.

During shutdown, the order is reversed: first the last tier is extinguished, then the second-to-last, and so on to the first.

A tier has states:
- `CREATED` — tier is created but not yet started
- `STARTING` — tier's units are starting, the tier awaits their readiness
- `WORKING` — all tier's units are working
- `STOPPING` — tier's units are stopping
- `STOPPED` — tier is extinguished

A tier tracks the startup/shutdown progress of its units. If some unit does not fit within the startup or shutdown timeout, the tier registers the problem but does not block the process — the problematic unit is marked as HALTED, and the tier moves on. The boot master may decide to restart the tier if it is marked as "flaky" (chronically unstable).

A tier does not manage threads directly — it works with units, and units are already distributed across threads. The same thread can contain units from different tiers.

A tier can be created manually (specifying a name or number or both) or automatically (when adding a unit to a non-existent tier). Automatically created tiers have the flag `autocreated-True` and can be reused for subsequent units without explicitly specifying a tier (via the LAST/NEW_CREATE/AUTO_CREATING mechanism).

[Contents](#contents)


## Kernel
_(class `Kernel`)_

The kernel is the central orchestrator of the entire system. This is the first object the application programmer creates. The kernel owns all registries: units, threads, tiers, as well as all infrastructure services.

**What the kernel creates during initialization:**
- Configuration (`Config`)
- Its own address (`Addr`) — a special kernel address, like `"SystemName:KERNEL"`
- Logger (`Logger`)
- Translator (`Translator`)
- WatchDog (`WatchDog`)
- BootMaster (`BootMaster`)
- MessageBroker (`MessageBroker`)
- Its own secretary (`KernelSecretary`)
- Transport for broker communication (`QueueAdapterTransport`)

Network services (`TcpService`, `UdpBeacon`, `UdpListener`) are created at system startup, not during kernel initialization.

**Kernel lifecycle:**
- `init` — creation of all services except network ones
- `setup` / `add_unit` / `add_thread` / `add_tier` — system configuration by the user-programmer
- `start` — network startup, then handover to the boot master (`BootMaster.boot`)
- `loop` / `step` — main loop: broker, secretary, tiers, boot master, watchdog
- `stop` — network shutdown, then handover to the boot master (`BootMaster.shutdown`)
- `on_stopped` — finalization, call of user callback

**Unit management (internal):**
The kernel does not just store units — it manages their full lifecycle:
- `_build_unit` — factory: creates Addr, Logger, Secretary, BaseUnit, Manifest and links them together
- `_destroy_unit` — calls `unit.destroy()` and removes the address from the broker
- `rebuild_unit` — recreates a unit from its recipe (used by `Tier` when problems occur)

**Consistency (persistence):**
The kernel can save and load the system state (recipes of units, threads, tiers) to JSON files. Saving occurs with a delay (`SYS_CONSIST_DELAY` - 5 sec) after the last change, so as not to hit the disk on every unit addition. When loading, module classes are resurrected from strings via importlib.

**Network callbacks:**
The kernel handles remote system connection and disconnection events:
- On connection — distributes remote unit manifests across the broker, sends out local public manifests
- On disconnection — cleans the address book and manifests of the remote system, notifies all local units via `broadcast_sys_message`(`NET_DISCONNECTED`)

**Watchdog and stability:**
The kernel provides the watchdog with `get_managers` (list of all `ThreadManager`) and `on_thread_stuck` (nuclear reset of a hung thread) methods. When a hang is detected, the thread is forcibly reloaded with all its units.

[Contents](#contents)


## Boot Master
_(class `BootMaster`)_

The boot master manages the system startup and shutdown process by tiers. It operates as a finite state machine with three modes:
- `BootTask.NONE` — idle
- `BootTask.BOOT` — system boot (startup)
- `BootTask.SHUTDOWN` — system shutdown

**Boot process (BOOT):**
1: The boot master sorts tiers by layer_num.
2: Starting from the first tier, calls `tier.start()` and waits until all tier units transition to WORKING (or fall out by timeout).
3: If a tier finishes with an error (not all units started), the boot master can:
- Restart the tier (until attempts are exhausted)
- Mark the tier as "flaky" and continue
- Halt the system (if the global attempt limit SYSTEM_STUCK_REBOOT_MAX is exceeded)
4: After successful startup of all tiers, calls `on_started` on the kernel (which in turn calls the user callback).

**Shutdown process (SHUTDOWN):**
1: Tiers are extinguished in reverse order (from last to first).
2: For each tier, `tier.stop()` is called; the boot master waits for all units to stop.
3: After all tiers stop, calls `on_stopped` on the kernel.

**Visualization:**
The boot master has two progress display modes:
- `CUI` — console progress bar
- `GUI` — Tkinter window with two progress bars (global and per-tier)
The mode is determined by the `BOOT_UI_MODE` config. The application programmer does not need to worry about visualization — it works automatically.

**Error management:**
If a tier cannot start, the boot master:
1: Logs the problem
2: Increments the tier's attempt counter
3: If attempts are exhausted — increments the global attempt counter
4: If the global counter exceeds the limit — calls `restart()` of the entire system

[Contents](#contents)


## Watchdog
_(class `WatchDog`)_

The WatchDog is a thread health monitor. It does not monitor each unit individually but checks whether entire threads have hung.

**Operating principle:**
1: WatchDog stores the last step time (last_step) for each thread known to it.
2: When `inspect()` is called (every kernel tick), it checks all threads via `kernel.get_managers()`.
3: If a thread has units and is not in JOINING/JOINED/HALTED state, but its last step was too long ago (the step time expiration interval is calculated using a margin obtained by multiplying the watchdog tick by 1.5 and the thread tick in normal or hibernation mode), the thread is considered suspicious. The timeout is calculated in advance, and if it may be exceeded — the thread's timeout recalculation method is called, since some module in the thread may have started performing heavy work after having changed the maximum step execution wait interval. Thus, to reduce the number of problems — the framework proactively activates timeout rechecking to avoid unnecessarily restarting objects and causing potential issues in program operation.
4: If at the next pass the step has not been executed — the thread is recognized as hung.
5: A "nuclear reset" is performed on the hung thread via `kernel.on_thread_stuck(manager, delay)`.

**Nuclear thread reset:**
When the watchdog triggers on a thread:
1: A critical error is logged with the thread name and hang time
2: `manager.reload()` is called with parameters:
- `source-CURRENT` — work with the current set of units
- `select-ALIVE` — restart only live units
- `action-WORKING` — after reload, start those that were in WORKING
3: If reload fails — an error is logged

Thus, a hung thread does not bring down the entire system — it is forcibly reloaded while other threads continue working. This is especially important for systems with multiple threads, where a hang in one (for example, due to blocking I/O in a module) should not stop the others.

[Contents](#contents)


## Message Broker
_(class `MessageBroker`)_

The broker is the router for all messages in the system. It does not store history, does not guarantee delivery (that is the concern of the command/report protocol through the secretary), but ensures correct routing.

**Broker components:**
- `bus` — central queue (`Queue`) where all secretaries put outgoing messages
- `_local_routes` — dictionary [`addr: AdapterTransport`] for local units (each unit has its own QueueAdapterTransport pointing to its inbox)
- `_federation_routes` — dictionary [`system_name: TcpAdapterTransport`] for remote systems
- `_addr_book` — dictionary [`addr_str: Addr`] of all known addresses (local and remote)
- `_local_manifests` — manifests of local units (published to the network)
- `_remote_manifests` — manifests of remote units (received from the network)
- `_subscribers` — subscription table: [event_type: set[Addr]] — who is subscribed to what

**Routing (step):**
Every kernel tick calls `broker.step()`, which:
1: Reads up to BROKER_BUS_READ_LIMIT messages from the bus
2: For each message, determines the type and addressee
3: If the addressee is local — puts the message in the unit's inbox via local transport
4: If the addressee is remote — sends via federated transport (TCP)
5: System messages (SYS) are handled specially — broadcast to all local units

**Network functions:**
- On new system connection — receives its manifests, registers remote addresses
- On system disconnection — cleans all its addresses and manifests
- `get_public_manifests_dict()` — returns all public local manifests for sending to a remote system

**Address book:**
The broker is the single source of truth for addresses. The `get_addr(addr_str, create, find)` method either finds an existing address or creates a new one (if create-True). This guarantees that two units with the same name in different systems get different Addr objects.

[Contents](#contents)


## Transport Adapters
_(classes `QueueAdapterTransport`, `TcpAdapterTransport`)_

Transport adapters are an abstraction over the physical message delivery method. Each unit (including the kernel) has its own transport registered with the broker. The broker does not care how exactly to deliver a message — it simply calls `transport.send(frame)` or `transport.read()`.

**QueueAdapterTransport (local):**
- Bound to a queue (Queue) — inbox of a specific unit
- `send(frame)` — puts a frame into the unit's queue
- `read()` — retrieves a frame from the queue (called by the unit's secretary)
- `is_empty()` — checks if the queue is empty
- The fastest transport, operates within a single process

**TcpAdapterTransport (network):**
- Bound to TcpService and the remote system's name
- `send(frame)` — serializes the frame to JSON → bytes and sends it via TCP connection to the target system
- `read()` — not used (incoming data is received asynchronously via TcpService.inject_received)
- Stores the mapping between system name and socket

**Other adapters (inactive in v1):**
- `EmailAdapterTransport` — sending/reading via email (POP3/IMAP). Proof of concept, not used.
- In v2, WebSocket, MQTT, and other transports may be added.

[Contents](#contents)


## Protocols
_(class `Frame`)_
`Frame` is the unit of communication in sanapo. Everything transmitted between units is frames. A frame can contain a command, event, report, or system message.

**Frame fields:**
- `msg_type` — message type: `CMD`, `EVT`, `RPT`, `SYS` (`MsgType`)
- `sender` — Addr of the sender
- `recipient` — Addr of the recipient (optional, can be empty for events)
- `cmd_type` — command type (`CmdType`, only for `CMD`)
- `evt_type` — event type (`EvtType`, only for `EVT`)
- `rpt_type` — report type (`RptType`, only for `RPT`)
- `sys_type` — system message type (`SysType`, only for `SYS`)
- `cmd_id` — command identifier (string, for `CMD` and `RPT`)
- `deadline` — absolute deadline timestamp (`float`, only for `CMD`)
- `payload` — payload (`dict`)
- `time_ext_req` — time extension request (`float`, only for `RPT`)
- `reason` — refusal reason (`RptReason`, only for RPT with `CANT_DO`)

**Serialization:**
- `to_dict()` — converts the frame to a dictionary for JSON serialization. Enums are replaced with strings, addresses with strings.
- `from_dict(data, reg, broker)` — restores the frame from a dictionary. Uses `EnumRegistry` to reverse-convert strings to Enums, and the broker for finding/creating addresses.
- `from_dict_light()` — a lightweight version that does not deeply convert addresses (used inside the kernel where addresses are already known).

**Validation:**
Frame checks required fields upon creation. For example, for CMD, cmd_type and recipient are mandatory; for RPT — `cmd_id` and `rpt_type`. On violation, MessageInitError is raised; the secretary logs the error and does not send a broken frame.

**Network specifics:**
When transmitted over the network, Frame becomes JSON, then bytes (UTF-8). On the receiving side: bytes → JSON → dictionary → `Frame.from_dict()`. Enums are restored via the remote system's `EnumRegistry` — this requires the command and event enums to be identical across all project systems.

[Contents](#contents)


## Manifest
_(class `Manifest`)_

A manifest is the unit's passport. It describes who this unit is, what role it performs, what tags it has, and whether it can be found remotely.

**Manifest fields:**
- `addr` — Addr of the unit (whom the manifest belongs to)
- `version` — module version (string, e.g. "1.0.0")
- `role` — unit role (string, e.g. "logger", "worker", "sensor")
- `is_public` — whether to publish the manifest to the network (bool)
- `is_persistent` — whether to save the unit in the consistency dump (bool)
- `tags` — set of tags (set[str]) for searching

**Manifest data sources:**
1: Default values (`version-"1.0.0", role-"default", is_public-False, is_persistent-True`)
2: `module.define_manifest()` — the module can override values
3: `manifest-[...]` parameter when adding the unit — the application programmer can add/override fields
The final manifest is assembled by merging: defaults → module → user. Tags are combined from all sources.

**Usage:**
- Locally: the manifest is stored in the unit and accessible via `self.v.manifest`
- On the network: upon system connection, all public manifests (`is_public-True`) are automatically sent to the new system. It distributes them in `broker._remote_manifests`
- Search: methods `get_remote_addrs_by_role` and `get_remote_addrs_by_tag` search through remote manifests

**Example:**
A logger unit on system Alpha with manifest `[role-"logger", tags-["persistent", "fast"], is_public-True]` will be visible on system Beta. A module on Beta can find it via `self.v.get_remote_addrs_by_role("logger")` and send a command to write a log.

[Contents](#contents)


## UDP Services: Beacon and Listener
_(classes `UdpBeacon`, `UdpListener`)_

Network discovery in sanapo works via UDP. This allows systems to find each other on the local network without manual IP address configuration.

**UdpBeacon:**
- Periodically sends a UDP packet to a broadcast (or multicast) address
- The packet contains: project token, system name, TCP port, protocol version
- Operates in two modes:
- Short interval (`BEACON_SHORT_INTERVAL`) — right after startup, for fast discovery
- Long interval (`BEACON_LONG_INTERVAL`) — after all neighbors have been found
- The beacon can be disabled via config `NET_BEACON-False`

**UdpListener:**
- Listens on a UDP port and receives beacons from other systems
- Upon receiving a beacon, checks the project token — foreign beacons are ignored
- If the beacon is from a new system (or a known one but with a new address) — calls `TcpService.connect_to()` to establish a TCP connection
- Auto-connection can be disabled via config `NET_AUTO_CONNECT_BY_BEACON-False`

**Discovery process:**
1: System A starts up, enables beacon and listener
2: System B starts up, enables beacon and listener
3: Beacon B reaches listener A
4: Listener A checks the token → OK → calls `TcpService.connect_to(host_B, port_B)`
5: `TcpService` A establishes a TCP connection with B
6: After handshake, the systems exchange manifests

[Contents](#contents)


## TCP Service
_(classes `TcpService`, `TcpConnection`)_

The TCP service provides reliable connection between sanapo systems. It operates in a separate thread and manages all connections.

**TcpService:**
- Listens on a TCP port for incoming connections
- Can initiate outgoing connections (connect_to)
- Creates a TcpConnection (in a separate thread) for each connection
- Stores a dictionary [system_name: TcpConnection] for fast access
- Provides methods send_to_system and send_to_addr for sending data
- Manages handshakes and manifest exchange

**TcpConnection (single connection):**
- Operates in a separate thread per socket
- Provides XOR encryption of traffic (if a password is set)
- Implements the sanapo protocol over TCP:
- Header: MAGIC_HEADER (8 bytes) + data length (6 bytes) + message type (1 byte) + CRC32 (4 bytes)
- Service message types: CONN_REQ, TOKEN_META_REQ, TOKEN_META_ACK, CONNECT_ACK, DISCONNECT, REFUSE
- Business message types: DATA_FRAME (serialized Frame)
- Supports Keep-Alive pings to maintain the connection
- Has timeouts for handshake and response waiting

**Handshake protocol:**
1: The outbound side sends CONN_REQ (with its system name)
2: The inbound side checks if the IP is allowed and sends TOKEN_META_REQ
3: The outbound side sends TOKEN_META_ACK (with password hash and metadata: manifests, events, commands)
4: The inbound side verifies the hash and sends CONNECT_ACK
5: Connection is established, manifest exchange occurs
6: If verification fails at any stage — REFUSE is sent with a reason

**Fault tolerance:**
- If the connection breaks, TcpConnection calls on_net_disconnected on the kernel
- The kernel cleans all addresses and manifests of the remote system
- All local units receive `NET_DISCONNECTED` and can call on_net_disconnected in their modules
- When the beacon reappears, the connection will be automatically re-established

[Contents](#contents)


## User Interfaces
_(classes `KernelUserView`, `UnitModuleView`)_

User interfaces (Views) are facades through which the application programmer interacts with the framework. They restrict access to internals and provide only safe methods.

**KernelUserView (for system configuration):**
- Created from the kernel: `view - KernelUserView(kernel)`
- Provides methods for managing components: `add_unit`, `add_thread`, `add_tier`, `del_unit`, `del_thread`, `del_tier`
- Provides lifecycle methods: start, stop, restart
- Gives access to the logger and translator
- Hides the kernel's internal registries, providing only the necessary API

**UnitModuleView (for the module inside the unit):**
- Passed to the module constructor as `self.v`
- Gives access to configuration (`self.v.cfg`), logger (`self.v.log`), secretary (`self.v.scr`), address (`self.v.addr`)
- Allows managing the unit's state: `started()`, `sleep()`, `wakeup()`
- Allows changing timeouts: start_timeout, stop_timeout, step_timeout (with automatic validation)
- Provides methods for searching remote units: `get_active_systems`, `get_remote_addrs_by_sys`, `get_remote_addrs_by_role`, `get_remote_addrs_by_tag`
- Protects the module from direct access to the unit's internals

**Other Views (internal, not for the application programmer):**
- `KernelTierView` — restricted kernel access for tiers (`rebuild_unit`, `get_manager`, `emit_progress`)
- `KernelBootMasterView` — restricted kernel access for the boot master (access to tiers, managers, translator, start/stop/restart methods)

The separation into Views allows refactoring the framework internals without breaking application programmers' code — as long as the public View API does not change, modules continue to work.

[Contents](#contents)


## Miscellaneous
Here is a description of the most changeable modules and classes.

### Module/Class Config
Contains the main settings of the framework; here is assembled the engine control panel. All numbers, strings, and other variables on which the logic depends in any way are collected here.
The logic of log level management — I think in the second version I will move it to each logger object individually, since I encountered the problem of reading a large amount of unnecessary logs when searching for debugs from specific objects.

### Module Enums
Contains all named strings, statuses, and types of other objects to prevent typos during code writing and to speed up code writing thanks to IDE hints.

### Class EnumRegistry
The creation of the `EnumRegistry` class suggested itself at the stage of separating the sanapo framework logic and code from the sanapo-net project. The creation was postponed due to the decision to strictly separate the responsibilities of the framework and programs based on it regarding message typing. The decision was made: report types and system messages are the framework's business, while commands and events are for projects based on sanapo.
With the transition to practical implementation of message transmission over the network, it became clear that there is a problem of converting events and commands to JSON text for subsequent conversion to bytes for TCP/IP transmission. Depriving project developers of the ability to use a safer and more convenient option for typing commands and events in the form of `Enum`-based classes would be against my main idea of creating both the framework and the sanapo-net program — ease and convenience of use, so commands and events are not strings or something else but `Enums`-inherited ones. To enable universal text conversion — this class was created, which registers two user classes of commands and events and is used when converting `Frame` messages to text, then to bytes.

### Boot Visualization
**The class operation has not been verified**. Three classes written for visualizing program boot and shutdown. They were written in one breath, but during debugging and tests it turned out that they either do not work or do work, but test programs boot so fast that the visualization is not visible. Due to the forced completion of work on sanapo v1 and transition to sanapo-net, it was decided to leave the code as is and check/fix it before the release of sanapo v2, or to reduce it.

### Class BriefEnumMixin
**Unused class**. **In sanapo v2, possibly to be reduced**. Makes log reading easier but may break `Frame` conversion to string and back from string to `Frame`.

### Class Translator
**In sanapo v2, possibly to be reduced**. The `Translator` class performs key-oriented localization (l18n) based on JSON files. Used for translating logs, provided as a service via `KernelUserView`. It was planned to be provided as a service in `BaseModule` via `UnitModuleView` in the form of the `BaseModule._()` method. The functionality is in question, as it does not relate to the main complex logic of the framework, bears an auxiliary character, and most often no one wants to localize logs, since a generally accepted and understandable technical English of simple words and phrases is used. Log localization can also complicate identification, for example of errors.

### E-mail Transport and Service
**Unused class**. **In sanapo v2, possibly to be reduced**. Added during the writing of message transport adapters. It proves the high capabilities, universality, and advantages of abstraction from the physical message delivery transport. In practice, it will be used only in specific applications, will increase development time, increase code volume, and the number of included libraries.
It may be relevant under conditions of information blockade and total built-in digital surveillance, as an alternative transport on top of popular global messenger transports.

### Restrictive Interfaces (views)
Classes `KernelTierView`, `KernelBootMasterView`.
**In sanapo v2, possibly to be reduced**. Created as a means to restrict one object from using methods and properties of another object, in this case `Kernel`. There are also definitely necessary user-restricting `UnitModuleView` and `KernelUserView`.
Since the sanapo framework code is written by a single developer — the necessity of the first two classes is questionable.

[Contents](#contents)
