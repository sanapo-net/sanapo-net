# sanapo-net Architecture

<div align="center"><img src="docs/sanapo/sanapo_logo.png" alt="logo" width="600"/></div>

# Overview
sanapo-net is a modular network monitoring and analysis system built on the **sanapo framework**. It provides real‑time availability checks, performance metric collection, anomaly detection, historical analysis, interactive maps, and notifications via Telegram/Email within an MDI desktop application. The system is designed for networks of any scale – from small office LANs to large distributed infrastructures – and minimises load through in‑memory buffering, multi‑level data aggregation, and an event‑driven architecture.

# Key Design Principles
- **Isolation** – Functional components (units) communicate only through a thread‑safe message bus; direct dependencies are minimised.
- **Tiered Startup** – Components are grouped into tiers that start and stop in a defined order; the next tier is activated only after the previous one is ready.
- **In‑Memory Buffering** – High‑frequency metric streams are first collected in RAM (circular buffers, dictionaries) and then batch‑written to databases.
- **Aggregation Hierarchy** – Raw metrics are rolled up into 10‑minute, hourly, and daily aggregates; old raw data is automatically deleted.
- **Lightweight Frontends** – User applications work with pre‑aggregated data and data from operational buffers, never touching heavy historical tables directly.
- **Pluggable Bots** – Notification and control channels (Email, Telegram) are implemented as independent units that can be added or removed without affecting the system core.

# High‑Level Component Map
^^^
{User} ↔ {Graphical Shell (MDI)}
├─ AppDashboard
├─ AppSmartDashboard
├─ AppGraphsIcmp / AppHistoryIcmp
├─ AppMaps
├─ AppMonitorTCP
├─ AppAnalytics
└─ Bots (Email, Telegram)

{Analytics}
├─ Analysator (real‑time anomaly detection)
└─ Analytic (periodic baseline profile computation)

{Data Pipeline}
Scanners → Buffers → DB Managers → Databases
Scanners → Buffers → Interface Sub‑Applications
^^^

# Component Catalog

# Scanners and Data Sources
- **ScannerICMP** – Manages asynchronous ICMP probing, prepares data for scanning based on information received from the network module and the ICMP buffer module. Generates events at configurable intervals (1 second … 24 hours). Results are sent to the ICMP buffer via the bus.
- **ScannerTCP** – Active TCP port scanner. Runs in a dedicated thread to avoid blocking on time‑outs. Results go to the network module.
- **sniffer** – Passive frame capture using raw sockets or Scapy. Runs in a separate thread.
- **HostProfiler** – Gathers detailed device information (MAC vendor, IP, OS fingerprint) using system calls, an OUI database, and third‑party libraries.

# Buffers (In‑Memory Real‑time Stores)
- **BufferIcmp** – A circular NumPy matrix (600 rows × N columns) holding the last 10 minutes of ICMP metrics for all hosts. Provides near‑zero‑latency access for graphs and dashboards. Every 10 minutes it forwards raw and pre‑aggregated data to the ICMP metrics storage database manager.
- **BufferSys** – Collects system performance metrics (CPU, memory, disk) in its own thread. Every 10 minutes it pushes a batch to DbSys for persistent storage.
- **BufferTcp** – Most likely will not be used according to the intended architecture.

# Database Managers and Storage
- **DbIcmp** – Manages all ICMP storage. Every 10 minutes it receives aggregated and raw data from BufferIcmp and writes them to icmp_10m.database and icmp_raw.database (separate SQLite files in WAL mode). It performs hourly and daily aggregations, saving results to icmp_hours.database and icmp_days.database. At midnight, the icmp_raw database is deleted and recreated. Old aggregates are pruned on schedule (10‑min > 31 days and hourly > 93 days). Aggregated data is also published on the bus for subscribers (e.g., the Analytic unit).
- **DbSys** – Equivalent manager for system metrics: raw → sys_raw.database, aggregates → sys_10m.database, sys_hour.database, sys_day.database. Daily raw DB cleanup.
- **DbMaps** – A graphical ORM layer that converts complex map objects (walls, windows, desks, trees, devices, links) to flat tables in maps.database and back.
- **ManagerDbNetwork** – Import/export of network topology in CSV, JSON, and SQLite formats, delegating to auxiliary classes (CsvStorageNetwork, JsonStorageNetwork, SqliteStorageNetwork).

