# tests/stress_test/test_main.py
# Run it as "python -m tests.stress_test.test_main" into sanapo-net/
import asyncio

import tests.stress_test.params as params
from tests.stress_test.test_kernel import TestKernel
from tests.stress_test.mock_module import MockModule
from core.enums import Addr, EvtType

async def run_test():
    all_results = []
    responders = [n for n in params.MODULE_NAMES if "R" in n]

    for i in range(8):
        print(f"Iter {i+1}/8: {params.ITERATION_NAMES[i]}")
        kernel = TestKernel()
        mocks = []
        
        for addr in params.MODULE_NAMES + [Addr.BUFFER]:
            messenger = kernel.orchestrator.connect(addr)
            m = MockModule(addr, messenger, f"tests/stress_test/gen/iter_{i+1}", 
                           params.STRESS_PARAMS[i][0], params.STRESS_PARAMS[i][1], responders)
            messenger.subscribe(m.on_receive, evt_type=EvtType.BUFFER_NEW_DATA)
            messenger.subscribe(m.on_receive, evt_type=EvtType.EVT_TEST)
            mocks.append(m)

        await kernel.launch()
        
        ovr = sum(m.bus_overcrowded_count for m in mocks)
        print(f" -> Done. Overcrowded incidents: {ovr}")
        
        all_results.append([rec for m in mocks for rec in m.logs])
        await asyncio.sleep(1) # Cool down

    print("Generating visual reports...")
    from visualizer import analyze_and_plot
    analyze_and_plot(all_results)
    print("Stress test finished successfully.")

if __name__ == "__main__":
    asyncio.run(run_test())
