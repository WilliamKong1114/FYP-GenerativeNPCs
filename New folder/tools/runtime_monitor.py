import time
import threading
from functools import wraps
from typing import Dict, Any

class RuntimeMonitor:
    _timings: Dict[str, float] = {}
    _counts: Dict[str, int] = {}
    _lock = threading.Lock()

    @classmethod
    def track(cls, phase_name: str):
        """Decorator to track function execution time."""
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                start = time.time()
                result = func(*args, **kwargs)
                duration = time.time() - start
                with cls._lock:
                    cls._timings[phase_name] = cls._timings.get(phase_name, 0) + duration
                    cls._counts[phase_name] = cls._counts.get(phase_name, 0) + 1
                return result
            return wrapper
        return decorator

    @classmethod
    def start(cls):
        """Start a global timer."""
        cls._start_time = time.time()

    @classmethod
    def get_phase_time(cls, phase_name: str) -> float:
        return cls._timings.get(phase_name, 0)

    @classmethod
    def add_time(cls, phase_name: str, duration: float):
        """Manually add time to a phase (helper function)."""
        with cls._lock:
            cls._timings[phase_name] = cls._timings.get(phase_name, 0) + duration
            cls._counts[phase_name] = cls._counts.get(phase_name, 0) + 1

    @classmethod
    def report(cls):
        """Print a detailed report of all tracked phases and total runtime."""
        total_time = time.time() - cls._start_time
        print("\n" + "="*35)
        print("RUNTIME PERFORMANCE REPORT")
        print("="*35)
        
        print(f"{'Phase Name':<25} | {'Avg/Agent':<10}")
        print("-" * 35)
        
        # Sort by duration descending
        for phase, duration in sorted(cls._timings.items(), key=lambda x: x[1], reverse=True):
            count = cls._counts.get(phase, 1)
            avg_time = duration / count
            print(f"{phase:<25} | {avg_time:>7.2f}s")
            
        print("-" * 35)
        print(f"{'TOTAL WALL CLOCK':<25} | {total_time:>7.2f}s")
        print("="*35 + "\n")

monitor = RuntimeMonitor
