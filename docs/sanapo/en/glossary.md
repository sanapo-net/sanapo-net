# sanapo Glossary

**Core terms**

**Unit** (in the context of logic) – a logical program object deployed within the framework. It consists of a module, secretary, logger, manifest, and address. It is managed by the kernel, lives in a thread and a tier, and has its own name as part of the address.

**unit** (in the context of code) – a Python object of class `BaseUnit`.

**Module** - a Python object of a class inherited from `BaseModule`. Implements business logic: `start()`, `stop()`, `step()`, message subscriptions.

**Module class** - a class inheriting `BaseModule`. Used to create modules inside units.

**Secretary** - component of a unit responsible for sending/receiving messages, subscription management, and command deadline control.

**Thread** - an OS thread executing one or more units. Managed by `ThreadManager`.

**Tier** - a group of units started and stopped together in a defined order. Controlled by `BootMaster`.

**Kernel** - central orchestrator. Creates/destroys all components, runs the main processing loop.

**MessageBroker** - router of all messages between units, including remote systems.

**Frame** - standardized message transferred via broker. Contains type, sender, recipient, and payload.

**Manifest** - unit's passport: role, version, tags, public flag.

**Addr** - unique unit identifier in `system:name` format.

**BootMaster** - manages sequential start and stop of tiers.

**WatchDog** - monitors thread hangs and forcibly reloads them.

**UdpBeacon** - broadcasts UDP packets for discovery by other sanapo systems.

**TcpService** - provides secure reliable connections between systems.