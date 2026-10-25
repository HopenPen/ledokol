"""Простой наглядный отчёт для менторов: как устроена система, CatBoost (поиск разрывов), категоризация.
Всё в одном HTML-файле, графики внутри. Данные берутся из experiments/out/state.pkl (его пишет ноутбук)."""
from __future__ import annotations

import base64
import io
import os
import json
import pickle
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import (accuracy_score, classification_report, confusion_matrix, f1_score, precision_score,
                             recall_score, roc_auc_score, roc_curve)

sys.stdout.reconfigure(encoding="utf-8")
S = pickle.load(open("experiments/out/state.pkl", "rb"))
INK, INK2, GRID, BLUE, RED, GREEN = "#0b0b0b", "#52514e", "#e6e5e0", "#2a78d6", "#d03b3b", "#1baf7a"
plt.rcParams.update({"font.size": 13, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "axes.titlecolor": INK,
                     "axes.titleweight": "bold", "axes.spines.top": False, "axes.spines.right": False,
                     "figure.facecolor": "white", "axes.facecolor": "white", "axes.grid": True, "grid.color": GRID})


def img(fig, alt: str) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    return f'<img alt="{alt}" src="data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}">'


# ───────────── CatBoost: поиск кассовых разрывов ─────────────
C, y = S["C"], S["y"]
score, pred = C["score_CatBoost"].to_numpy(), S["CV_PRED"]["CatBoost"]
prec, rec, f1, auc = precision_score(y, pred), recall_score(y, pred), f1_score(y, pred), roc_auc_score(y, score)
tn, fp, fn, tp = confusion_matrix(y, pred, labels=[False, True]).ravel()

fig, ax = plt.subplots(figsize=(7.4, 6))
cells = [[tn, fp], [fn, tp]]
shares = [[tn / (tn + fp), fp / (tn + fp)], [fn / (fn + tp), tp / (fn + tp)]]
color = {(0, 0): GREEN, (1, 1): GREEN, (0, 1): RED, (1, 0): RED}
names = [["Верно: всё спокойно", "Ложная тревога"], ["Пропущен разрыв", "Верно: нашли разрыв"]]
for i in range(2):
    for j in range(2):
        alpha = min(0.2 + 0.7 * shares[i][j], 0.9)
        ax.add_patch(plt.Rectangle((j, 1 - i), 1, 1, color=color[(i, j)], alpha=alpha, ec="white", lw=3))
        ax.text(j + 0.5, 1 - i + 0.62, f"{cells[i][j]}", ha="center", va="center", fontsize=34, weight="bold", color=INK)
        ax.text(j + 0.5, 1 - i + 0.33, f"{shares[i][j]:.0%} от строки", ha="center", va="center", fontsize=14, color=INK)
        ax.text(j + 0.5, 1 - i + 0.14, names[i][j], ha="center", va="center", fontsize=13, color=INK2)
ax.set_xlim(0, 2)
ax.set_ylim(0, 2)
ax.set_xticks([0.5, 1.5], ["Модель: разрыва не будет", "Модель: разрыв будет"])
ax.set_yticks([0.5, 1.5], ["На деле: был разрыв", "На деле: разрыва не было"])
ax.tick_params(length=0)
ax.grid(False)
for sp in ax.spines.values():
    sp.set_visible(False)
ax.set_title("Матрица ошибок CatBoost", loc="left")
cm_img = img(fig, "Матрица ошибок CatBoost")

fpr, tpr, _ = roc_curve(y, score)
fig, ax = plt.subplots(figsize=(6.2, 5.6))
ax.plot(fpr, tpr, color=BLUE, lw=3, label=f"CatBoost, AUC = {auc:.2f}")
ax.plot([0, 1], [0, 1], "--", color=INK2, lw=1.2, label="случайное угадывание, AUC = 0,50")
ax.fill_between(fpr, tpr, alpha=0.12, color=BLUE)
ax.set(xlabel="Доля ложных тревог", ylabel="Доля найденных разрывов", xlim=(0, 1), ylim=(0, 1.02))
ax.set_title("ROC-кривая", loc="left")
ax.legend(loc="lower right", frameon=False)
roc_img = img(fig, "ROC-кривая")

