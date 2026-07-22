# Glossary of sanapo-net
[Русская версия](../ru/glossary.md)

## Main Entities

**Unit** – A logical object of the program deployed inside the sanapo framework. It has its own name, address, secretary, logger, and manifest. In code, it is represented by an instance of the `BaseUnit` class, which manages the lifecycle of a single **Module**.

**Module** – A Python object created from a **Module Class**. This is the main object of a unit; it implements the application’s business logic and may have `start`, `stop`, `step` methods, as well as message subscriptions. In the documentation, *scanner module* means the object that executes the scanning code.

**module (outside the sanapo architecture context)** – A Python source code file (`.py`). It is better to use *file* instead to avoid confusion with the module-object.

**Module Class** – A Python class inherited from `BaseModule` (from the sanapo framework). It is used to create a **Module** inside a **Unit**. Examples: `ScannerIcmpManager`, `BufferIcmp`.

**Auxiliary Class** – An ordinary Python class that **does NOT** inherit from `BaseModule`. It is imported and used inside a **Module Class** for utility tasks (rendering graphs, network operations). It may reside in the same directory as the **Module Class** or in the project’s shared auxiliary classes directory if it is imported by several classes. Example: the `GraphsRender` class, which draws graphs but is not itself a unit.

**Module Class of type UTILITY** – A module class that creates a **unit of type UTILITY**. Such a unit has no secretary or pseudo‑loop – it is used as a helper object inside another unit within the same thread and is accessible by direct reference. The main difference from an **Auxiliary Class** is that it has a name, a logger, and access to certain framework resources.

**pseudo‑loop** – The presence and callability of the `step()` method on a **Module**. This method is called regularly by the runner agent inside the thread manager’s loop where the unit resides.

**sub‑application** – A unit that serves as a user interface, outputting information to a graphical interface or a message interface. It can be turned off.

**sub‑window** – The graphical window representation of a **sub‑application**, which is placed within the overall MDI interface, can be resized by user actions, minimised, maximised, closed, etc.

**Tier** – A group of units that start and stop together in a specified order. The tier number determines the startup sequence.

**Thread** – An isolated operating‑system thread in which one or more units run. Managed by the thread manager.

**Frame** – A communication unit between units. It is passed through the message broker and contains a type (`CMD`, `EVT`, `RPT`, `SYS`), a recipient, and a payload.

**Command (CMD)** – A message type by which one unit (the commander) gives a task to another unit (the executor). Always expects a report in reply.

**Event (EVT)** – A message type that a unit publishes to the bus to notify all subscribers about some fact (e.g., scanning completion).

**Report (RPT)** – A reply message to a command. It contains an execution status (`DONE`, `INTO_WORK`, `CANT_DO`) and, optionally, a result or the reason for failure.

[Documentation](../../README.md)