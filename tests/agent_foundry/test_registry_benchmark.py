"""S1.8 — Non-functional: startup performance budget.

Benchmark test: registry startup under N=100 specs, p95 <= 500ms.
Marked @pytest.mark.benchmark — excluded from normal test runs.
"""

import os
import statistics
import time
from pathlib import Path

import pytest
import yaml

from agent_foundry.registry.registry import RoleRegistry

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def large_roles_dir(tmp_path):
    """Create a directory with 100 unique role specs."""
    d = tmp_path / "capabilities"
    d.mkdir()
    base_spec = yaml.safe_load((FIXTURES / "valid_role.yaml").read_text())
    for i in range(100):
        spec = {**base_spec, "name": f"role_{i:03d}"}
        (d / f"role_{i:03d}.yaml").write_text(yaml.dump(spec))
    return d


@pytest.mark.benchmark
class TestRegistryStartupPerformance:
    """Registry startup must meet performance budget."""

    def test_startup_p95_under_500ms(self, large_roles_dir):
        slow_factor = float(os.getenv("AF_BENCHMARK_SLOW_FACTOR", "1.0"))
        p95_budget_ms = 500 * slow_factor
        timings = []
        for _ in range(20):
            start = time.perf_counter()
            RoleRegistry.from_directory(large_roles_dir)
            elapsed_ms = (time.perf_counter() - start) * 1000
            timings.append(elapsed_ms)

        timings.sort()
        p95_index = int(len(timings) * 0.95)
        p95 = timings[p95_index]
        median = statistics.median(timings)

        assert p95 <= p95_budget_ms, (
            f"p95 startup time {p95:.1f}ms exceeds {p95_budget_ms:.1f}ms budget"
        )
        # Log for visibility
        print(
            "\nRegistry startup (N=100): "
            f"median={median:.1f}ms, p95={p95:.1f}ms, budget={p95_budget_ms:.1f}ms"
        )
