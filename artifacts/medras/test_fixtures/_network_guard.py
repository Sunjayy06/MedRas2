"""Shared test guard: block real OpenRouter/OpenAI network calls.

The Sigma test suite must never make a live OpenRouter request, even when a
developer's local ``.env`` has a real ``OPENROUTER_API_KEY`` and
``SIGMA_AI_POLISH_ENABLED=true``. ``openrouter_client.chat_completion``
deliberately swallows every exception (including ones raised by this guard)
and returns ``None`` so production export never breaks — which means a
forgotten test mock would otherwise fail *silently* (the test would just see
an empty/deterministic result and pass). This guard makes that failure loud:
it patches the ``openai.OpenAI`` constructor for the duration of a test run
and counts any attempt to construct a real client; callers assert the count
is zero once the run finishes.

Tests that want to exercise a specific mocked OpenRouter response should
nest their own ``patch("openai.OpenAI", ...)`` inside this guard's ``with``
block — the inner patch takes precedence while active, and the guard
resumes once that inner ``with`` block exits.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch


class NetworkCallAttempted(AssertionError):
    pass


class _RealNetworkGuard:
    def __init__(self) -> None:
        self.attempts = 0

    def __call__(self, *args, **kwargs):
        self.attempts += 1
        raise NetworkCallAttempted(
            "Test attempted a real OpenAI/OpenRouter network call "
            "(openai.OpenAI(...) was constructed without a test mock). "
            "The test suite must never hit the live network — mock "
            "openai.OpenAI (or app.services.openrouter_client.chat_completion) "
            "for this test."
        )


@contextmanager
def block_real_openrouter_calls():
    """Patch openai.OpenAI for the duration of the block; assert no real
    construction attempt slipped through once the block exits.

    Use this around an entire test module's ``main()`` so every test in the
    file is covered, including ones that forget to mock OpenRouter
    themselves. Tests that *do* want a mocked OpenRouter response should
    apply their own nested ``patch("openai.OpenAI", ...)``.
    """
    guard = _RealNetworkGuard()
    with patch("openai.OpenAI", side_effect=guard):
        yield guard
    assert guard.attempts == 0, (
        f"{guard.attempts} real OpenAI/OpenRouter client construction attempt(s) "
        "were made during this test run without being mocked."
    )