fig, ax = plt.subplots(figsize=(8, 4.6))
bins = np.linspace(0, 1, 21)
ax.hist(score[~y], bins=bins, color=GREEN, alpha=0.6, label=f"разрыва не было ({(~y).sum()} окон)")
ax.hist(score[y], bins=bins, color=RED, alpha=0.6, label=f"разрыв был ({y.sum()} окон)")
ax.set(xlabel="Риск разрыва по модели", ylabel="Число окон")
ax.set_title("Как модель разделяет окна: зелёное и красное должны быть врозь", loc="left", fontsize=12)
ax.legend(frameon=False)
hist_img = img(fig, "Распределение риска")

REG = S["REG"]
reg_rows = "".join(
    f"<tr><td>{h} дн.</td><td class='n'>{REG.loc['CatBoost', f'RMSE h{h}']:.2f}</td><td class='n'>{REG.loc['CatBoost', f'MAE h{h}']:.2f}</td></tr>"
    for h in (5, 10, 20, 30))

# ───────────── Категоризация ─────────────
cat, labels_ru = S["cat"], S["cat_labels"]
classes = sorted(cat["true"].unique())
ru = [labels_ru.get(c, c) for c in classes]
acc_clean, acc_noisy = accuracy_score(cat["true"], cat["pred_clean"]), accuracy_score(cat["true"], cat["pred_noisy"])
f1_noisy = f1_score(cat["true"], cat["pred_noisy"], average="macro")
cm = confusion_matrix(cat["true"], cat["pred_noisy"], labels=classes)
share = cm / cm.sum(axis=1, keepdims=True).clip(min=1)

fig, ax = plt.subplots(figsize=(13, 11.5))
im = ax.imshow(share, cmap="Blues", vmin=0, vmax=1)
for (i, j), v in np.ndenumerate(share):
    if v >= 0.04:
        ax.text(j, i, f"{v:.0%}", ha="center", va="center", fontsize=9, color="white" if v > 0.55 else INK)
ax.set_xticks(range(len(classes)), ru, rotation=90, fontsize=10)
ax.set_yticks(range(len(classes)), ru, fontsize=10)
ax.set_xlabel("Что предсказала модель", fontsize=13)
ax.set_ylabel("Как на самом деле", fontsize=13)
ax.grid(False)
ax.set_title("Матрица ошибок категоризации (доля от строки, по диагонали — верно)", loc="left")
fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
cat_cm_img = img(fig, "Матрица ошибок категоризации")

rep = classification_report(cat["true"], cat["pred_noisy"], output_dict=True, zero_division=0)
per = pd.DataFrame({c: rep[c] for c in classes}).T
per.index = ru
per = per.sort_values("f1-score")
fig, ax = plt.subplots(figsize=(9, 8.5))
ax.barh(per.index, per["f1-score"], color=[RED if v < 0.8 else BLUE for v in per["f1-score"]], height=0.7)
for k, v in enumerate(per["f1-score"]):
    ax.text(min(v + 0.01, 0.98), k, f"{v:.2f}", va="center", fontsize=10, color=INK)
ax.set(xlim=(0, 1.08), xlabel="F1 по категории (красные — ниже 0,8)")
ax.grid(axis="y", visible=False)
ax.set_title("Качество по каждой категории", loc="left")
f1_img = img(fig, "F1 по категориям")

worst_rows = "".join(
    f"<tr><td>{n}</td><td class='n'>{r['precision']:.2f}</td><td class='n'>{r['recall']:.2f}</td><td class='n'>{r['f1-score']:.2f}</td><td class='n'>{int(r['support'])}</td></tr>"
    for n, r in per.head(6).iterrows())
err = cat[cat["true"] != cat["pred_noisy"]].sample(8, random_state=3)
err_rows = "".join(
    f"<tr><td>{r['noisy'][:110]}</td><td>{labels_ru.get(r['true'], r['true'])}</td><td>{labels_ru.get(r['pred_noisy'], r['pred_noisy'])}</td></tr>"
    for _, r in err.iterrows())

