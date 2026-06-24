"""Pytest setup shared across the test suite."""

from __future__ import annotations

import os

# server.py validates keys at import time; unit tests mock HTTP clients instead.
os.environ.setdefault(
    "CARTESIA_API_KEY",
    "sk_car_testId1234567890ab.secretPartHere1234567890abcdefghij",
)
