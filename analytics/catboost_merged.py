# %% [markdown]
# # CatBoost для прогноза дневного потока: кейс + российские внешние данные
#
# **Задача.** Прогноз «шумной» части дневного потока денег компании на 30 рабочих дней. Известные события
# (регулярные платежи, налоги, счета) прогноз добавляет поверх, как в гибриде, — модель их не учит.
#
# **Две модели, а не одна** — иначе скрытый перекос по цели:
# - **B — розничная выручка** (эквайринг, СБП, наличные, маркетплейсы): кейс + продажи 1С (в 1С есть только
#   выручка, без расходов — смешивать её с чистым потоком нельзя);
# - **C — прочий чистый поток** (B2B без счёта, закупки и т.п.): кейс.
# - Поток = B + C, складываем **в рублях** (каждая цель нормирована на свой оборот).
#
# **Внешние данные — только РФ.** MBD (Сбер) проверяем на пригодность и **не смешиваем**: в нём нет направления
# денег, а даты при обезличивании перемешаны на уровне дней (раздел 2 — проверка с цифрами). Он испортил бы
# самые сильные признаки (день недели, 28-е число). Продажи 1С — с настоящими датами — берём для модели B.
#
# **Защита от дисбаланса и утечек:**
# 1. цель и признаки — в долях обычного оборота компании, а не в рублях;
# 2. признак `source`; при прогнозе для нас всегда `source=case`;
# 3. внешние окна — через фильтр похожести (adversarial validation по компаниям);
# 4. вес кейса ≥ 50%, внешних строк — не больше двух объёмов кейса;
# 5. выбросы цели обрезаются по квантилям **обучающей части кейса**;
# 6. тест — компании кейса, которых модель не видела, и только даты после разреза; признаки — только из прошлого;
#    регулярные платежи ищем по данным до разреза; ранняя остановка — по отдельной валидации;
# 7. несколько сидов → среднее; интервалы метрик — бутстрепом по компаниям.

# %%
import glob
import json
import os
import subprocess
import sys
import time
import warnings
import zipfile

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
IN_COLAB = "google.colab" in sys.modules

if IN_COLAB:
    subprocess.run([sys.executable, "-m", "pip", "-q", "install", "catboost", "pyarrow", "kaggle"], check=True)
    if not os.path.exists("ledokol"):
        subprocess.run(["git", "clone", "--depth", "1", "https://github.com/HopenPen/ledokol.git"], check=True)
    sys.path.insert(0, "ledokol/backend")
else:  # локально: ноутбук лежит в analytics/ рядом с backend/
    for p in ("../backend", "backend"):
        sys.path.insert(0, os.path.abspath(p))

from catboost import CatBoostRegressor, Pool  # noqa: E402

from app.domain.calendar import is_working_day, next_working_day  # noqa: E402
from app.domain.categories import EXCLUDED_FROM_FORECAST, RETAIL  # noqa: E402
from app.domain.ingest import read_statement  # noqa: E402
from app.domain.ml_flow import NON_FEATURES, adversarial_filter, make_rows, mix_weights  # noqa: E402
from app.domain.pipeline import prepare_company, split_by_company  # noqa: E402
from app.domain.recurring import detect_recurring  # noqa: E402

# %% [markdown]
# ## Настройки
# Все «ручки» в одном месте. По умолчанию ноутбук укладывается в бесплатный Colab (CPU).

