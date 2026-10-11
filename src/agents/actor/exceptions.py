"""Actor-runtime exception types."""


class AgentBudgetExceeded(RuntimeError):
    """Raised when an actor execution budget is exhausted."""