demo_rows = "".join(
    f"<tr><td>{d['company']}</td><td>{d['industry']}</td><td class='n'>{d['risk_max_pct']}%</td><td>{'да' if d['alert'] else 'нет'}</td>"
    f"<td>{'был' if d['gap_actual'] else 'не было'}</td><td>{d['verdict']}</td></tr>" for d in json.load(open("experiments/out/catboost_demo.json", encoding="utf-8")))
demo_section = f'<img alt="Прогноз CatBoost на демо-компаниях" src="data:image/png;base64,{base64.b64encode(open("experiments/out/catboost_demo.png", "rb").read()).decode()}">'

# ───────────── Кривые обучения, стабильность, розница ─────────────
CUR = S["CURVES"]
fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.6))
for k, cv in enumerate(CUR):
    lr_, vr_ = cv["mean"]["learn"]["RMSE"], cv["mean"]["validation"]["RMSE"]
    a1.plot(lr_, color=BLUE, lw=1.4, alpha=0.75, label="обучающие компании" if k == 0 else None)
    a1.plot(vr_, color="#eb6834", lw=1.4, alpha=0.75, label="другие компании (проверка)" if k == 0 else None)
    a1.plot([cv["best_mean"]], [vr_[cv["best_mean"]]], "o", color=INK, ms=6, label="выбранная итерация" if k == 0 else None)
    qk = next(iter(cv["q"]["learn"]))
    a2.plot(cv["q"]["learn"][qk], color=BLUE, lw=1.4, alpha=0.75)
    a2.plot(cv["q"]["validation"][qk], color="#eb6834", lw=1.4, alpha=0.75)
    a2.plot([cv["best_q"]], [cv["q"]["validation"][qk][cv["best_q"]]], "o", color=INK, ms=6)
a1.set(xlabel="итерация (число деревьев)", ylabel="ошибка RMSE (в долях оборота)")
a1.set_title("Точечная модель: по линии на каждый из 5 фолдов", loc="left")
a1.legend(frameon=False)
a2.set(xlabel="итерация (число деревьев)", ylabel="потеря квантильной модели")
a2.set_title("Квантильная модель (коридор и вероятность разрыва)", loc="left")
curves_img = img(fig, "Кривые обучения")

FM = S["FOLD_METRICS"]
fig, axs = plt.subplots(1, 2, figsize=(13, 4))
for ax_, met in zip(axs, ("ROC-AUC", "PR-AUC")):
    for name, col in (("CatBoost", BLUE), ("Гибрид", "#eb6834"), ("Ансамбль", "#e87ba4")):
        d_ = FM[FM["модель"] == name]
        ax_.plot(d_["фолд"], d_[met], "-o", color=col, lw=2.2, ms=7, label=name)
    ax_.set(xlabel="группа компаний в тесте (фолд)", ylabel=met, xticks=sorted(FM["фолд"].unique()))
    ax_.set_title(f"{met} по группам компаний", loc="left")
axs[0].legend(frameon=False)
folds_img = img(fig, "Стабильность по фолдам")

LC = S["LC"]
fig, ax = plt.subplots(figsize=(6.5, 4.4))
ax.plot(LC["примеров"], LC["accuracy"], "-o", color=BLUE, lw=2.4, ms=7, label="accuracy")
ax.plot(LC["примеров"], LC["macro-F1"], "-o", color="#eb6834", lw=2.4, ms=7, label="macro-F1")
ax.set(xscale="log", xlabel="число обучающих примеров", ylabel="качество на искажённых назначениях", ylim=(0, 1.02))
ax.set_title("Кривая обучения категоризации", loc="left")
ax.legend(frameon=False, loc="lower right")
lc_img = img(fig, "Кривая обучения категоризации")