# %%
CFG = {
    "horizon": 30,
    "train_horizons": [1, 2, 3, 4, 5, 7, 10, 14, 20, 25, 30],   # для обучения хватает выборки горизонтов
    "train_end": "2026-04-30",        # разрез по времени: обучение — отсечки до, тест — после
    "case_step": 2,                   # шаг отсечек по кейсу (больше окон без сдвига распределения)
    "ext_step": 7,                    # шаг отсечек по внешним данным
    "min_history": 60,
    "test_frac": 0.2, "val_frac": 0.15,
    "case_share": 0.5,                # минимальная доля веса кейса
    "ext_rows_max_ratio": 2.0,        # внешних строк — не больше двух объёмов кейса
    "max_p_external": 0.8,            # порог фильтра похожести
    "clip_q": (0.005, 0.995),         # обрезка выбросов цели по обучающей части кейса
    "seeds": [7, 42, 2026],
    "iterations": 3000, "learning_rate": 0.05, "depth": 6, "l2_leaf_reg": 5.0, "od_wait": 200,
}
CFG.update(json.loads(os.environ.get("CFG_OVERRIDES", "{}")))   # быстрый прогон: CFG_OVERRIDES='{"seeds":[7]}'
QUANTILES = (0.1, 0.5, 0.9)
LOSS = "MultiQuantile:alpha=" + ",".join(map(str, QUANTILES))
CAT_FEATURES = ["industry", "target_dow", "source"]
TRAIN_END = pd.Timestamp(CFG["train_end"])
OUT = "catboost_out"
os.makedirs(OUT, exist_ok=True)

# %% [markdown]
# ## 1. Данные кейса
# Загрузите `cashflow_dataset_participants.zip` (или задайте путь к распакованной папке в `CASE_DIR`).

# %%
def find_case_dir() -> str | None:
    for base in [os.environ.get("CASE_DIR", ""), ".", "data", "/content", "/content/data", "../data"]:
        if base and os.path.isdir(base):
            hits = glob.glob(os.path.join(base, "**", "all_operations.csv"), recursive=True)
            if hits:
                return os.path.dirname(hits[0])
    return None


root = find_case_dir()
if root is None:
    zips = glob.glob("*.zip") + glob.glob("/content/*.zip")
    if not zips and IN_COLAB:
        from google.colab import files
        zips = [k for k in files.upload() if k.endswith(".zip")]
    for z in zips:
        zipfile.ZipFile(z).extractall("data")
    root = find_case_dir()
assert root, "Не найден all_operations.csv"
raw = read_statement(open(os.path.join(root, "all_operations.csv"), "rb").read())
companies = pd.read_csv(os.path.join(root, "companies.csv"), sep=";", encoding="utf-8-sig", dtype=str)
INDUSTRY = dict(zip(companies["company_id"], companies["industry"]))
print(f"Кейс: {raw['company_id'].nunique()} компаний, {len(raw):,} операций")

# %% [markdown]
# ### Потоки B и C
# C — всё, кроме розницы, денег владельца, переводов между своими счетами, налогов и **регулярных платежей**
# (их прогноз ставит поштучно). Регулярные платежи ищем только по данным **до** `train_end` — без утечки.

# %%
case_flows = {}
t0 = time.time()
for cid, df in split_by_company(raw).items():
    prep = prepare_company(df)
    good = prep.ops[prep.ops["quality"].isin(["ok", "after_gap"])]
    as_of = min(TRAIN_END, prep.panel["date"].iloc[-1]).date()
    members = {i for s in detect_recurring(good, as_of) for i in s.member_index}
    days = pd.DatetimeIndex(prep.panel["date"])
    is_b = good["category"].isin(RETAIL)
    is_c = ~is_b & ~good["category"].isin(EXCLUDED_FROM_FORECAST | {"tax"}) & ~good.index.isin(list(members))
    b = good[is_b].groupby("operation_date")["signed"].sum().reindex(days, fill_value=0.0)
    c = good[is_c].groupby("operation_date")["signed"].sum().reindex(days, fill_value=0.0)
    inflow = good.loc[good["direction"].eq("in"), "amount"].sum()
    case_flows[cid] = {"B": b, "C": c, "after_gap": prep.panel["after_gap"].to_numpy(),
                       "industry": INDUSTRY.get(cid, "unknown"),
                       "retail_share": float(b.clip(lower=0).sum() / inflow) if inflow else 0.0}
print(f"Потоки посчитаны за {time.time() - t0:.0f} с; компаний с заметной розницей: "
      f"{sum(f['retail_share'] >= 0.05 for f in case_flows.values())}")

