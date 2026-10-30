"""How a step fails decides whether Dagu retries it: the CLI maps these to exit codes."""


class StepError(RuntimeError):
    """Might work on a retry: a network error, a flaky download. Exit 1."""


class NeedsPerson(StepError):
    """Retrying won't help until someone changes something on the page. Exit 2."""