R30 = S["RET"][S["RET"]["h"] == 30]
rm_h, rm_c = (float(np.sqrt(np.mean((R30[c] - R30["y"]) ** 2))) for c in ("hybrid", "catboost"))
ret_note = f"Считается по статистике по дням недели. CatBoost на ней точнее: ошибка за 30 дней {rm_c:.1f} против {rm_h:.1f} дневных оборотов (в {rm_h / rm_c:.1f} раза меньше)."

# ───────────── Дополнительный эксперимент: TabPFN ─────────────
from sklearn.metrics import precision_recall_curve as _prc
TP = json.load(open("experiments/out/gap_tabpfn.json", encoding="utf-8"))
tp_scores = pd.read_csv("experiments/out/gap_tabpfn_scores.csv")
tpd = tp_scores[tp_scores["h"] == 30]
ens_s = C["score_Ансамбль"].to_numpy()
fig, ax = plt.subplots(figsize=(7.4, 5.2))
for name, yy, ss, col in (("Ансамбль гибрида и CatBoost", y, ens_s, "#e87ba4"), ("TabPFN", tpd["y"].to_numpy(), tpd["score"].to_numpy(), "#1a9a6c")):
    pp, rr, _ = _prc(yy, ss)
    ax.plot(rr, pp, color=col, lw=2.6, label=name)
ax.axhline(y.mean(), ls="--", lw=1.2, color=INK2, label=f"случайная модель ({y.mean():.2f})")
ax.set(xlabel="Recall: доля найденных разрывов", ylabel="Precision: доля настоящих тревог", xlim=(0, 1), ylim=(0, 1.02))
ax.set_title("Компромисс между precision и recall (30 дней)", loc="left")
ax.legend(frameon=False, loc="upper right")
tabpfn_img = img(fig, "Кривая precision и recall")

def _trade(yy, ss):
    pp, rr, _ = _prc(yy, ss)
    return {t: float(pp[int(np.argmax(np.where(rr[:-1] >= t, pp[:-1], -1)))]) for t in (0.6, 0.7, 0.8, 0.9)}
t_ens, t_tp = _trade(y, ens_s), _trade(tpd["y"].to_numpy(), tpd["score"].to_numpy())
trade_rows = "".join(f"<tr><td>не меньше {int(t * 100)}% разрывов</td><td class='n'>{t_ens[t]:.2f}</td><td class='n'>{t_tp[t]:.2f}</td></tr>" for t in (0.6, 0.7, 0.8, 0.9))
tp30 = TP["30"]

# ───────────── Паспорт данных и обучения ─────────────
import ast as _ast
_src = open("model_evaluation.py", encoding="utf-8").read()
_cfg_text = _src[_src.index("CFG = {") + 6: _src.index(chr(10) + "}" + chr(10), _src.index("CFG = {")) + 2]
CFGV = _ast.literal_eval(_cfg_text)
_case = os.environ.get("CASE_DIR", "")
if _case and os.path.exists(os.path.join(_case, "all_operations.csv")):
    _raw = pd.read_csv(os.path.join(_case, "all_operations.csv"), sep=";", encoding="utf-8-sig", usecols=["company_id", "operation_date"])
    _ind = pd.read_csv(os.path.join(_case, "companies.csv"), sep=";", encoding="utf-8-sig", dtype=str)["industry"].nunique()
    data_rows = [("Компаний", f"{_raw['company_id'].nunique()}"), ("Отраслей", f"{_ind}"), ("Операций", f"{len(_raw):,}".replace(",", " ")),
                 ("Период выписок", f"{_raw['operation_date'].min()} … {_raw['operation_date'].max()}")]
else:
    data_rows = [("Компаний", "150"), ("Операций", "222 420")]
data_rows += [("Проверочных окон", f"{len(C):,}".replace(",", " ") + " (компания × дата прогноза)"),
              ("Из них с разрывом", f"{int(y.sum())} ({y.mean():.0%}): классы несбалансированы"),
              ("Горизонт прогноза", f"{CFGV['horizon']} рабочих дней"),
              ("Даты прогноза на компанию", f"{CFGV['eval_cutoffs']} с шагом {CFGV['eval_step']} рабочих дней")]
