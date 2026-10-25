"""CLI: пакетный прогноз для проверки жюри (US-8) и бэктест.

    cashflow predict --input statements/ --out results/
    cashflow backtest --input all_operations.csv --out backtest/
    cashflow seed-demo --input statements/ --companies C009,C066,C082
    cashflow train-tabpfn --dataset gap_v2_dataset.csv --scores gap_tabpfn_scores.csv   # необязательный ML-модуль
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

import pandas as pd
import typer

from app.core.logging import setup_logging
from app.domain.categorize import train_classifier
from app.domain.forecast import fit, forecast
from app.domain.ingest import StatementFormatError, read_statement
from app.domain.pipeline import prepare_company, split_by_company

if hasattr(sys.stdout, "reconfigure"):   # консоль Windows по умолчанию в cp1251 и падает на «₽» и «→»
    sys.stdout.reconfigure(encoding="utf-8")

app = typer.Typer(add_completion=False, help="Прогноз остатка и кассовых разрывов по выпискам")
log = logging.getLogger("cashflow.cli")


def _load(path: Path) -> pd.DataFrame:
    files = sorted(path.glob("*.csv")) if path.is_dir() else [path]
    if not files:
        raise typer.BadParameter(f"В {path} нет CSV-файлов")
    frames = []
    for f in files:
        try:
            frames.append(read_statement(f.read_bytes()))
        except StatementFormatError as exc:
            log.warning("file_skipped", extra={"file": f.name, "reason": str(exc)})
    if not frames:
        raise typer.BadParameter("Ни один файл не прочитан")
    return pd.concat(frames, ignore_index=True).drop_duplicates(["company_id", "operation_id"])


@app.command()
def predict(
    input: Path = typer.Option(..., exists=True, help="CSV-файл или папка с выписками в формате кейса"),
    out: Path = typer.Option(Path("results"), help="Куда положить forecast.csv и alerts.csv"),
    horizon: int = typer.Option(30, min=5, max=90),
    sims: int = typer.Option(1000, min=100, max=10000),
    seed: int = 7,
) -> None:
    """Прогноз и разрывы по каждой компании. Не падает на плохой компании — пишет её в errors.csv."""
    setup_logging()
    started = time.perf_counter()
    raw = _load(input)
    by_company = split_by_company(raw)
    preps = {cid: prepare_company(df) for cid, df in by_company.items()}
    clf = train_classifier(pd.concat([p.ops for p in preps.values()], ignore_index=True))
    points, alerts, errors = [], [], []
    for cid, df in by_company.items():
        try:
            prep = prepare_company(df, clf)
            res = forecast(fit(prep.ops, prep.panel), [], horizon=horizon, n_sims=sims, seed=seed,
                           data_warnings=prep.quality.warnings)
        except Exception as exc:  # noqa: BLE001 — пакетный режим: одна компания не валит весь прогон
            errors.append({"company_id": cid, "error": type(exc).__name__})
            log.exception("company_failed", extra={"company_id": cid})
            continue
        points += [{"company_id": cid, "date": p.day, "p10": round(p.p10, 2), "p50": round(p.p50, 2),
                    "p90": round(p.p90, 2), "prob_below_threshold": round(p.prob_below, 3)} for p in res.points]
        alerts += [{"company_id": cid, "start_date": a.start, "end_date": a.end, "probability": round(a.probability, 3),
                    "max_shortfall": round(a.shortfall, 2), "worst_case_only": a.worst_case,
                    "causes": "; ".join(c.title for c in a.causes), "explanation": a.explanation} for a in res.alerts]
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(points).to_csv(out / "forecast.csv", index=False, encoding="utf-8-sig", sep=";")
    pd.DataFrame(alerts, columns=["company_id", "start_date", "end_date", "probability", "max_shortfall",
                                  "worst_case_only", "causes", "explanation"]).to_csv(
        out / "alerts.csv", index=False, encoding="utf-8-sig", sep=";")
    if errors:
        pd.DataFrame(errors).to_csv(out / "errors.csv", index=False)
    typer.echo(f"Компаний: {len(by_company)}, разрывов: {len(alerts)}, ошибок: {len(errors)}, "
               f"время: {time.perf_counter() - started:.1f} с → {out}")


@app.command()
def backtest(
    input: Path = typer.Option(..., exists=True),
    out: Path = typer.Option(Path("backtest")),
    holdout: float = typer.Option(0.2, help="Доля компаний, отложенных как «скрытый датасет»"),
    cutoffs: int = typer.Option(6),
    sims: int = typer.Option(300),
) -> None:
    """Rolling-origin бэктест: гибрид vs бейзлайны, метрики остатка и разрывов, отдельно dev и holdout."""
    from app.backtest.runner import BacktestConfig, backtest_company, split_holdout, summarize

    setup_logging()
    by_company = split_by_company(_load(input))
    held = split_holdout(list(by_company), holdout)
    cfg = BacktestConfig(n_cutoffs=cutoffs, n_sims=sims)
    rows = []
    with typer.progressbar(by_company.items(), label="Бэктест") as items:
        for cid, df in items:
            for r in backtest_company(prepare_company(df), cfg):
                r["group"] = "holdout" if cid in held else "dev"
                rows.append(r)
    table = pd.DataFrame(rows)
    out.mkdir(parents=True, exist_ok=True)
    table.to_csv(out / "windows.csv", index=False)
    summary = {g: summarize(table[table["group"] == g]) for g in ("dev", "holdout")} if not table.empty else {}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    typer.echo(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


@app.command("seed-demo")
def seed_demo(
    input: Path = typer.Option(..., exists=True),
    companies: str = typer.Option("C009,C066,C082", help="Какие компании загрузить демо-пользователю"),
    cutoff: str = typer.Option("", help="ГГГГ-ММ-ДД: загрузить данные до этой даты, остальное — в demo/next_*.csv"),
) -> None:
    """Создаёт демо-пользователя (логин/пароль из CASHFLOW_DEMO_USER / CASHFLOW_DEMO_PASSWORD) и загружает выписки.

    С --cutoff демо разыгрывается как в жизни: прогноз строится «на дату отсечки», а следующую неделю выписки
    загружаем на вкладке «План-факт» и видим, что пришло, а что нет.
    """
    from app.services.demo import seed, to_csv

    setup_logging()
    raw = _load(input)
    wanted = {c.strip() for c in companies.split(",") if c.strip()}
    raw = raw[raw["company_id"].isin(wanted)]
    if cutoff:
        cut = pd.Timestamp(cutoff)
        Path("demo").mkdir(exist_ok=True)
        for cid, rest in raw[raw["operation_date"] > cut].groupby("company_id"):
            nxt = rest[rest["operation_date"] <= cut + pd.Timedelta(days=7)]
            (Path("demo") / f"next_week_{cid}.csv").write_bytes(to_csv(nxt))
        raw = raw[raw["operation_date"] <= cut]
    n = seed(raw)
    typer.echo(f"Загружено компаний: {n}")


@app.command("train-classifier")
def train_classifier_cmd(input: Path = typer.Option(..., exists=True)) -> None:
    """Обучает ML-слой категоризации на всём датасете и сохраняет в models/classifier.pkl (для API)."""
    from app.services.classifier import save_classifier

    setup_logging()
    preps = [prepare_company(df) for df in split_by_company(_load(input)).values()]
    path = save_classifier(train_classifier(pd.concat([p.ops for p in preps], ignore_index=True)))
    typer.echo(f"Классификатор сохранён: {path}")


@app.command("train-tabpfn")
def train_tabpfn_cmd(
    dataset: Path = typer.Option(..., exists=True, help="Выборка признаков эксперимента: analytics/experiments/out/gap_v2_dataset.csv"),
    scores: Path = typer.Option(None, exists=True, help="Прогнозы вне обучения (gap_tabpfn_scores.csv): из них берутся пороги тревоги"),
    results: Path = typer.Option(None, exists=True, help="Метрики проверки (gap_tabpfn.json): показываются рядом с оценкой"),
    out: Path = typer.Option(Path("models/tabpfn_gap"), help="Куда положить train.csv и meta.json"),
    rows: int = typer.Option(10_000, min=500, max=10_000, help="Сколько обучающих строк хранить (TabPFN рассчитан на ~10 000)"),
) -> None:
    """Готовит файлы для ML-оценки риска разрыва (TabPFN). Сам TabPFN здесь не нужен: он подключается при первом запросе."""
    from datetime import date

    from sklearn.metrics import f1_score, precision_recall_curve

    from app.domain.gap_features import FEATURES, HORIZONS

    df = pd.read_csv(dataset)
    industries = sorted(df["industry"].dropna().unique().tolist())
    df["industry_code"] = df["industry"].map({name: i for i, name in enumerate(industries)})
    train = df.sample(n=min(rows, len(df)), random_state=7)[FEATURES + ["y"]]
    thresholds: dict[str, dict[str, float]] = {}
    if scores is not None:
        sc = pd.read_csv(scores)
        grid = [round(0.03 + 0.02 * i, 2) for i in range(47)]
        for h in HORIZONS:
            d = sc[sc["h"] == h]
            balanced = max(grid, key=lambda t: f1_score(d["y"], d["score"] >= t))
            p, r, t = precision_recall_curve(d["y"], d["score"])
            ok = [i for i in range(len(t)) if r[i] >= 0.8]
            high_recall = float(t[max(ok, key=lambda i: p[i])]) if ok else balanced
            thresholds[str(h)] = {"balanced": balanced, "high_recall": round(high_recall, 3)}
    meta = {"model": "TabPFN v2 (Prior Labs, лицензия Apache 2.0 с указанием автора)", "features": FEATURES, "industries": industries,
            "thresholds": thresholds, "trained_rows": len(train), "created": date.today().isoformat(),
            "cv": json.loads(results.read_text(encoding="utf-8")) if results is not None else None,
            "note": "Пороги подобраны по прогнозам вне обучения (кросс-валидация по компаниям)."}
    out.mkdir(parents=True, exist_ok=True)
    train.to_csv(out / "train.csv", index=False)
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    typer.echo(f"Готово: {out}  (строк {len(train):,}, отраслей {len(industries)}, пороги: {'есть' if thresholds else 'нет'})")


if __name__ == "__main__":
    app()
