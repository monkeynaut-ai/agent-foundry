from agent_foundry.observability import (
    AgentTurnRecord,
    JsonlObservabilityStore,
    NoOpObservabilityStore,
    ObservabilityStore,
    StopReason,
    StreamMetrics,
    TokenUsage,
    extract_stream_metrics,
)


class TestPublicApi:
    def test_all_public_symbols_importable_from_package_root(self) -> None:
        assert AgentTurnRecord is not None
        assert JsonlObservabilityStore is not None
        assert NoOpObservabilityStore is not None
        assert ObservabilityStore is not None
        assert StopReason is not None
        assert StreamMetrics is not None
        assert TokenUsage is not None
        assert callable(extract_stream_metrics)