data_table = "".join(f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in data_rows)

param_rows = [("Алгоритм", "CatBoost: две модели (точечная RMSE и квантильная MultiQuantile)"),
              ("Квантили", ", ".join(f"{q:g}" for q in CFGV["quantiles"])),
              ("Глубина деревьев", CFGV["depth"]), ("Скорость обучения (learning rate)", CFGV["learning_rate"]),
              ("Регуляризация L2", CFGV["l2_leaf_reg"]), ("Максимум итераций («эпох»)", CFGV["iterations"]),
              ("Ранняя остановка", f"если ошибка на проверочных компаниях не падает {CFGV['od_wait']} итераций подряд"),
              ("Зерно", CFGV["seed"]), ("Доля проверочных компаний для остановки", f"{CFGV['val_frac']:.0%} обучающих"),
              ("Шаг дат в обучающей выборке", f"{CFGV['train_step']} рабочих дня"),
              ("Горизонты в обучении", ", ".join(map(str, CFGV["train_horizons"]))),
              ("Обрезка выбросов цели", "по квантилям 0,5% и 99,5% обучающей части")]
param_table = "".join(f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in param_rows)

FD = S["FOLDS"]
Wf = S["W"].groupby("fold")["company"].agg(["count", "nunique"])
fold_rows = "".join(
    f"<tr><td>{int(r['фолд'])}</td><td class='n'>{int(r['компаний в обучении'])}</td><td class='n'>{int(r['строк кейса']):,}".replace(",", " ")
    + f"</td><td class='n'>{int(r['строк 1С'])}</td><td class='n'>{int(Wf.loc[int(r['фолд']), 'nunique'])}</td><td class='n'>{int(Wf.loc[int(r['фолд']), 'count'])}</td>"
    f"<td class='n'>{int(r['итераций RMSE'])}</td><td class='n'>{int(r['итераций квантилей'])}</td><td class='n'>{r['RMSE обучение']:.2f}</td>"
    f"<td class='n'>{r['RMSE ранняя остановка']:.2f}</td><td class='n'>{r['RMSE тест']:.2f}</td><td class='n'>{int(r['секунд'])}</td></tr>"
    for _, r in FD.iterrows())
fold_rows += (f"<tr><th>среднее</th><td></td><td></td><td></td><td></td><td></td><td class='n'>{FD['итераций RMSE'].mean():.0f}</td><td class='n'>{FD['итераций квантилей'].mean():.0f}</td>"
              f"<td class='n'>{FD['RMSE обучение'].mean():.2f}</td><td class='n'>{FD['RMSE ранняя остановка'].mean():.2f}</td><td class='n'>{FD['RMSE тест'].mean():.2f}</td><td class='n'>{FD['секунд'].sum():.0f}</td></tr>")
ratio = (FD["RMSE тест"] / FD["RMSE обучение"])

imp = S["imp"].sort_values()
fig, ax = plt.subplots(figsize=(7.4, 5.2))
ax.barh(imp.index, imp.values, color=BLUE, height=0.65)
for k, v in enumerate(imp.values):
    ax.text(v + 0.2, k, f"{v:.1f}", va="center", fontsize=10, color=INK)
ax.set(xlabel="важность признака, %")
ax.grid(axis="y", visible=False)
ax.set_title("Какие признаки важнее всего для CatBoost", loc="left")
imp_img = img(fig, "Важность признаков")
feature_note = ", ".join(S["imp"].sort_values(ascending=False).index)
passport_html = True

html = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ML-отчёт: прогноз денежных потоков</title>
<style>
body {{ margin:0; background:#fff; color:#0b0b0b; font:17px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }}
main {{ max-width:1040px; margin:0 auto; padding:28px 18px 70px; }}
h1 {{ font-size:32px; margin:0 0 6px; }} h2 {{ font-size:25px; margin:46px 0 6px; padding-top:18px; border-top:3px solid #2a78d6; }}
p.m {{ color:#52514e; margin:4px 0 14px; }}
.k {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:12px; margin:16px 0; }}
.k div {{ border:1px solid #e6e5e0; border-radius:12px; padding:14px 16px; background:#fafaf9; }}
.k b {{ display:block; font-size:34px; color:#2a78d6; line-height:1.1; }} .k span {{ color:#52514e; font-size:14px; }}
img {{ max-width:100%; height:auto; border:1px solid #e6e5e0; border-radius:10px; margin:10px 0; }}
.two {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(420px,100%),1fr)); gap:14px; }}
.steps {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:12px; margin:14px 0; }}
.steps div {{ border:1px solid #e6e5e0; border-radius:12px; padding:14px 16px; }}
.steps b {{ display:block; font-size:18px; margin-bottom:4px; color:#2a78d6; }}
table {{ border-collapse:collapse; width:100%; margin:8px 0; font-size:15px; }}
th,td {{ border-bottom:1px solid #e6e5e0; padding:7px 9px; text-align:left; }} th {{ color:#52514e; }} td.n {{ text-align:right; font-variant-numeric:tabular-nums; }}
.box {{ background:#f3f7fd; border-left:5px solid #2a78d6; padding:10px 14px; border-radius:6px; margin:12px 0; }}
</style></head><body><main>
<h1>ML-отчёт: прогноз денежных потоков малого бизнеса</h1>
<p class="m">Сервис по выписке показывает, когда и на какую сумму может не хватить денег. Ниже: как устроена система, две ML-модели и результаты проверки на компаниях, которых модель не видела.</p>

<h2>1. Данные и настройки обучения</h2>
<div class="two"><div><h3>Данные и проверка</h3><table>{data_table}</table></div>
<div><h3>Параметры CatBoost</h3><table>{param_table}</table></div></div>
<h3>Как шло обучение по фолдам</h3>
<p class="m">Пять фолдов: на каждом модель учится на одних компаниях и проверяется на других, которых не видела. «Итерация» это одно добавленное дерево (эпоха бустинга). Ошибка RMSE в долях оборота компании, чем меньше, тем лучше.</p>
<div style="overflow-x:auto"><table><tr><th>Фолд</th><th class="n">Компаний в обучении</th><th class="n">Строк обучения</th><th class="n">Внешних строк (1С)</th><th class="n">Компаний в тесте</th><th class="n">Окон в тесте</th><th class="n">Итераций (RMSE)</th><th class="n">Итераций (квантили)</th><th class="n">RMSE обучение</th><th class="n">RMSE проверка</th><th class="n">RMSE тест</th><th class="n">Секунд</th></tr>{fold_rows}</table></div>
<div class="box"><b>Что видно.</b> Ранняя остановка выбирает от {int(FD['итераций RMSE'].min())} до {int(FD['итераций RMSE'].max())} итераций. Ошибка на новых компаниях в {ratio.min():.1f}–{ratio.max():.1f} раза выше, чем на обучающих: модель частично запоминает обучающие компании (это видно и на кривых обучения ниже). В одном фолде в обучение попало 30 внешних строк из продаж 1С (0,1% выборки): влияние пренебрежимо мало, но мы указываем это явно.</div>
<div class="two"><div><h3>Признаки ({len(S['imp'])})</h3>
<p class="m">{feature_note}</p></div><div>{imp_img}</div></div>

<h2>2. Как устроена система</h2>
<p class="m">Остаток на каждый будущий день считается из частей. Каждая часть считается тем способом, который для неё лучше всего подходит.</p>
<div class="steps">
<div><b>События</b>Аренда, зарплата, кредит, налоги, выставленные счета, платежи, введённые предпринимателем. Известны заранее, ставятся на свою дату и сумму (правила и календарь).</div>
<div><b>Розничная выручка</b>Эквайринг, СБП, наличные. Зависит от дня недели, но колеблется. {ret_note}</div>
<div><b>Остальной поток</b>Мелкие поступления и закупки. Берём среднее за последние месяцы.</div>
<div><b>Риск разрыва</b>1000 вариантов будущего с отклонениями из прошлого. Доля вариантов, где остаток ушёл ниже нуля, — вероятность разрыва.</div>
</div>
<div class="box"><b>Что такое «гибрид».</b> Это название расчёта, который складывает остаток из этих частей и прогоняет 1000 вариантов будущего. Он объединяет расчёт «поштучно» (события) и «в среднем» (статистика). Он ничему не обучается, считает по истории одной компании и поэтому сразу учитывает новые события пользователя: платёж, счёт, сценарий «что если».</div>
<div class="box"><b>Что такое CatBoost.</b> Это ML-модель: много небольших деревьев решений, каждое исправляет ошибки предыдущих. Обучена на всех 150 компаниях сразу, видит закономерности, которые одна компания не покажет, и умеет оценивать вероятность разрыва. Про конкретные события компании она не знает, их знает гибрид.</div>

<h2>3. CatBoost: поиск кассовых разрывов</h2>
<p class="m">Вопрос к модели: «будет ли в ближайшие 30 рабочих дней нехватка денег?». Проверка на 150 компаниях: в тесте только те, которых модель не видела. 1 594 окна, в 268 из них разрыв действительно был.</p>
<div class="k">
<div><b>{rec:.0%}</b><span>разрывов нашли (recall)</span></div>
<div><b>{prec:.0%}</b><span>тревог настоящие (precision)</span></div>
<div><b>{f1:.2f}</b><span>F1: баланс precision и recall</span></div>
<div><b>{auc:.2f}</b><span>ROC-AUC: насколько хорошо отличает окна с разрывом</span></div>
</div>
<div class="two">{cm_img}{roc_img}</div>
<div class="box"><b>Как читать матрицу.</b> Зелёные клетки — модель права: {tp} раз нашла настоящий разрыв и {tn} раз верно сказала «всё спокойно». Красные — ошибки: {fp} ложных тревог и {fn} пропущенных разрывов. Из {tp + fn} настоящих разрывов найдено {tp}.</div>
{hist_img}
<h3>Как обучалась модель</h3>
<p class="m">У бустинга «эпоха» это одно добавленное дерево. Синяя линия: ошибка на обучающих компаниях, оранжевая: на других компаниях, по ним выбирается момент остановки (чёрная точка). Когда оранжевая перестаёт падать, а синяя идёт вниз, модель начинает запоминать обучающие компании, и обучение останавливается.</p>
{curves_img}
<h3>Стабильность по группам компаний</h3>
<p class="m">Качество на каждой из пяти групп компаний отдельно. Разброс заметный: результат зависит от того, какие компании попали в тест.</p>
{folds_img}
<h3>Ошибка прогноза остатка на счёте</h3>
<p class="m">В дневных оборотах компании: «ошибка 3» — промахнулись на три дня обычных трат. Чем меньше, тем лучше.</p>
<table><tr><th>Горизонт</th><th class="n">RMSE CatBoost</th><th class="n">MAE CatBoost</th></tr>{reg_rows}</table>
<p class="m">Точную сумму остатка через месяц предсказать трудно: мешают редкие крупные платежи, которых нет в истории. Сильная сторона модели — раннее предупреждение о нехватке денег и более точный прогноз розничной выручки.</p>

<h2>4. Категоризация операций</h2>
<p class="m">Модель определяет категорию платежа по тексту назначения. 27 категорий. Проверили на компаниях, которых модель при обучении не видела, и отдельно на искажённых назначениях (опечатки, сокращения, выпавшие слова): так выглядят незнакомые формулировки.</p>
<div class="k">
<div><b>{acc_clean:.0%}</b><span>верных на обычных назначениях</span></div>
<div><b>{acc_noisy:.1%}</b><span>верных на искажённых</span></div>
<div><b>{f1_noisy:.2f}</b><span>macro-F1 на искажённых</span></div>
<div><b>{len(cat):,}</b><span>операций в проверке</span></div>
</div>
{cat_cm_img}
<div class="box"><b>Как читать матрицу.</b> Строка — настоящая категория, столбец — что предсказала модель. Тёмная диагональ значит «угадала». Тёмные клетки вне диагонали — путаница: чаще всего незнакомые операции модель относит к «Закупки у поставщиков».</div>
<div class="two">
<div>{f1_img}</div>
<div>
<h3>Кривая обучения</h3>
{lc_img}
<h3>Где модель ошибается чаще всего</h3>
<table><tr><th>Категория</th><th class="n">Precision</th><th class="n">Recall</th><th class="n">F1</th><th class="n">Операций</th></tr>{worst_rows}</table>
<h3>Примеры ошибок</h3>
<table><tr><th>Назначение платежа</th><th>Настоящая</th><th>Модель сказала</th></tr>{err_rows}</table>
</div></div>
<p class="m">Оговорка: правильным ответом здесь считается разметка по нашим правилам, поэтому это проверка устойчивости модели. Ручная разметка 500 операций для проверки реальной точности пока не сделана.</p>

<h2>5. Как модель работает на конкретных компаниях</h2>
<p class="m">Модель обучена на 118 компаниях. Эти четыре она не видела. Прогноз сделан за 30 рабочих дней до конца выписки, затем сравнён с тем, что было на самом деле.</p>
{demo_section}
<table><tr><th>Компания</th><th>Отрасль</th><th class="n">Риск по модели</th><th>Тревога</th><th>Разрыв на деле</th><th>Итог</th></tr>{demo_rows}</table>
<div class="box"><b>Что видно.</b> Три компании из четырёх определены верно. Разрыв у C082 модель пропустила: 21 сентября там было погашение сезонного кредита на 9,3 млн ₽. Платёж годовой (такой же был 10 октября 2025 года), а модель смотрит назад всего на два месяца и годовой цикл не видит. Для таких случаев нужны график кредита из банка или ручной ввод события; признак «тот же период год назад» в планах. У C009 остаток уже был отрицательным на дату прогноза.</div>

<h2>6. Дополнительный эксперимент: готовая модель TabPFN</h2>
<p class="m">TabPFN это предобученная модель для небольших табличных данных. Мы обучили её на тех же признаках и проверили на тех же окнах и группах компаний. <b>Этот расчёт сделан отдельным скриптом на видеокарте (experiments/gap_tabpfn.py), в основном ноутбуке его нет.</b> Лицензия весов v2: Apache 2.0 с указанием авторов.</p>
<div class="k">
<div><b>{tp30['precision']:.2f}</b><span>precision (доля настоящих тревог)</span></div>
<div><b>{tp30['recall']:.2f}</b><span>recall (доля найденных разрывов)</span></div>
<div><b>{tp30['F1']:.2f}</b><span>F1</span></div>
<div><b>{tp30['PR-AUC']:.2f}</b><span>PR-AUC (у ансамбля 0,66)</span></div>
</div>
{tabpfn_img}
<table><tr><th>Нужно найти</th><th class="n">Precision у ансамбля</th><th class="n">Precision у TabPFN</th></tr>{trade_rows}</table>
<div class="box"><b>Что видно.</b> При том же recall (около 0,66–0,68) тревоги у TabPFN заметно точнее: precision 0,63 против 0,53. Если нужно находить 80% разрывов, precision получается около 0,54. Достичь 0,8 по обоим показателям не удаётся ни одной модели: часть разрывов вызвана событиями, которых нет в выписке. Это один запуск, а качество заметно зависит от группы компаний, поэтому цифры стоит читать с запасом. В приложение TabPFN не встроен: он тяжёлый (видеокарта, минуты на расчёт).</div>

<h2>7. Ограничения</h2>
<ul>
<li>Данные синтетические; на другом наборе цифры могут отличаться.</li>
<li>Точную сумму остатка через 30 дней предсказать трудно: решают редкие крупные платежи. Поэтому главная ценность — раннее предупреждение.</li>
<li>CatBoost не знает событий конкретной компании; их учитывает гибридный расчёт.</li>
</ul>
</main></body></html>"""
open("REPORT_SIMPLE.html", "w", encoding="utf-8").write(html)
print("готово: REPORT_SIMPLE.html", round(len(html) / 1e6, 1), "МБ")
