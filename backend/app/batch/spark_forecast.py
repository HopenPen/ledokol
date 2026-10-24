"""Масштабирование на весь клиентский портфель банка: тот же доменный код, но в Spark.

Зачем: на данных кейса (150 компаний, 222 тыс. строк) pandas считает всё за минуту, Spark здесь только медленнее
(JVM, сериализация). Но прогноз каждой компании независим, поэтому для сотен тысяч клиентов банка задача
параллелится «по компаниям» без переписывания логики: groupBy(company_id).applyInPandas(наша функция).

Запуск (нужны Java 17+ и `uv add pyspark`):
    spark-submit app/batch/spark_forecast.py --input s3://.../operations/ --output s3://.../forecasts/

Статус: задел для слайда «архитектура и масштабирование», в прототипе не используется (см. TODO.md).
"""
from __future__ import annotations

import argparse

import pandas as pd

from app.domain.forecast import fit, forecast
from app.domain.ingest import normalize
from app.domain.pipeline import prepare_company

OUTPUT_SCHEMA = "company_id string, date date, p10 double, p50 double, p90 double, prob_below double"


def forecast_one_company(raw: pd.DataFrame) -> pd.DataFrame:
    """pandas-функция на одну компанию: ровно то, что делает CLI `cashflow predict` для одной выписки."""
    ops = normalize(raw.astype(str))
    if ops.empty:
        return pd.DataFrame(columns=["company_id", "date", "p10", "p50", "p90", "prob_below"])
    prep = prepare_company(ops)
    res = forecast(fit(prep.ops, prep.panel), n_sims=500)
    return pd.DataFrame([{"company_id": prep.company_id, "date": p.day, "p10": p.p10, "p50": p.p50, "p90": p.p90,
                          "prob_below": p.prob_below} for p in res.points])


def main() -> None:  # pragma: no cover — требует Spark
    from pyspark.sql import SparkSession

    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    spark = SparkSession.builder.appName("cashflow-forecast").getOrCreate()
    ops = spark.read.option("header", True).option("sep", ";").option("encoding", "UTF-8").csv(args.input)
    # Все колонки читаем строками (ИНН с ведущими нулями!), типы приводит normalize().
    result = ops.groupBy("company_id").applyInPandas(forecast_one_company, schema=OUTPUT_SCHEMA)
    result.write.mode("overwrite").partitionBy("company_id").parquet(args.output)


if __name__ == "__main__":
    main()