# Network Topology
- **NetworkManager** – Holds the network graph (Network.class) and its snapshots (NetworkSnapshot.class). Cooperates with DbMaps and ManagerDbNetwork for persistence and topology exchange.

# Analytics Pipeline
- **Analysator (analysator.unit)** – Real‑time anomaly detector. Reads medians and other indicators over 1‑, 3‑, and 10‑minute windows directly from BufferIcmp. Publishes events (status changes, critical deviations) on the bus for dashboards and bots.
- **Analytic (analytic.unit)** – Periodic heavy‑computation module. Builds behavioural profiles (day‑by‑10‑min, week‑by‑hour, week‑by‑day, year‑by‑day) and a global degradation trend by aggregating history from icmp_hours.database and icmp_days.database. Results are stored in analytic.database via db_analytic.unit. Upon detecting negative trends (e.g., gradually increasing latency), it publishes warnings on the bus; it also publishes per‑host aggregated data to the analyser, which periodically compares real‑time behaviour with the corresponding statistical behaviour from the same 10‑minute / hour / day window over a defined period.

# Applications
# Operational Monitoring Dashboards
- **AppDashboard** – The main dashboard. Subscribes to Analysator alerts and displays host statuses and summary indicators using data from BufferIcmp and icmp_10m.database. Embeds into the MDI interface as a child window.
- **AppSmartDashboard** – An intelligent variant that dynamically creates tiles for problematic devices based on Analysator alerts and Analytic historical profiles, making it possible to distinguish real incidents from planned load.

# Historical Graphs
- **AppGraphsIcmp** – Live graph widget (uses ChartRenderer or CandlestickRenderer). Reads data from BufferIcmp or icmp_10m.database. Contains a toolbar of control buttons (MdiButton).
- **AppHistoryIcmp** – Extends AppGraphsIcmp to display historical graphs. Requests data through DbIcmp, which automatically selects the appropriate aggregation level (hourly or daily) based on the requested time range.

# Advanced Analytics and Smart Dashboards
- **AppAnalytics** – Application for complex mathematical computations (regression, correlation). Reads exclusively pre‑calculated profiles from analytic.database, never touching raw metrics.

# Network Maps
- **AppMaps** – Interactive map widget. Loads topology from network.database via DbNetwork and colours elements in real time based on data from BufferIcmp or bus alerts. Edited by the user with visual tools; serves to visualise network diagrams at L1 / L2 / L3 levels or in a hybrid fashion.

# TCP Monitor
- **AppMonitorTCP** – Displays current port states and scan history, combining live data from BufferTcp and historical records from DbTcp.

# Bots (Telegram and Email)
- **BotEmail** and **BotTg** – Notification and command bot units. They subscribe to system events (e.g., a host going offline) and forward notifications to users. Administrators can manage subscriptions, register users, and query information via commands. A role‑based model (admin/user) and a wide range of service requests (sub, unsub, user‑reg, etc.) are implemented. Communication with the system core occurs exclusively through the sanapo message bus.
As a lower‑priority follow‑up (or in parallel), additional bots for other messengers and social networks may be developed.

# Graphical Shell (MDI)
- **Mdi** – The main application window with a Multiple Document Interface. It consists of a left sidebar of buttons (48 pixels wide) and a work area for child windows.
- **SubWindow** – A window for a sub‑application. Contains a title bar, a toolbar (buttons, input fields), and a content area. Supports edge snapping, maximisation, and size restoration.
- **Themes** – The Theme Manager provides light and dark schemes with a fixed palette (hover, enabled, disabled, work, bad, warning). Components react dynamically to theme changes.
- **Icons** – Loaded from a sprite atlas at startup, cached as alpha masks, and tinted to the required colour on the fly using QPainter composition. This avoids storing multiple colour variants on disk.
- **Buttons** (MainBt, MainBtSwitch, MainBtMenu, MainBtApp) – Sidebar buttons: a simple action button, a toggle, a menu with a horizontal sub‑panel, or an application launcher. Colour and behaviour reflect status and availability.

