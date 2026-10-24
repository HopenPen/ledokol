"""Механика смешивания внешних данных с кейсом: без масштаба, с весами, с отбором похожих окон."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.domain.ml_flow import adversarial_filter, make_rows, mix_weights


def _flow(seed: int, scale: float = 1.0, shift: float = 0.0, n: int = 200) -> pd.Series:
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2025-01-01", periods=n)
    base = np.where(days.day_of_week == 0, 3.0, 1.0)            # понедельник ×3, как в кейсе
    return pd.Series((base + rng.normal(0, 0.3, n) + shift) * scale, index=days)


def test_rows_do_not_depend_on_company_scale():
    small = make_rows(_flow(1, scale=50_000), "Общепит")
    big = make_rows(_flow(1, scale=50_000_000), "Общепит")
    num = small.select_dtypes("number").columns
    assert np.allclose(small[num], big[num])


def test_case_keeps_half_of_total_weight_even_when_outnumbered():
    rows = pd.DataFrame({"source": ["case"] * 100 + ["mbd"] * 10_000})
    w = mix_weights(rows, case_share=0.5)
    case_share = w[rows["source"] == "case"].sum() / w.sum()
    assert abs(case_share - 0.5) < 1e-9


def test_external_rows_never_outweigh_case_rows_individually():
    rows = pd.DataFrame({"source": ["case"] * 100 + ["mbd"] * 10})   # внешних меньше — не раздуваем их вес
    assert mix_weights(rows).max() == 1.0


def test_adversarial_filter_drops_unlike_windows_keeps_like_ones():
    case = pd.concat([make_rows(_flow(s), "Опт", company=f"c{s}") for s in range(6)], ignore_index=True)
    like = pd.concat([make_rows(_flow(100 + s), "Опт", source="mbd", company=f"l{s}") for s in range(6)],
                     ignore_index=True)
    unlike = pd.concat([make_rows(_flow(200 + s, shift=-5.0), "Опт", source="mbd", company=f"u{s}")
                        for s in range(6)], ignore_index=True)
    kept_like = len(adversarial_filter(case, like)) / len(like)
    kept_unlike = len(adversarial_filter(case, unlike)) / len(unlike)
    assert kept_like > 0.7 and kept_unlike < 0.1
