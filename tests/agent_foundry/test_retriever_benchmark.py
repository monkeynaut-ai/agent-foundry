"""S2.7 — Non-functional: retrieval latency budgets.

Benchmark: 100 queries; median <= 50ms, p95 <= 200ms.
Marked @pytest.mark.benchmark — excluded from normal test runs.
"""

import statistics
import time
import os
from pathlib import Path

import pytest

from agent_foundry.registry.registry import CapabilityRegistry
from agent_foundry.retriever.indexer import RegistryIndexer
from agent_foundry.retriever.retrieval import RetrievalAPI

CAPABILITIES_DIR = Path(__file__).parent.parent.parent / "capabilities"

QUERIES = [f"query_{i}" for i in range(100)]


@pytest.fixture(scope="module")
def retrieval_api(tmp_path_factory):
    registry = CapabilityRegistry.from_directory(CAPABILITIES_DIR)
    index_dir = tmp_path_factory.mktemp("index")
    indexer = RegistryIndexer(index_dir=index_dir)
    indexer.build(registry)
    return RetrievalAPI(indexer=indexer)


@pytest.mark.benchmark
class TestRetrievalLatency:
    """Retrieval must meet latency budget."""

    def test_median_under_50ms_p95_under_200ms(self, retrieval_api):
        slow_factor = float(os.getenv("AF_BENCHMARK_SLOW_FACTOR", "1.0"))
        median_budget_ms = 50 * slow_factor
        p95_budget_ms = 200 * slow_factor
        timings = []
        for q in QUERIES:
            start = time.perf_counter()
            retrieval_api.retrieve(q, k=3)
            elapsed_ms = (time.perf_counter() - start) * 1000
            timings.append(elapsed_ms)

        timings.sort()
        median = statistics.median(timings)
        p95_index = int(len(timings) * 0.95)
        p95 = timings[p95_index]

        print(
            "\nRetrieval latency (100 queries): "
            f"median={median:.1f}ms, p95={p95:.1f}ms, "
            f"budgets=({median_budget_ms:.1f}ms, {p95_budget_ms:.1f}ms)"
        )
        assert median <= median_budget_ms, (
            f"Median {median:.1f}ms exceeds {median_budget_ms:.1f}ms budget"
        )
        assert p95 <= p95_budget_ms, f"p95 {p95:.1f}ms exceeds {p95_budget_ms:.1f}ms budget"
