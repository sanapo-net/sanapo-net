# tests/test_core_1.py
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock
from core.kernel import Kernel

# DDT-data: event_type, event_payload, sub_type
test_data = [
    ("EVENT_TYPE_0", {"msg_type_0": 1000}, "async"),
    ("EVENT_TYPE_1", {"mag_type_1": [1, 2, 3]}, "sync"),
    ("EVENT_TYPE_2", {"msg_type_2": {'some_id':777}}, "async"),
    ("EVENT_TYPE_3", {}, "sync"),
]

@pytest.mark.parametrize("event_type, event_payload, sub_type", test_data)
@pytest.mark.asyncio
async def test_kernel_delivery_ddt(event_type, event_payload, sub_type):

    kernel = Kernel()

    # subscribing with pseudo-callback
    callback = AsyncMock() if sub_type == "async" else Mock()
    kernel.subscribe(event_type, callback)

    # go
    kernel.orchestrator.start()

    # send messages
    message = {"event": event_type, **event_payload}
    kernel.emit(message)

    # pseudo work
    await asyncio.sleep(0.1)

    # checking
    callback.assert_called_with(message)