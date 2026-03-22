# sanapo-net — Network Monitoring & Analysis System

[![License: BSL](https://img.shields.io/badge/License-BSL-orange)](https://www.mariadb.com/bsl11/)

Quickly identify network failures, analyze their scale, predict issues, and visualize your network topology.

## Key Features

* **Failure Detection**: Real‑time visualization of network state (available/unavailable/unknown).
* **Analysis & Prediction**: Ping graphs with sensitivity adjustment, sorting, and filtering.
* **High Scalability**: Supports networks with thousands of hosts.
* **Custom Topology Engine**: Built on Tkinter Canvas with 2000+ node support and optimized rendering.
* **Multi‑threaded Scanning**: Efficient ICMP scanning without GUI slowdowns.
* **MDI Interface**: Enable only necessary monitoring elements and resize output fields.
* **Data Aggregation**: Roll‑up history with aggregated data display.
* **Flexible Storage**: Save network maps in SQLite; import/export in CSV and JSON.

## Tech Stack

* **Language**: Python
* **GUI**: Tkinter (planned migration to PyQt6)
* **DB**: SQLite
* **Libraries**: Pillow, pythonping, colorama, icmplib, sv_ttk, nava

## Roadmap

### v1.0.0
* All MVP‑Legasy functions in new modular architecture.
* ICMP scanning and real‑time network map.
* MDI interface for sub‑applications.

### v2.0.0
* Scan metric history with Roll‑up.
* History graphs and logging.
* Import/export (CSV, JSON) and GUI settings.

### v3.0.0 (future)
* Additional features defined post‑v2.0.0.

## Contribution

Want to help? Check [CONTRIBUTING.md](CONTRIBUTING.md) for details. We especially need help with PyQt6 migration and performance optimization.

## License

BSL1.1 until 2029-01-01, then Apache 2.0. See [LICENSE](LICENSE).

## Author

Alexander Vasilievich Polykov (SanaPo)