# %% [markdown]
# ### Разбиение компаний: train / val / test, стратифицировано по отраслям

# %%
rng = np.random.default_rng(2026)
split = {}
for _, grp in pd.Series(INDUSTRY).groupby(lambda c: INDUSTRY[c]):
    ids = sorted(c for c in grp.index if c in case_flows)
    rng.shuffle(ids)
    n_test, n_val = max(1, round(len(ids) * CFG["test_frac"])), max(1, round(len(ids) * CFG["val_frac"]))
    for i, c in enumerate(ids):
        split[c] = "test" if i < n_test else "val" if i < n_test + n_val else "train"
print(pd.Series(split).value_counts().to_dict())


def case_rows(target: str, part: str, horizons=None) -> pd.DataFrame:
    """Строки кейса для B или C. Розничная модель — только компании с розницей ≥ 5% поступлений."""
    frames = []
    for cid, f in case_flows.items():
        if split[cid] != part or (target == "B" and f["retail_share"] < 0.05):
            continue
        window = (pd.Timestamp.min, TRAIN_END) if part != "test" else (TRAIN_END + pd.Timedelta(days=1), pd.Timestamp.max)
        frames.append(make_rows(f[target], f["industry"], horizon=CFG["horizon"], step=CFG["case_step"],
                                min_history=CFG["min_history"], after_gap=f["after_gap"], source="case", company=cid,
                                horizons=horizons, cutoff_range=window))
    return pd.concat([f for f in frames if len(f)], ignore_index=True)


rows = {t: {"train": case_rows(t, "train", CFG["train_horizons"]), "val": case_rows(t, "val", CFG["train_horizons"]),
            "test": case_rows(t, "test")} for t in ("B", "C")}
for t in rows:
    print(t, {k: f"{len(v):,} строк / {v['company'].nunique()} компаний" for k, v in rows[t].items()})

# %% [markdown]
# ## 2. MBD (Сбер): проверка пригодности — и почему не смешиваем
#
# Перед тем как смешивать чужие данные, проверяем, что в них сохранились закономерности, на которых держится
# наш прогноз. У настоящих юрлиц почти все платежи — в будни, с пиками в определённые числа (зарплата,
# налоги 28-го). Если даты перемешаны, на выходные придётся ровно 2/7 ≈ 28,6% операций, а по дням месяца —
# ровно ~1/30 на каждый день.
#
# **Результат на MBD-mini (4 млн транзакций, 9,7 тыс. клиентов):** выходные — 29,2%, максимум по дню месяца
# у любого типа операций — 3,4–3,7%. Распределение равномерное: в статье MBD сказано, что к датам добавлен
# случайный шум («сохраняя час»). Вдобавок суммы все положительные, направление денег не раскрыто.
# **Вывод:** для дневной модели MBD вреден — не смешиваем. Ячейка ниже повторяет проверку, если MBD скачан
# (`MBD_TRX_DIR`), иначе пропускается.

# %%
def check_mbd_calendar(trx_dir: str, max_files: int = 40) -> dict | None:
    files = sorted(glob.glob(os.path.join(trx_dir, "fold=0", "*.parquet")))[:max_files]
    if not files:
        print("MBD не найден — проверка пропущена (результат см. в тексте выше)")
        return None
    t = pd.concat([pd.read_parquet(f, columns=["event_time", "event_type", "amount"]) for f in files])
    dow = t["event_time"].dt.day_of_week
    big_types = t["event_type"].value_counts()
    big_types = big_types[big_types >= 1000].index          # редкие типы дают случайные пики — не смотрим
    dom_max = t[t["event_type"].isin(big_types)].groupby("event_type")["event_time"].apply(
        lambda s: s.dt.day.value_counts(normalize=True).max())
    res = {"транзакций": len(t), "доля выходных": round(float((dow >= 5).mean()), 3),
           "равномерно было бы": round(2 / 7, 3), "макс. доля дня месяца (типы ≥1000 операций)": round(float(dom_max.max()), 3), "равномерно ~": round(1 / 30, 3),
           "доля отрицательных сумм": round(float((t["amount"] < 0).mean()), 3)}
    print(res)
    return res


