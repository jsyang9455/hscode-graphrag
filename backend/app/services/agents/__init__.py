"""Agents package exports (lazy-safe: avoid circular imports with ClassificationPipeline)."""

__all__ = [
    "BlindTesterAgent",
    "EvaluatorAgent",
    "SupervisorAgent",
    "SIAHarnessLoop",
    "FeedbackHarnessAgent",
    "get_harness",
]


def __getattr__(name: str):
    if name in {"BlindTesterAgent", "EvaluatorAgent", "SupervisorAgent"}:
        from backend.app.services.agents import loop as _loop

        return getattr(_loop, name)
    if name == "SIAHarnessLoop":
        from backend.app.services.agents.sia_loop import SIAHarnessLoop

        return SIAHarnessLoop
    if name in {"FeedbackHarnessAgent", "get_harness"}:
        from backend.app.services.agents import harness as _harness

        return getattr(_harness, name)
    raise AttributeError(name)
