# tests/stress_test/params.py
MODULE_NAMES = [
    "MSCH", "MSCL", "MACH", "MACL", "OSCL", "OACL", 
    "MSRH", "MSRL", "MARH", "MARL", "OSRL", "OARL"
]

# Params for generators (work imitations and time between event or command sending)
STRESS_PARAMS = [
    # 1. Minimum load
    ({"per95_max": 20, "per95_min": 1}, {"per95_max": 50, "per95_min": 20}),
    # 2. Medium load
    ({"per95_max": 50, "per95_min": 1}, {"per95_max": 25, "per95_min": 10}),
    # 3. Hight load
    ({"per95_max": 100, "per95_min": 1}, {"per95_max": 15, "per95_min": 5}),
    # 4. Peak load (the queue will grow)
    ({"per95_max": 250, "per95_min": 1}, {"per95_max": 10, "per95_min": 1}),
    # 5. Minimum load + rare small emissions
    ({"per95_max": 20, "per95_min": 1, "em_min": 1, "em_max": 80, "kurtosis": 0.9, "em_possible": 0.05}, 
     {"per95_max": 50, "per95_min": 20, "em_min": 1, "em_max": 80, "kurtosis": 0.9, "em_possible": 0.05}),
    # 6. Unstable operation (surges up to 150 ms)
    ({"per95_max": 50, "per95_min": 1, "em_min": 1, "em_max": 150, "kurtosis": 0.7, "em_possible": 0.05}, 
     {"per95_max": 25, "per95_min": 10, "em_min": 1, "em_max": 40, "kurtosis": 0.7, "em_possible": 0.05}),
    # 7. Severe conditions (surges up to 250ms, risk of timeouts)
    ({"per95_max": 100, "per95_min": 1, "em_min": 1, "em_max": 250, "kurtosis": 0.5, "em_possible": 0.1}, 
     {"per95_max": 15, "per95_min": 5, "em_min": 1, "em_max": 20, "kurtosis": 0.5, "em_possible": 0.1}),
    # 8. Critical stress (spikes up to 450ms, guaranteed deadline misses)
    ({"per95_max": 250, "per95_min": 1, "em_min": 1, "em_max": 450, "kurtosis": 0.3, "em_possible": 0.1}, 
     {"per95_max": 10, "per95_min": 1, "em_min": 1, "em_max": 10, "kurtosis": 0.3, "em_possible": 0.1})
]

ITERATION_NAMES = [
    "1. Minimum load",
    "2. Medium load",
    "3. High load",
    "4. Peak load (the queue will grow)",
    "5. Minimum load + rare small emissions",
    "6. Unstable operation (surges up to 150 ms)",
    "7. Severe conditions (surges up to 250ms, risk of timeouts)",
    "8. Critical stress (spikes up to 450ms, guaranteed deadline misses)"
]