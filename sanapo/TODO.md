## Add feature: send multicast events between systems based on subscriptions
### TODO
#### MessageBroker
- add self.net_evt_subscriptions: dict[Addr, dict[str|EvtType, Addr]]
- add self.net_evt_subscribers: dict[Addr, list[str]]
#### Secretary
- add self.configure_net_subscriptions(sys: str, evts: dict[EvtTypeClass | str, callable] | None)
- add self.net_subscribe(sys: str, cb: callable, evt: EvtTypeClass | str)
- add self.net_unsubscribe(sys: str, cb: callable, evt: EvtTypeClass | str)
#### Enums
- add SysType: NET_SUB, NET_UNSUB, NET_SUB_SETUP as local analogues
- add SysType: NET_EVT as inbound event-message for Secretary
- add SysType: NET_EVT_TRANS as inbound event-message for system
- add SysType: NET_SUB_SETUP_TRANS as inbound subscribe for system
### Note
- approach: use EvtType if found in local system, otherwise use str
- on system connection: check project bytes, exchange manifests; if projects differ, exchange evt-lists
- only events? commands?

## Add feature: add session id to every net-message; ignore manifest and evt-list exchanges if session is old
## Add feature: automatically adjust deadlines if message is meant for network transport
## I need New Test System for net-tests; possibly requires BaseTest class
## Problem: messages take too long to arrive (15-60ms). Need time tests and optimization.
## Del feature: Maybe delete email transport: keep only Queue and TCP
## Add feature: Add ability to adjust logger settings individually for each logger object
## Add feature: Make it possible to send a manifest both as a dictionary and as an object
