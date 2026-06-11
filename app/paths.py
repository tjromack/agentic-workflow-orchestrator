"""Shared filesystem locations. One source of truth for where data lives."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
CORPUS_DIR = DATA_DIR / "corpus"
SEED_GOALS = DATA_DIR / "demo_goals.seed.json"
