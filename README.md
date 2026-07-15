# sanapo-net — Network Monitoring & Analysis System
<div align="center"><img src="docs/sanapo/sanapo_logo.png" alt="Logo" width="800"/></div>

[https://img.shields.io/badge/License-BSL-orange](https://www.mariadb.com/bsl11/)
[https://img.shields.io/badge/Python-3.10%252B-blue]

Rapid detection of network failures, scale analysis, problem prediction, network topology visualization, and convenient dashboards.

# Key Features

- **Failure Detection** – real‑time ICMP/TCP device availability monitoring with adjustable intervals.
- **Analytics and Forecasting** – automatic anomaly detection, calculation of baseline network behavior profiles, detection of long‑term degradation trends.
- **Smart Dashboards** – dynamic display of problematic nodes with historical data context.
- **Multi‑level Aggregation** – raw metrics are rolled up into 10‑minute, hourly, and daily slices; automatic cleanup of outdated data.
- **Interactive Network Maps** – topology editor with L1/L2/L3 level support, visual status indication.
- **Notification Bots** – Telegram and Email with a flexible subscription and command system.
- **Multi‑threaded Scanning** – efficient polling of thousands of hosts without UI blocking.
- **Modular Architecture** – isolated units communicating via a thread‑safe message bus (sanapo framework).
- **High Performance** – in‑memory circular buffers, batch writes to SQLite in WAL mode, optimized chart rendering.

# Tech Stack

- **Language**: Python 3.10+
- **GUI**: PySide6 (Qt for Python) — multi‑window MDI with themes
- **Databases**: SQLite (WAL mode), future PostgreSQL/MySQL
- **Key Libraries**: PySide6, Pillow, colorama, icmplib (later Pandas, Matplotlib)
- **Framework**: sanapo (in‑house) — units, threads, tiers, message bus

# Architecture (briefly)

The project consists of isolated **units**, grouped into tiers and started in a specific order. Data exchange happens through a message bus (commands, events, reports). Hot data is stored in NumPy circular buffers, cold data in aggregated SQLite databases. Dashboard applications communicate only with buffers and ready‑made aggregates, without loading raw storages. See [ARCHITECTURE.md](./ARCHITECTURE.RU.md) for details.

# Contributing

Want to help? Check [CONTRIBUTING.md](./CONTRIBUTING.md). We are especially interested in help with GUI migration to PySide6, topology engine optimization, and test writing.
To write most modules, you don’t even need to understand multithreading and asynchronous programming, nor worry about thread safety or complexity of information transfer between modules — even if modules are on different physical machines accessible over the network — these issues are handled by the sanapo framework.

# License

BSL 1.1 until 2030‑01‑01, then Apache 2.0. Details in [LICENSE](./LICENSE).

# Author

Alexander Vasilievich Polykov (SanaPo)
mrsanapo100#gmail.com