mbd_check = check_mbd_calendar(os.environ.get("MBD_TRX_DIR", "mbd/detail/trx"))

# %% [markdown]
# ## 3. Продажи 1С → модель B (по желанию)
# Нужен `kaggle.json` (Kaggle → Settings → API → Create New Token) и принятые правила соревнования.
# Нет файла — шаг пропускается, ноутбук работает дальше на кейсе.

# %%
def load_1c_daily() -> dict[str, pd.Series]:
    """Выручка «магазин × рабочий день» = Σ цена × количество; продажи выходного дня — на ближайший рабочий
    (как зачисление эквайринга в выписке)."""
    path = glob.glob("**/sales_train.csv", recursive=True)
    if not path:
        token = "kaggle.json" if os.path.exists("kaggle.json") else os.path.expanduser("~/.kaggle/kaggle.json")
        if not os.path.exists(token):
            print("1С: нет kaggle.json и sales_train.csv — пропускаем")
            return {}
        os.makedirs(os.path.expanduser("~/.kaggle"), exist_ok=True)
        if token == "kaggle.json":
            os.replace("kaggle.json", os.path.expanduser("~/.kaggle/kaggle.json"))
        subprocess.run(["kaggle", "competitions", "download", "-c", "competitive-data-science-predict-future-sales",
                        "-f", "sales_train.csv", "-p", "1c"], check=False)
        for z in glob.glob("1c/*.zip"):
            zipfile.ZipFile(z).extractall("1c")
        path = glob.glob("**/sales_train.csv", recursive=True)
        if not path:
            print("1С: скачать не удалось — примите правила соревнования на Kaggle")
            return {}
    s = pd.read_csv(path[0])
    s["date"] = pd.to_datetime(s["date"], format="%d.%m.%Y")
    s["revenue"] = s["item_price"].clip(lower=0) * s["item_cnt_day"]
    s["date"] = s["date"].map(lambda d: pd.Timestamp(next_working_day(d.date())))
    out = {}
    for shop, g in s.groupby("shop_id"):
        daily = g.groupby("date")["revenue"].sum()
        days = pd.DatetimeIndex([d for d in pd.date_range(daily.index.min(), daily.index.max()) if is_working_day(d.date())])
        series = daily.reindex(days, fill_value=0.0)
        if len(series) > 250 and (series > 0).mean() > 0.8:      # только «живые» магазины без долгих закрытий
            out[f"1c_{shop}"] = series
    print(f"1С: магазинов {len(out)}")
    return out


def external_rows(flows: dict[str, pd.Series], source: str, industry: str, target: str) -> pd.DataFrame:
    """Внешние строки: фильтр похожести на обучающий кейс + лимит объёма по КОМПАНИЯМ (окна не рвём)."""
    frames = [make_rows(sr, industry, horizon=CFG["horizon"], step=CFG["ext_step"], min_history=CFG["min_history"],
                        source=source, company=cid, horizons=CFG["train_horizons"]) for cid, sr in flows.items()]
    ext = pd.concat([f for f in frames if len(f)], ignore_index=True)
    before = ext["company"].nunique()
    ext = adversarial_filter(rows[target]["train"], ext, max_p_external=CFG["max_p_external"])
    cap = int(CFG["ext_rows_max_ratio"] * len(rows[target]["train"]))
    if len(ext) > cap:
        order = ext["company"].drop_duplicates().sample(frac=1.0, random_state=7)
        per = ext.groupby("company").size().reindex(order)
        ext = ext[ext["company"].isin(per.index[per.cumsum() <= cap])]
    print(f"{source}: компаний {before} → после фильтра и лимита {ext['company'].nunique()}, строк {len(ext):,}")
    return ext


onec = load_1c_daily()
ext_b = external_rows(onec, "1c_retail", "Розница (1С)", "B") if onec else pd.DataFrame()

