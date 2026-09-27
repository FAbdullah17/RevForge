"""Hermetic suite: mock transports regardless of the local .env.

Live runs (G8_LIVE=1) intentionally opt out so live-gated tests exercise
the real transport.
"""
import os

if os.getenv("G8_LIVE") != "1":
    os.environ["MOCK_GRAPH8"] = "1"
os.environ["MOCK_LLM"] = "1"
