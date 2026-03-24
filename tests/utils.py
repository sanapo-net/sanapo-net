# tests/utils.py
import random
import threading
import math
import matplotlib.pyplot as plt
from pathlib import Path
from typing import Optional, Literal

class DataGenerator:
    base_path: Path = Path("gens")
    global_mode: Literal["read", "gen_write", "gen"] = "gen_write"

    def __init__(
        self, 
        name: str,                # Unique generator name (used for filename)
        per95_min: float,         # Lower bound for 95% of generated data
        per95_max: float,         # Upper bound for 95% of generated data
        limit: int = 100000,      # Maximum number of samples to store in RAM
        mode: Optional[Literal["read", "gen_write", "gen"]] = None,
        median: Optional[float] = None, # Distribution center (defaults to average of per95)
        skewness: float = 0.0,    # Asymmetry: 0=balanced, >0=left-heavy, <0=right-heavy
        kurtosis: float = 1.0,    # Peak sharpness: 1.0=normal, >1=sharp/thin, <1=flat/wide
        em_min: Optional[float] = None, # Hard floor for values (also for outliers)
        em_max: Optional[float] = None, # Hard ceiling for values (also for outliers)
        em_possible: float = 0.01, # Probability of extreme outlier (0.0 to 1.0)
    ):
        """
        name: Unique identifier for file naming
        per95_min: The value below which only 2.5% of data falls (by default)
        per95_max: The value above which only 2.5% of data falls (by default)
        limit: Max capacity of internal RAM buffer
        mode: 'read' (from file), 'gen_write' (generate & save), 'gen' (RAM only)
        median: Forced center of the distribution bell
        skewness: Shifts the peak and stretches one of the tails
        kurtosis: Adjusts how "pointed" or "flat" the distribution peak is
        em_min: Hard limit: no values will ever be generated below this
        em_max: Hard limit: no values will ever be generated above this
        em_possible: Chance that a sample will be a random jump within em_min/max
        """

        self.name = name
        self.limit = limit
        self.file_path = self.base_path / f"{name}.log"
        self.mode = mode
        
        # Distribution shape
        self.median = median if median is not None else (per95_min + per95_max) / 2
        self._sigma = (per95_max - per95_min) / 4
        self.skew = skewness
        self.kurt = kurtosis
        
        # Hard boundaries (Outliers)
        self.em_min = em_min if em_min is not None else per95_min
        self.em_max = em_max if em_max is not None else per95_max
        self.em_possible = em_possible
        
        self._memory_data: list[float] = [] 
        self._ptr: int = 0
        self._lock = threading.Lock()

    @property
    def current_mode(self) -> str:
        return self.mode if self.mode is not None else DataGenerator.global_mode

    def __enter__(self):
        self.base_path.mkdir(exist_ok=True)
        if self.current_mode == "read":
            if self.file_path.exists():
                with open(self.file_path, "r", encoding="utf-8") as f:
                    self._memory_data = [float(line.strip()) for line in f if line.strip()][:self.limit]
            self._ptr = 0
        else:
            self._memory_data = [] 
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.current_mode == "gen_write" and self._memory_data:
            with open(self.file_path, "w", encoding="utf-8") as f:
                f.writelines(f"{v:.4f}\n" for v in self._memory_data)
        self._memory_data = [] 

    def __call__(self) -> Optional[float]:
        with self._lock:
            if self.current_mode == "read":
                return self._read_next()
            return self._generate_and_store()

    def _generate_and_store(self) -> float:
        if len(self._memory_data) >= self.limit:
            return self._memory_data[-1] if self._memory_data else 0.0

        if random.random() < self.em_possible:
            val = random.uniform(self.em_min, self.em_max)
        else:
            u0, v = random.gauss(0, 1), random.gauss(0, 1)
            if self.skew == 0:
                res = u0
            else:
                delta = self.skew / math.sqrt(1 + self.skew**2)
                u1 = delta * u0 + math.sqrt(1 - delta**2) * v
                res = u1 if u0 >= 0 else -u1
            val = self.median + (res * self._sigma * self.kurt)
            
        # Hard clamping within Outlier boundaries
        if val < self.em_min: val = self.em_min
        if val > self.em_max: val = self.em_max
            
        self._memory_data.append(val)
        return val

    def _read_next(self) -> Optional[float]:
        if not self._memory_data: return None
        val = self._memory_data[self._ptr]
        self._ptr = (self._ptr + 1) % len(self._memory_data)
        return val

def visualize_generator(**kwargs):
    """
    Plots histogram with all limits:
    Red - per95, Blue - outliers (hard limits).
    """
    kwargs['mode'] = 'gen'
    kwargs['limit'] = 10000
    
    p_min, p_max = kwargs.get('per95_min'), kwargs.get('per95_max')
    e_min = kwargs.get('em_min', p_min)
    e_max = kwargs.get('em_max', p_max)
    
    gen = DataGenerator(**kwargs)
    with gen:
        data = [gen() for _ in range(10000)]
    
    plt.figure(figsize=(12, 7))
    plt.hist(data, bins=100, color='skyblue', edgecolor='black', alpha=0.5, label='Samples')
    
    # Reference Lines
    plt.axvline(p_min, color='red', ls='--', lw=2, label='per95 limits')
    plt.axvline(p_max, color='red', ls='--', lw=2)
    plt.axvline(e_min, color='blue', ls=':', lw=2, label='Hard (EM) limits')
    plt.axvline(e_max, color='blue', ls=':', lw=2)

    # Info box
    stats_text = f"Skewness: {gen.skew}\nKurtosis: {gen.kurt}\nEM Prob: {gen.em_possible*100}%"
    plt.gca().text(0.95, 0.95, stats_text, transform=plt.gca().transAxes, 
                   verticalalignment='top', horizontalalignment='right',
                   bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

    plt.title(f"Gen: {gen.name} (Skew={gen.skew}, Kurt={gen.kurt})")
    plt.legend(loc='upper left')
    plt.grid(True, alpha=0.3)
    
    # Adjust X-axis to see the range properly
    plt.xlim(min(e_min, min(data)) - 5, max(e_max, max(data)) + 5)
    plt.show()
