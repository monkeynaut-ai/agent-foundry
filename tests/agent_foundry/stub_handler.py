"""Stub handler classes for testing dynamic resolution."""


class StubHandler:
    def __init__(self, spec):
        self.spec = spec

    def __call__(self, state, node_config=None):
        return {**state, "handled": True}

    def custom_method(self, state, node_config=None):
        return {**state, "custom": True}


class BadInitHandler:
    def __init__(self, spec):
        raise ValueError("init failed")


class NoCallHandler:
    def __init__(self, spec):
        pass
