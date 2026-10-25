"""Подключение предобученной модели TabPFN v2 для оценки риска разрыва (без БД и HTTP).

Модель обучается «в контексте»: при первом запросе читаются обучающие строки из models/tabpfn_gap/train.csv и
передаются в TabPFN, дообучения весов нет. Если файлов или пакета tabpfn нет, бросается MlUnavailable с понятным текстом.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from app.core.config import get_settings
from app.domain.gap_features import FEATURES

log = logging.getLogger("cashflow.ml_risk")
_lock = threading.RLock()
_cache: dict[str, GapPredictor] = {}

# Те же параметры, с которыми считались признаки при обучении (analytics/experiments/gap_classifier_v2.py).
FORECAST_SIMS, FORECAST_SEED = 150, 7


class MlUnavailable(Exception):
    """Модуль нельзя использовать: нет файлов обучения, пакета tabpfn или весов. Текст показываем пользователю."""


@dataclass
class GapPredictor:
    clf: object
    meta: dict
    device: str

    def industry_code(self, industry: str | None) -> float:
        names = self.meta.get("industries", [])
        return float(names.index(industry)) if industry in names else float("nan")   # неизвестная отрасль — как пропуск

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        with _lock:
            return self.clf.predict_proba(features[FEATURES].to_numpy(dtype=float))[:, 1]


def get_predictor() -> GapPredictor:
    """Загружает обучающую выборку и подключает TabPFN один раз за жизнь процесса."""
    s = get_settings()
    folder = Path(s.ml_gap_dir)
    key = str(folder.resolve())
    with _lock:
        if key in _cache:
            return _cache[key]
        meta_path, train_path = folder / "meta.json", folder / "train.csv"
        if not (meta_path.exists() and train_path.exists()):
            raise MlUnavailable("ML-модель не обучена: нет файлов в папке модели. Запустите `cashflow train-tabpfn`.")
        try:
            import torch
            from tabpfn import TabPFNClassifier
            from tabpfn.constants import ModelVersion
        except ImportError as exc:
            raise MlUnavailable("Не установлен пакет tabpfn (см. backend/requirements-tabpfn.txt).") from exc
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        train = pd.read_csv(train_path)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cpu" and len(train) > s.ml_gap_cpu_rows:
            train = train.sample(n=s.ml_gap_cpu_rows, random_state=7)
        try:
            # Веса v2 берём явно: лицензия Apache 2.0 с указанием автора. Новые версии весов некоммерческие.
            clf = TabPFNClassifier.create_default_for_version(
                ModelVersion.V2, device=device, categorical_features_indices=[FEATURES.index("industry_code")],
                random_state=7, n_estimators=8 if device == "cuda" else 4)
            clf.fit(train[FEATURES].to_numpy(dtype=float), train["y"].to_numpy())
        except Exception as exc:  # noqa: BLE001 — скачивание весов, память видеокарты и т.п.: наружу общий текст
            log.exception("tabpfn_init_failed", extra={"reason": type(exc).__name__})
            raise MlUnavailable("Не удалось подключить модель TabPFN (проверьте доступ к весам и память).") from exc
        _cache[key] = GapPredictor(clf=clf, meta=meta, device=device)
        log.info("tabpfn_ready", extra={"device": device, "rows": len(train)})
        return _cache[key]