# Shared Rendering Classes
- **ChartRenderer** – Draws bar charts with a colour gradient (red‑yellow‑green) based on the metric value. Supports “trails” (semi‑transparent copies) for missing data and special error bars for time‑outs. Optimised for step‑by‑step real‑time updates.
- **CandlestickRenderer** – Draws candlestick charts (box‑and‑whisker), displaying the distribution of a metric (min, p5, p25, p50, p75, p95, max). Used to visualise aggregated data (e.g., latency quartiles). All dimensions scale relative to a base width.

# Data Flows and Interaction Scenarios
- **Scan → Buffer → DB**: Scanners produce raw measurements → Buffers accumulate and optionally pre‑aggregate → DB Managers perform batch writes to SQLite.
- **Operational Views**: Applications (Dashboard, Graphs, Maps) subscribe to buffer contents or read the fast icmp_10m.database for the latest 10‑minute aggregates.
- **Historical Views**: Applications (History, Analytics) request data through DbIcmp, which serves ready‑made hourly/daily aggregates, never touching raw tables.
- **Analytics Loop**: The Analytic unit periodically reads icmp_hours.database and icmp_days.database, computes profiles, stores them in analytic.database, and publishes trend warnings.
- **Alert Distribution**: Analysator and Analytic publish events (host statuses, anomalies, trends) on the message bus. Subscribers (dashboards, bots) react immediately.

# Storage and Database Strategy
- All performance‑critical databases are separate SQLite files with WAL journal mode, allowing concurrent reading and writing.
- Raw ICMP data is kept only for the current day, after which the database is physically deleted and recreated.
- Aggregated data is stored in multiple tiers: 10‑minute (31 days), hourly (93 days), daily (longer retention depending on the metric).
- Analytics results are placed in an isolated analytic.database.
- Network topology and maps reside in their own databases, served by specialised managers.

# Deployment and Tiers (approximate startup order)
The system starts in layers under the control of the sanapo BootMaster. The recommended tier order for sanapo-net is:

**Infrastructure** – DbIcmp, DbSys, DbTcp, DbMaps, ManagerDbNetwork, NetworkManager.

**Data Acquisition** – Scanners (ICMP, TCP, Sniffer), Buffers (Icmp, Sys, Tcp), HostProfiler.

**Processing** – Analysator, Analytic.

**Applications** – All App* units, Bots.

**Graphical Shell** – Mdi.
Units within a tier start concurrently; the next tier begins launching only after all units of the previous tier have entered the working state.

# Threading Model
- Scanners (TCP, Sniffer, ICMP manager) and buffers (Sys, ICMP) run in their own dedicated threads to avoid blocking the UI and to meet hard real‑time requirements.
- DB Managers (DbSys, DbTcp) are also moved to separate threads to isolate disk I/O.
- The custom sanapo framework provides thread managers that automatically detect hung threads (via WatchDog) and can reload them without stopping the entire system by recreating the module object (modular class) inside the unit, recreating the unit by the sanapo kernel, or restarting the whole thread along with its contained units, modules, and environment.

# Message Bus and Communication (sanapo Framework)
All inter‑unit communication takes place over the sanapo message bus. The exchange includes:
- **Commands (CMD)** – Addressed tasks with a mandatory reply (report).
- **Events (EVT)** – Broadcast notifications for subscribers.
- **Reports (RPT)** – Command execution status.
- **System Messages (SYS)** – Infrastructure events (connection/disconnection of other sanapo systems).
When multiple sanapo systems are federated, messages are serialised to JSON and transmitted over TCP. Automatic neighbour discovery in a local network is implemented via UDP beacons; inter‑system messages are encrypted and transmitted using a custom protocol over TCP/IP.

# Configuration and Extensibility
- Module parameters, thread assignments, and tier numbers are specified at application assembly (main.py) via the KernelUserView API.
- New monitoring capabilities are added by implementing a module class (inheriting BaseModule) and registering it in the appropriate tier.
- The bot framework allows adding additional communication channels (e.g., Slack) following the same pattern as BotEmail/BotTg.

# References
- [Architecture of the sanapo framework](./docs/sanapo/en/architecture.md) – description of units, threads, tiers, message protocol, and boot process.
- [sanapo framework documentation](./docs/sanapo/en/index.md)
- [sanapo-net program documentation](./docs/sanapo-net/en/index.md) – detailed technical documentation for each unit and auxiliary classes.