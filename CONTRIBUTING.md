# Contributing to sanapo-net

We welcome any contributions to sanapo-net! Here's how you can help.

# Licensing of Contributions
By submitting a Pull Request, you agree that your contribution will be licensed under the same license as the project: Business Source License 1.1 until 2030‑01‑01, then Apache 2.0 License.

# How to Contribute

**Fork the repository** and create a branch for your feature or fix (`git checkout -b feature/AmazingFeature`).

**Commit your changes** (`git commit -m 'Add some AmazingFeature'`).

**Push the branch** (`git push origin feature/AmazingFeature`).

**Open a Pull Request**.

You can also create a branch right here, just message me!

# Areas Needing Help

- **GUI** – Migration from Tkinter‑based MVP to PySide6 (Qt for Python) in version 1. Help is needed with porting existing MDI windows, maps, charts, and UI controls.
- **Topology Engine** – Implementation of map rendering, support for L1/L2/L3 and hybrid levels, visual editing of elements (walls, racks, links), switching between maps.
- **Scanners** – Addition of TCP/UDP scanner.
- **Databases** – Implementation of additional backends (PostgreSQL, MySQL) alongside the current WAL‑mode SQLite files. Adaptation of managers DbIcmp, DbSys, etc.
- **Testing** – Writing unit and integration tests for units (scanners, buffers, analytics, DB managers). Help with CI setup.
- **Performance** – Optimization of chart rendering (ChartRenderer, CandlestickRenderer).
- **sanapo Core** – Improvements to the sanapo framework; a simplified list is prepared in [`TODO in ver2`](./docs/sanapo/en/todo-v2.md).

# Code Standards

- Follow the project’s coding style.
- Add clear comments for non‑trivial code.
- Ensure all tests pass before submitting a PR.
- Use descriptive commit messages.
- Maximum line length 100 characters.
- Type annotations in function/method signatures and properties in `init()`.
- Comments and docstrings in English, using the simplest possible language.
- Desired sizes: Modules 200–600 lines, Functions/Methods 5–50 lines, nesting within functions/methods up to 4 levels.
- Use type aliases for complex types.

# Communication

- Open an **Issue** for ideas, questions, or bug reports.
- Contact the author directly: Alexander Polyakov (SanaPo). mrsanapo100#gmail.com

Thank you for helping make sanapo-net better!