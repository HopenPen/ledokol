"""ML-слой категоризации для API. Обучается командой `cashflow train-classifier` на всём датасете и
кладётся файлом; если файла нет — работаем на правилах и истории контрагента (их хватает на 99,99% данных кейса).
"""
from __future__ import annotations

import pickle
from functools import lru_cache
from pathlib import Path

from app.domain.categorize import TextClassifier

MODEL_PATH = Path("models/classifier.pkl")


@lru_cache(maxsize=1)
def get_classifier() -> TextClassifier | None:
    if not MODEL_PATH.exists():
        return None
    # pickle грузим только свой файл, собранный нашим же CLI; пользовательские файлы сюда не попадают.
    with MODEL_PATH.open("rb") as f:
        return pickle.load(f)  # noqa: S301


def save_classifier(clf: TextClassifier) -> Path:
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MODEL_PATH.open("wb") as f:
        pickle.dump(clf, f)
    get_classifier.cache_clear()
    return MODEL_PATH
