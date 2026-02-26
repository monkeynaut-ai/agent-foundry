"""S2.7 — Non-functional: retrieval latency budgets.

Benchmark: 100 queries; median <= 50ms, p95 <= 200ms.
Marked @pytest.mark.benchmark — excluded from normal test runs.
"""

import statistics
import time
from pathlib import Path

import pytest

from agent_foundry.registry.registry import CapabilityRegistry
from agent_foundry.retriever.indexer import RegistryIndexer
from agent_foundry.retriever.retrieval import RetrievalAPI

CAPABILITIES_DIR = Path(__file__).parent.parent / "capabilities"

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

        print(f"\nRetrieval latency (100 queries): median={median:.1f}ms, p95={p95:.1f}ms")
        assert median <= 50, f"Median {median:.1f}ms exceeds 50ms budget"
        assert p95 <= 200, f"p95 {p95:.1f}ms exceeds 200ms budget"
