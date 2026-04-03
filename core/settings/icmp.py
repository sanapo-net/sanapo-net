# core/settings/icmp.py
from core.enums import TickInterval
from core.config import SCAN_ICMP_TIMEOUT_MARGIN 

class IcmpPolicy:
    def __init__(self):
        # Default state
        self._defaults = {
            "high": TickInterval.SEC_1,
            "mid":  TickInterval.SEC_2,
            "low":  TickInterval.SEC_4
        }
        
        self._interval_high = self._defaults["high"]
        self._interval_medium = self._defaults["mid"]
        self._interval_low = self._defaults["low"]
        
        self._base_timeout = 0.4
        self._timeout_high = 0.4
        self._timeout_medium = 0.4
        self._timeout_low = 0.4
        self._update_all_timeouts()

    # TODO SCAN_ICMP_TIMEOUT_MARGIN is not in core.config, it in class Config
    def _calculate_clamped_timeout(self, interval: TickInterval) -> float:
        """Ensures timeout never exceeds interval minus safety margin."""
        if interval == TickInterval.OFF:
            return self._base_timeout
        # Interval must be larger than margin
        limit = max(0.1, interval.value - SCAN_ICMP_TIMEOUT_MARGIN)
        return min(self._base_timeout, limit)


    def _update_all_timeouts(self):
        """Recalculate all tiers based on new base timeout or intervals"""
        self._timeout_high = self._calculate_clamped_timeout(self._interval_high)
        self._timeout_medium = self._calculate_clamped_timeout(self._interval_medium)
        self._timeout_low = self._calculate_clamped_timeout(self._interval_low)


    def _shift_interval(self, current: TickInterval, step: int) -> TickInterval:
        """Navigates through TickInterval enum, respecting OFF and SEC_8 boundaries."""
        if current == TickInterval.OFF:
            return TickInterval.OFF
        # Get members up to SEC_8 as per requirement
        valid_range = [m for m in TickInterval if m != TickInterval.OFF and m.value <= 8.0]
        try:
            curr_idx = valid_range.index(current)
            new_idx = max(0, min(len(valid_range) - 1, curr_idx + step))
            return valid_range[new_idx]
        except ValueError:
            # If current was already > 8s, clamp it to 8s
            return TickInterval.SEC_8


    def boost(self):
        """Speeds up all active tiers"""
        self._interval_high = self._shift_interval(self._interval_high, -1)
        self._interval_medium = self._shift_interval(self._interval_medium, -1)
        self._interval_low = self._shift_interval(self._interval_low, -1)
        self._update_all_timeouts()


    def relax(self):
        """Slows down all active tiers"""
        self._interval_high = self._shift_interval(self._interval_high, 1)
        self._interval_medium = self._shift_interval(self._interval_medium, 1)
        self._interval_low = self._shift_interval(self._interval_low, 1)
        self._update_all_timeouts()


    # TODO not from _defaults, from memory
    def reset_to_defaults(self):
        """Restores baseline speed"""
        self._interval_high = self._defaults["high"]
        self._interval_medium = self._defaults["mid"]
        self._interval_low = self._defaults["low"]
        self._update_all_timeouts()

    # --- Properties with logic validation ---

    @property
    def base_timeout(self) -> float:
        return self._base_timeout

    @property
    def interval_high(self) -> TickInterval:
        return self._interval_high
    
    @property
    def interval_medium(self) -> TickInterval:
        return self._interval_medium

    @property
    def interval_low(self) -> TickInterval:
        return self._interval_low
    
    @base_timeout.setter
    def base_timeout(self, val: float):
        """
        Update base timeout and immediately clip all tier timeouts.
        Sanitize user input for timeout. Must be positive.
        """
        try:
            self._base_timeout = max(0.01, float(val))
        except (ValueError, TypeError):
            pass

    @interval_high.setter
    def interval_high(self, val: TickInterval):
        if not isinstance(val, TickInterval):
            return
        if val != TickInterval.OFF and val.value > 8.0:
            val = TickInterval.SEC_8
        self._interval_high = val
        self._update_all_timeouts()
    
    @interval_medium.setter
    def interval_medium(self, val: TickInterval):
        if not isinstance(val, TickInterval):
            return
        if val != TickInterval.OFF and val.value > 8.0:
            val = TickInterval.SEC_8
        self._interval_medium = val
        self._update_all_timeouts()

    @interval_low.setter
    def interval_low(self, val: TickInterval):
        if not isinstance(val, TickInterval):
            return
        if val != TickInterval.OFF and val.value > 8.0:
            val = TickInterval.SEC_8
        self._interval_low = val
        self._update_all_timeouts()

    def get_all_intervals(self) -> dict[str, TickInterval]:
        """Returns the current state of all three scanning intervals."""
        return {
            "high": self._interval_high,
            "mid":  self._interval_medium,
            "low":  self._interval_low
        }

    def get_all_timeouts(self) -> dict[str, float]:
        """Returns the current calculated timeouts for all tiers."""
        return {
            "high": self._timeout_high,
            "mid":  self._timeout_medium,
            "low":  self._timeout_low
        }
