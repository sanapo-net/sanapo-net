# sanapo-net — Network Monitoring & Analysis 
[Русская версия](./docs/ru/readme.md)

<div align="center"><img src="docs/sanapo_net_logo.png" alt="Logo" width="600"/></div>

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
- **Framework**: sanapo (in‑house) — units, threads, tiers, message bus [LICENSE](https://github.com/sanapo-net/sanapo/blob/master/LICENSE)

# Documentation

- [Brief General Description of the Program](./docs/en/description.md) - for end users and management.
- [Architecture](ARCHITECTURE.md) - a technical description of the system.
- [Glossary](./docs/en/glossary.md) - terms used in the project.
- [Units (now only russian lang)](./docs/ru/units/index.md) - cards for all units of the sanapo-net program.
- Specifications - technical specifications for developers.
    - [Module Class Specifications (now only russian lang)](./docs/ru/spec/module_classes/index.md)
    - [Utility Class Specifications (now only russian lang)](./docs/ru/spec/utility_classes/index.md)
- [Contribute to the project](CONTRIBUTING.md)
- [License](../../LICENSE) - BSL 1.1 until 2030-01-01, then Apache 2.0.

# Author

Alexander Vasilievich Polykov (SanaPo)
mrsanapo100@gmail.com