# Architecture of sanapo-net

## Overview

Sanapo-net is a network monitoring and analysis system built on a modular architecture with minimal dependencies between modules. The system helps quickly identify network failures, assess their scale, and predict potential issues.

## 📂 Project Structure

```text
├── core/                # System Backbone (Bus, Orchestrator, DataBuffer)
├── modules/             # Functional Blocks
│   ├── engine/          # Ethernet scanners
│   ├── network/         # Network image
│   ├── storage/         # DB, import, export, logging
│   ├── analysis/        # Real-time & Deep Analytics
│   └── media/           # Sound & Pillow Graphics Rendering
├── dashboards/          # Visual Sub-apps (Dashboards & Settings)
├── net_services/        # Net services (Telegram, Email, Web, TCP/UDP clients)
└── main.py              # System Assembly & Entry Point

## Core Components

* **core**: central module with event queue for event‑driven architecture.
* **orchestrator**: manages interactions between modules with different callback functions (asynchronous or in a separate thread).
* **scan_manager**: handles network scanning functions in a separate module to prevent GUI slowdowns.
* **scan_icmp**: submodule for multi‑threaded ICMP scanning and response time metrics.
* **data_buffer**: double‑buffered data storage with locks to prevent race conditions; aggregates data for different time intervals.
* **net_map**: custom network topology engine on Tkinter Canvas (supports 2000+ nodes) with a graphical editor for creating network maps.
* **db_network_manager** and **db_network_sqlite**: manage network object storage in SQLite using flat tables.
* **network**, **dialogs_ui**, **dialogs_logic**, **validations**: handle network object creation, editing, and data validation.
* **db_history_manager**, **db_history_ping**, **db_history_ping_long**: save scan metric history with Roll‑up aggregation.
* **graphs_history**: display aggregated data at different scales.
* **logger**: log saving to file.
* **db_network_json**, **db_network_csv**: import/export network database in CSV and JSON.
* **settings**: GUI for changing settings.

## Key Features

* Custom topology engine with 2000+ node support and optimized rendering.
* Multi‑threaded scanning for large networks (up to thousands of hosts).
* MDI interface: users can enable only necessary monitoring elements and resize output fields.
* Real‑time network state visualization (available/unavailable/unknown).
* Ping graphs with sensitivity adjustment, sorting, and filtering.

## Development Approach

* **TDD**: requirements → test → code → testing → debugging → PR review → merge to `develop`.
* **Git Flow** for version control.
* **Single Responsibility Principle (SRP)**: each module has one responsibility.

## Roadmap

### v1.0.0
* Implement all MVP‑Legasy functions in a new modular architecture.
* Basic network monitoring via ICMP scanning.
* Network map with real‑time node status visualization.
* MDI interface for managing sub‑applications.

### v2.0.0
* Scan metric history with Roll‑up aggregation.
* History graphs with aggregated data display.
* Logging to file.
* Import/export database (CSV, JSON).
* GUI settings.

### v3.0.0 (horizon view)
* Additional features to be defined after v1.0.0 or v2.0.0 release.