# %% [markdown]
# ## 4. Обучение
# CatBoost MultiQuantile (P10/P50/P90 за один проход), ранняя остановка по валидации кейса, ансамбль сидов.

# %%
def features(df: pd.DataFrame, force_case: bool = False) -> pd.DataFrame:
    x = df.drop(columns=[c for c in NON_FEATURES if c in df.columns])
    return x.assign(source="case") if force_case else x


def train_ensemble(train: pd.DataFrame, val: pd.DataFrame, bounds: tuple[float, float]) -> list:
    train, val = train.assign(y=train["y"].clip(*bounds)), val.assign(y=val["y"].clip(*bounds))
    w = mix_weights(train, CFG["case_share"])
    models = []
    for seed in CFG["seeds"]:
        m = CatBoostRegressor(loss_function=LOSS, eval_metric=LOSS, iterations=CFG["iterations"],
                              learning_rate=CFG["learning_rate"], depth=CFG["depth"], l2_leaf_reg=CFG["l2_leaf_reg"],
                              random_seed=seed, od_type="Iter", od_wait=CFG["od_wait"], use_best_model=True,
                              verbose=False, thread_count=-1)
        m.fit(Pool(features(train), train["y"], cat_features=CAT_FEATURES, weight=w),
              eval_set=Pool(features(val, True), val["y"], cat_features=CAT_FEATURES))
        models.append(m)
    return models


def predict(models: list, df: pd.DataFrame) -> np.ndarray:
    """Среднее по сидам, (n, 3): P10/P50/P90. Квантили сортируем, чтобы не пересекались."""
    return np.sort(np.mean([np.asarray(m.predict(features(df, True))) for m in models], axis=0), axis=1)


experiments = {"E1 кейс": False}
if len(ext_b):
    experiments["E2 кейс + 1С (для B)"] = True

preds, fitted, log = {}, {}, []
for name, use_1c in experiments.items():
    for t in ("B", "C"):
        if t == "C" and name != "E1 кейс":      # модель C одинакова во всех экспериментах — не переобучаем
            preds[(name, t)], fitted[(name, t)] = preds[("E1 кейс", t)], fitted[("E1 кейс", t)]
            continue
        train = rows[t]["train"] if not (t == "B" and use_1c) else pd.concat([rows[t]["train"], ext_b], ignore_index=True)
        bounds = tuple(float(q) for q in rows[t]["train"]["y"].quantile(list(CFG["clip_q"])))
        t0 = time.time()
        models = train_ensemble(train, rows[t]["val"], bounds)
        preds[(name, t)], fitted[(name, t)] = predict(models, rows[t]["test"]), (models, bounds)
        log.append({"эксперимент": name, "модель": t, "строк": len(train),
                    "итераций (среднее по сидам)": int(np.mean([m.get_best_iteration() for m in models])),
                    "секунд": round(time.time() - t0)})
pd.DataFrame(log)

# %% [markdown]
# ## 5. Оценка на тестовых компаниях кейса
# Главная метрика — **ошибка накопленного потока на горизонте h**: это ошибка прогноза остатка (остаток =
# сегодня + сумма потоков). Считаем в рублях и делим на средний дневной оборот компании, чтобы компании разного
# масштаба весили одинаково. Плюс покрытие интервала P10–P90 (цель ≈ 0,8) и pinball loss.

# %%
def assemble(pc: np.ndarray | None = None, pb: np.ndarray | None = None) -> pd.DataFrame:
    """Тестовые окна B и C, выровненные по (компания, отсечка, горизонт). pc/pb — прогнозы (n, 3) или None."""
    key = ["company", "cutoff", "h"]
    c = rows["C"]["test"][key + ["y", "scale", "mean_20", "same_dow_mean_8w"]].rename(
        columns={"y": "yc", "scale": "sc", "mean_20": "c_m20", "same_dow_mean_8w": "c_dow"})
    b = rows["B"]["test"][key + ["y", "scale", "mean_20", "same_dow_mean_8w"]].rename(
        columns={"y": "yb", "scale": "sb", "mean_20": "b_m20", "same_dow_mean_8w": "b_dow"})
    if pc is not None:
        c[["c10", "c50", "c90"]], b[["b10", "b50", "b90"]] = pc, pb
    m = c.merge(b, on=key, how="left").fillna(0.0)    # нет розницы → B = 0
    m["y_rub"] = m["yc"] * m["sc"] + m["yb"] * m["sb"]
    m["norm"] = m["sc"] + m["sb"]                      # общий масштаб компании для сопоставимости
    return m.sort_values(key).reset_index(drop=True)


