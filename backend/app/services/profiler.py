"""
Pipeline Profiler
=================
Measures execution time for every stage in the live stream pipeline.
Call start(stage) / end(stage) around each section.
Reports bottlenecks every N frames.
"""
import time
from collections import defaultdict, deque
from typing import Dict


class PipelineProfiler:
    def __init__(self, report_every: int = 100):
        self._starts:  Dict[str, float] = {}
        self._totals:  Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self._report_every = report_every
        self._frame_count  = 0

    def start(self, stage: str):
        self._starts[stage] = time.perf_counter()

    def end(self, stage: str):
        if stage in self._starts:
            elapsed = (time.perf_counter() - self._starts.pop(stage)) * 1000  # ms
            self._totals[stage].append(elapsed)

    def report(self) -> Dict[str, float]:
        """Returns avg ms per stage."""
        return {
            stage: round(sum(times) / len(times), 2)
            for stage, times in self._totals.items()
            if times
        }

    def frame(self) -> bool:
        """Call once per frame. Returns True when report is due."""
        self._frame_count += 1
        if self._frame_count % self._report_every == 0:
            r = self.report()
            total = sum(r.values())
            print(f"[Profile] Frame {self._frame_count} — total {total:.1f}ms/frame (~{1000/max(total,1):.1f}fps)")
            for stage, ms in sorted(r.items(), key=lambda x: -x[1]):
                pct = (ms / max(total, 1)) * 100
                bar = "█" * int(pct / 5)
                print(f"  {stage:<22} {ms:6.1f}ms  {pct:4.0f}%  {bar}")
            return True
        return False
