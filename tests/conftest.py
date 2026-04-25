"""Shared pytest configuration. DB fixtures will be added in Task 1."""

from __future__ import annotations

from dotenv import load_dotenv

# Load .env at test session start so MOONSHOT_API_KEY etc. are available.
load_dotenv()
