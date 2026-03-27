# tests/stress_twst/test_kernel.py
from core.kernel import Kernel

class TestKernel(Kernel):
    def __init__(self):
        super().__init__()
        
        # The operating speed is 10 times faster
        self.settings.DEFAULT_CMD_DEADLINE_ANSW = 0.005
        self.settings.DEFAULT_CMD_DEADLINE_DONE = 0.08
        self.settings.TICK_RATE = 0.0025