def metrics(m: pd.DataFrame, p10, p50, p90, label: str) -> dict:
    y = m["y_rub"].to_numpy()
    n = m["norm"].to_numpy()
    res = {"модель": label, "покрытие P10–P90": float(((y >= p10) & (y <= p90)).mean()),
           "дневная MAE": float(np.mean(np.abs(p50 - y) / n))}
    res["pinball"] = float(np.mean([np.mean(np.maximum(q * (y - p), (q - 1) * (y - p)) / n)
                                    for q, p in zip(QUANTILES, (p10, p50, p90))]))
    g = m[["company", "cutoff", "h"]].assign(dy=y, dp=p50, n=n)
    g["cy"], g["cp"] = g.groupby(["company", "cutoff"])["dy"].cumsum(), g.groupby(["company", "cutoff"])["dp"].cumsum()
    for h in (5, 10, 20, 30):
        s = g[g["h"] == h]
        res[f"ошибка остатка h={h}"] = float(np.mean(np.abs(s["cp"] - s["cy"]) / s["n"]))
    return res


def model_cols(m):
    return (m["c10"] * m["sc"] + m["b10"] * m["sb"], m["c50"] * m["sc"] + m["b50"] * m["sb"],
            m["c90"] * m["sc"] + m["b90"] * m["sb"])


base = assemble()
zero = np.zeros(len(base))
table = [metrics(base, zero, zero, zero, "E0 ноль (остаток не меняется)"),
         metrics(base, *(base["c_m20"] * base["sc"] + base["b_m20"] * base["sb"],) * 3, "E0 среднее за 20 дней"),
         metrics(base, *(base["c_dow"] * base["sc"] + base["b_dow"] * base["sb"],) * 3, "E0 тот же день недели")]
assembled = {}
for name in experiments:
    assembled[name] = m = assemble(preds[(name, "C")], preds[(name, "B")])
    table.append(metrics(m, *[c.to_numpy() for c in model_cols(m)], name))
table = pd.DataFrame(table).set_index("модель")
table.round(3)

# %% [markdown]
# ### Устойчивость: 95% интервалы бутстрепом по компаниям и разброс по сидам
# Строки одной компании зависимы, поэтому бутстрепим **компании**, а не строки.

# %%
def bootstrap(m: pd.DataFrame, p: tuple, metric: str = "ошибка остатка h=30", n_boot: int = 200) -> tuple:
    comps = m["company"].unique()
    pos = {c: np.flatnonzero(m["company"].to_numpy() == c) for c in comps}
    arrs = [np.asarray(x) for x in p]
    r, vals = np.random.default_rng(0), []
    for _ in range(n_boot):
        pick = r.choice(comps, size=len(comps))
        idx = np.concatenate([pos[c] for c in pick])
        # Повторно выбранная компания — отдельная «копия», иначе её окна склеятся в одну группу при cumsum.
        tags = np.concatenate([np.full(len(pos[c]), k) for k, c in enumerate(pick)])
        sub = m.iloc[idx].copy()
        sub["company"] = sub["company"].astype(str).to_numpy() + "#" + tags.astype(str)
        vals.append(metrics(sub, *(a[idx] for a in arrs), "")[metric])
    return round(float(np.quantile(vals, 0.025)), 3), round(float(np.quantile(vals, 0.975)), 3)


