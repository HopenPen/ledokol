"""Категоризация в три слоя: правила → история контрагента → ML для незнакомых формулировок.

EDA: правила покрывают 99,99% операций датасета. ML-слой нужен для скрытого датасета жюри, где формулировки
могут отличаться, и как второй подход для сравнения в презентации.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

_IN_RULES: list[tuple[str, str]] = [
    ("acquiring", r"эквайринг"),
    ("sbp", r"\bСБП\b"),
    ("cash", r"взнос наличных|инкасс"),
    ("marketplace", r"договору? оферты.*за период|маркетплейс"),
    ("owner_in", r"займ|задолженности по овердрафту|уставн"),
    ("loan_in", r"выдач[аи] кредит|предоставлени[ея] кредит|зачислени[ея] кредит|транш"),
    ("own_transfer_in", r"собственн|с расчетного счета в"),
    ("refund_in", r"возврат|ошибочн"),
    ("subsidy", r"субсид|грант|страхов"),
    ("client_payment", r"оплат|предоплат|расчет|аванс|доплат|агентск|по договору|по счету|упд"),
]
_OUT_RULES: list[tuple[str, str]] = [
    ("tax", r"единый налог|\bЕНП\b|налогов|страховые взносы|пени|штраф"),
    ("enforcement", r"исполнительн"),
    ("salary", r"заработн|зарплат|отпускн|больничн"),
    ("gph", r"ГПХ|самозанят"),
    ("owner_out", r"дивиденд|личн|на счет физического лица|займа учредител|подотчет"),
    ("bank_fees", r"комисси|POS-терминал|ведени[ея] счета|расчетно-кассов"),
    ("loan_payment", r"кредит|овердрафт|процент"),
    ("leasing", r"лизинг"),
    ("rent", r"аренд"),
    ("utilities", r"электроэнерг|водоснабж|водоотвед|ТКО|теплоснабж|отоплен|газоснабж"),
    ("own_transfer_out", r"собственн"),
    ("refund_out", r"возврат|ошибочн"),
    ("marketing", r"реклам|продвижен"),
    ("it_accounting", r"связи|интернет|(?-i:\bПО\b)|программ|бухгалт|(?-i:1С)|подписк|облачн"),
    ("logistics", r"топлив|провоз|транспорт|экспедиц|ГСМ|бензин|перевозк"),
    ("facility", r"охран|уборк|клининг|канцтовар|хозтовар"),
    ("capex", r"ремонт|оборудован|монтаж"),
    ("suppliers", r"УПД|поставк|товар|продукт|продукц|материал|сырь|запчаст|оплата по счету|субподряд|изделия"),
]
_COMPILED = {
    "in": [(c, re.compile(p, re.I)) for c, p in _IN_RULES],
    "out": [(c, re.compile(p, re.I)) for c, p in _OUT_RULES],
}


def rule_category(direction: str, purpose: str) -> str | None:
    """None — назначение пустое; 'other' — ни одно правило не сработало."""
    if not purpose:
        return None
    for code, rx in _COMPILED[direction]:
        if rx.search(purpose):
            return code
    return "other"


@dataclass(slots=True)
class TextClassifier:
    """TF-IDF по символьным n-граммам + логистическая регрессия. Учится на разметке правил."""

    pipeline: object | None = None
    min_confidence: float = 0.6

    def fit(self, texts: pd.Series, labels: pd.Series) -> TextClassifier:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline

        if labels.nunique() < 2:
            return self
        self.pipeline = make_pipeline(
            TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, max_features=50_000),
            LogisticRegression(max_iter=300, C=4.0),
        )
        self.pipeline.fit(texts, labels)
        return self

    def predict(self, texts: pd.Series) -> tuple[np.ndarray, np.ndarray]:
        if self.pipeline is None or texts.empty:
            return np.array(["other"] * len(texts)), np.zeros(len(texts))
        proba = self.pipeline.predict_proba(texts)
        idx = proba.argmax(axis=1)
        return self.pipeline.classes_[idx], proba.max(axis=1)


def categorize(ops: pd.DataFrame, classifier: TextClassifier | None = None) -> pd.DataFrame:
    """Добавляет category, category_source ('rule'|'counterparty'|'ml'|'none') и confidence."""
    ops = ops.copy()
    ops["category"] = [rule_category(d, p) for d, p in zip(ops["direction"], ops["payment_purpose"])]
    ops["category_source"] = np.where(ops["category"].notna(), "rule", "none")
    ops["confidence"] = np.where(ops["category"].notna(), 1.0, 0.0)

    # Слой 2: пустое назначение или «Прочее» → самая частая категория этого контрагента в этом направлении.
    known = ops[ops["category"].notna() & ops["category"].ne("other")]
    if not known.empty:
        mode = known.groupby(["direction", "cp_key"])["category"].agg(lambda s: s.value_counts().index[0])
        need = ops["category"].isna() | ops["category"].eq("other")
        filled = ops.loc[need].join(mode.rename("cp_cat"), on=["direction", "cp_key"])["cp_cat"].dropna()
        ops.loc[filled.index, "category"] = filled
        ops.loc[filled.index, "category_source"] = "counterparty"
        ops.loc[filled.index, "confidence"] = 0.9

    # Слой 3: ML по тексту для оставшегося «Прочего» с непустым назначением.
    if classifier is not None:
        rest = ops["category"].eq("other") & ops["payment_purpose"].ne("")
        if rest.any():
            text = ops.loc[rest, "direction"] + " " + ops.loc[rest, "payment_purpose"]
            pred, conf = classifier.predict(text)
            ok = conf >= classifier.min_confidence
            idx = ops.index[rest][ok]
            ops.loc[idx, "category"] = pred[ok]
            ops.loc[idx, "category_source"] = "ml"
            ops.loc[idx, "confidence"] = conf[ok]

    ops["category"] = ops["category"].fillna("unknown")
    ops["confidence"] = ops["confidence"].astype(float)
    return ops


def train_classifier(ops: pd.DataFrame) -> TextClassifier:
    """Учим ML-слой на операциях, размеченных правилами (без «Прочего»)."""
    lab = ops[ops["category_source"].eq("rule") & ops["category"].ne("other")]
    if len(lab) > 50_000:
        # Балансируем классы: не больше 3000 примеров на категорию (эквайринга десятки тысяч, лизинга — сотни).
        lab = lab.sample(frac=1.0, random_state=0).groupby("category").head(3000)
    return TextClassifier().fit(lab["direction"] + " " + lab["payment_purpose"], lab["category"])
