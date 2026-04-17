# tests/core/stress_test/common.py
import random
import pickle
import os

class CandleGenerator:
    def __init__(self, name: str, min_val: float, max_val: float, peak: float) -> None:
        self._path = f"{name}.seed"
        self._params = (min_val, max_val, peak)
        
        if os.path.exists(self._path):
            with open(self._path, 'rb') as f:
                random.setstate(pickle.load(f))

    def next(self) -> float:
        val = random.triangular(*self._params)
        with open(self._path, 'wb') as f:
            pickle.dump(random.getstate(), f)
            
        return round(val, 2)