ci = {"E0 ноль (остаток не меняется)": bootstrap(base, (zero, zero, zero))}
seed_spread = {}
for name, m in assembled.items():
    ci[name] = bootstrap(m, tuple(c.to_numpy() for c in model_cols(m)))
    per_seed = []
    for i in range(len(CFG["seeds"])):   # каждый сид отдельно: насколько результат зависит от случайности
        one = lambda t: np.sort(np.asarray(fitted[(name, t)][0][i].predict(features(rows[t]["test"], True))), axis=1)  # noqa: E731
        ms = assemble(one("C"), one("B"))
        per_seed.append(metrics(ms, *[c.to_numpy() for c in model_cols(ms)], "")["ошибка остатка h=30"])
    seed_spread[name] = (round(float(np.mean(per_seed)), 3), round(float(np.std(per_seed)), 3))
pd.DataFrame({"95% ДИ ошибки остатка h=30": ci, "среднее ± ст.откл. по сидам": seed_spread})

# %% [markdown]
# ### Где модель ошибается: ошибка остатка h=30 по отраслям

# %%
best = min(experiments, key=lambda n: table.loc[n, "ошибка остатка h=30"])
m = assembled[best]
p10, p50, p90 = (c.to_numpy() for c in model_cols(m))
m = m.assign(industry=m["company"].map(INDUSTRY))
by_ind = []
for ind, g in m.groupby("industry"):
    i = g.index.to_numpy()                      # assemble() сбрасывает индекс, поэтому индекс = позиция
    by_ind.append({"отрасль": ind, "компаний": g["company"].nunique(),
                   "модель": metrics(g, p10[i], p50[i], p90[i], "")["ошибка остатка h=30"],
                   "ноль": metrics(g, *(np.zeros(len(g)),) * 3, "")["ошибка остатка h=30"]})
pd.DataFrame(by_ind).sort_values("модель").round(3)

# %% [markdown]
# ### Важность признаков

# %%
imp = {t: pd.Series(fitted[(best, t)][0][0].get_feature_importance(), index=fitted[(best, t)][0][0].feature_names_)
       for t in ("B", "C")}
pd.DataFrame(imp).fillna(0).sort_values("C", ascending=False).round(1)

# %% [markdown]
# ## 6. Сохраняем модели для бэкенда
# `catboost_{B,C}_seed*.cbm` + `meta.json` (признаки, квантили, границы обрезки, конфиг, метрики).
# Положить в `backend/models/`.

# %%
meta = {"best_experiment": best, "quantiles": QUANTILES, "cat_features": CAT_FEATURES, "config": CFG,
        "clip_bounds": {}, "features": {}, "mbd_check": mbd_check,
        "metrics": table.round(4).reset_index().to_dict("records")}
for t in ("B", "C"):
    models, bounds = fitted[(best, t)]
    meta["clip_bounds"][t], meta["features"][t] = bounds, list(models[0].feature_names_)
    for seed, mdl in zip(CFG["seeds"], models):
        mdl.save_model(f"{OUT}/catboost_{t}_seed{seed}.cbm")
with open(f"{OUT}/meta.json", "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2, default=str)
print("Лучший эксперимент:", best, "· файлы:", sorted(os.listdir(OUT)))
if IN_COLAB:
    import shutil

    shutil.make_archive("catboost_out", "zip", OUT)
    from google.colab import files
    files.download("catboost_out.zip")

# %% [markdown]
# ## Как читать результаты
# - **Ошибка остатка h=30** — средняя ошибка остатка через 30 рабочих дней в «днях оборота» компании: 2,0 значит,
#   что в среднем ошибаемся на два обычных дневных оборота. Это главный критерий выбора модели.
# - Модель имеет смысл, только если она **уверенно** лучше бейзлайнов: интервал по компаниям не пересекается
#   с интервалом нуля, а разброс по сидам мал по сравнению с выигрышем.
# - **Покрытие P10–P90** должно быть около 0,8. Меньше — интервал узкий, вероятность разрыва будет занижена;
#   больше — модель перестраховывается и будет давать ложные тревоги.
# - Внешние данные (E2) оставляем, только если они улучшают ошибку остатка, не ухудшая покрытие.
