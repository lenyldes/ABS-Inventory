"""Пакет начальных данных (сидов) приложения."""

from app.seeds.data import (
    SEED_CONDITIONS,
    SEED_ITEMS,
    SEED_LOCATIONS,
    SEED_SUPPLIERS,
)
from app.seeds.loader import load_seeds

__all__ = [
    "SEED_CONDITIONS",
    "SEED_ITEMS",
    "SEED_LOCATIONS",
    "SEED_SUPPLIERS",
    "load_seeds",
]
