"""HTML для презентации: паспорт и метрики CatBoost, сравнение с другими моделями (графики seaborn).

Всё считается из сохранённых оценок моделей (analytics/experiments/out), ничего не рисуется вручную.
Запуск: uv run --with seaborn --with matplotlib --with scikit-learn --with pyarrow python build_presentation_metrics.py out.html
"""
import ast, base64, io, pickle, re, sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.metrics import (average_precision_score, brier_score_loss, confusion_matrix, f1_score, precision_recall_curve,
                             precision_score, recall_score, roc_auc_score, roc_curve)

HERE = Path(__file__).parent
O = HERE / "experiments" / "out"
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "METRICS_PRESENTATION.html")
S = pickle.load(open(O / "state.pkl", "rb"))
sns.set_theme(style="whitegrid", font_scale=1.0, rc={"axes.spines.top": False, "axes.spines.right": False})
PAL = {"Гибрид": "#9aa5b1", "CatBoost": "#1f6feb", "Ансамбль": "#8250df", "CatBoost-классификатор": "#0a7d5a",
       "TabPFN": "#d1242f", "CatBoost + TabPFN": "#bf8700"}


def img(fig):
    b = io.BytesIO()
    fig.savefig(b, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return '<img src="data:image/png;base64,%s">' % base64.b64encode(b.getvalue()).decode()


def html_table(df):
    return df.to_html(classes="t", border=0, float_format=lambda v: f"{v:.3f}")


# параметры обучения читаем из самого ноутбука-источника, чтобы не расходились
src = (HERE / "model_evaluation.py").read_text(encoding="utf-8")
CFG = ast.literal_eval(re.search(r"^CFG = (\{.*?^\})", src, re.S | re.M).group(1).split("\n}")[0] + "\n}") if False else None
block = re.search(r"^CFG = \{(.*?)^\}", src, re.S | re.M).group(1)
CFG = {}
for k, v in re.findall(r'"(\w+)":\s*([^,#\n]+(?:\[[^\]]*\])?)', block):
    try:
        CFG[k] = ast.literal_eval(v.strip())
    except Exception:
        pass

# ---------- оценки всех моделей на одних и тех же окнах (горизонт 30) ----------
v2 = pd.read_parquet(O / "gap_v2_scores.parquet")
v2.columns = ["company", "t", "h", "y", "fold", "mode", "set", "score"]
v2_all = v2[(v2["mode"] == "по компаниям") & (v2["set"].str.contains("прогноз гибрида"))]
v2 = v2_all[v2_all["h"] == 30]
tp_all = pd.read_csv(O / "gap_tabpfn_scores.csv")
tp = tp_all[tp_all["h"] == 30]
v3 = pd.read_parquet(O / "gap_v3_scores.parquet")
v3.columns = ["company", "t", "h", "y", "fold", "model", "score"]
mix = v3[(v3["h"] == 30) & (v3["model"] == "смесь CatBoost + TabPFN")]
hyb = pd.read_csv(O / "gap_v2_dataset.csv", usecols=["company", "t", "h", "hyb_pmax"])
hyb = hyb[hyb["h"] == 30]
key = ["company", "t"]
W = (v2[key + ["y", "score"]].rename(columns={"score": "CatBoost-классификатор"})
     .merge(tp[key + ["score"]].rename(columns={"score": "TabPFN"}), on=key)
     .merge(mix[key + ["score"]].rename(columns={"score": "CatBoost + TabPFN"}), on=key)
     .merge(hyb[key + ["hyb_pmax"]].rename(columns={"hyb_pmax": "Гибрид"}), on=key))
MODELS = ["Гибрид", "CatBoost-классификатор", "TabPFN", "CatBoost + TabPFN"]
y = W["y"].to_numpy().astype(int)


def best_thr(yy, s):
    p, r, t = precision_recall_curve(yy, s)
    f = 2 * p * r / (p + r + 1e-12)
    return t[f[:-1].argmax()]


def prec_at_recall(yy, s, rec):
    p, r, _ = precision_recall_curve(yy, s)
    return p[r >= rec].max()


def table(df, cols, yy):
    rows = []
    for m in cols:
        s = df[m].to_numpy()
        th = best_thr(yy, s)
        pr = (s >= th).astype(int)
        rows.append({"модель": m, "ROC-AUC": roc_auc_score(yy, s), "PR-AUC": average_precision_score(yy, s),
                     "precision": precision_score(yy, pr), "recall": recall_score(yy, pr), "F1": f1_score(yy, pr),
                     "precision при recall 0,8": prec_at_recall(yy, s, 0.8), "Brier": brier_score_loss(yy, np.clip(s, 0, 1)),
                     "порог": th})
    return pd.DataFrame(rows).set_index("модель")


T = table(W, MODELS, y)

# ---------- основной набор окон: Гибрид / CatBoost / Ансамбль ----------
C = S["C"]
C = C[~C["ongoing"]]
yc = C["gap_actual"].astype(int).to_numpy()
ens_cols = {"Гибрид": "score_Гибрид", "CatBoost": "score_CatBoost", "Ансамбль": "score_Ансамбль"}
CA = pd.DataFrame({k: C[v].to_numpy() for k, v in ens_cols.items()})
TA = table(CA, list(ens_cols), yc)
figs = {}

# --- обучение: кривые потерь по фолдам (train vs validation) ---
cur = S["CURVES"]
fig, ax = plt.subplots(1, 2, figsize=(12, 4.2))
for k, e in enumerate(cur):
    for name, a, col in (("mean", ax[0], "RMSE"), ("q", ax[1], None)):
        ev = e[name]
        metric = list(ev["learn"])[0]
        lr_, va_ = ev["learn"][metric], ev["validation"][metric]
        a.plot(lr_, color=sns.color_palette("Blues", 7)[k + 2], lw=1.2, label="обучение" if k == 0 else None)
        a.plot(va_, color=sns.color_palette("Reds", 7)[k + 2], lw=1.2, label="проверка (ранняя остановка)" if k == 0 else None)
        a.axvline(e["best_" + name], color="#888", lw=0.6, ls=":")
ax[0].set(title="Модель остатка (RMSE): 5 фолдов", xlabel="итерация (дерево)", ylabel="RMSE")
ax[1].set(title="Квантильная модель (коридор): 5 фолдов", xlabel="итерация (дерево)", ylabel="потеря")
for a in ax:
    a.legend()
fig.tight_layout()
figs["learn"] = img(fig)

FD = S["FOLDS"].copy()
FD["фолд"] = FD["фолд"].astype(int) + 1
FD = FD[["фолд", "компаний в обучении", "итераций RMSE", "итераций квантилей", "RMSE обучение", "RMSE ранняя остановка", "RMSE тест", "секунд"]].set_index("фолд")

# --- метрики разрывов ---
fig, ax = plt.subplots(1, 3, figsize=(13, 3.9))
for a, m in zip(ax, ens_cols):
    th = TA.loc[m, "порог"]
    cm = confusion_matrix(yc, (CA[m] >= th).astype(int))
    sns.heatmap(cm, annot=True, fmt="d", cmap="Blues", cbar=False, ax=a, annot_kws={"size": 15},
                xticklabels=["нет тревоги", "тревога"], yticklabels=["разрыва нет", "разрыв был"])
    a.set_title(f"{m}, порог {th:.2f}\nprecision {TA.loc[m, 'precision']:.2f} · recall {TA.loc[m, 'recall']:.2f}", fontsize=11)
fig.tight_layout()
figs["cm_a"] = img(fig)


def curves(df, yy, cols, title):
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.6))
    for m in cols:
        fpr, tpr, _ = roc_curve(yy, df[m])
        p, r, _ = precision_recall_curve(yy, df[m])
        lw = 3 if m in ("CatBoost", "CatBoost-классификатор") else 1.8
        ax[0].plot(fpr, tpr, color=PAL[m], lw=lw, label=f"{m} ({roc_auc_score(yy, df[m]):.3f})")
        ax[1].plot(r, p, color=PAL[m], lw=lw, label=f"{m} ({average_precision_score(yy, df[m]):.3f})")
    ax[0].plot([0, 1], [0, 1], "--", color="#bbb")
    ax[0].set(xlabel="доля ложных тревог", ylabel="доля найденных разрывов (recall)", title="ROC-кривая")
    ax[1].axhline(yy.mean(), ls="--", color="#bbb")
    ax[1].axvline(0.8, ls=":", color="#d1242f")
    ax[1].set(xlabel="recall", ylabel="precision", title="Precision–Recall (красная линия: recall 0,8)")
    ax[0].legend(loc="lower right", fontsize=9)
    ax[1].legend(loc="upper right", fontsize=9)
    fig.suptitle(title, y=1.02, fontsize=12)
    fig.tight_layout()
    return img(fig)


figs["curves_a"] = curves(CA, yc, list(ens_cols), "CatBoost и соседи по основному набору окон")
figs["curves_b"] = curves(W, y, MODELS, "Все модели на одних и тех же окнах")

fig, ax = plt.subplots(1, 2, figsize=(12, 4.2))
q = pd.qcut(CA["CatBoost"], 10, duplicates="drop")
g = pd.DataFrame({"p": CA["CatBoost"], "y": yc}).groupby(q, observed=True).mean()
ax[0].plot([0, 1], [0, 1], "--", color="#bbb")
ax[0].plot(g["p"], g["y"], "o-", color=PAL["CatBoost"], lw=2.5)
ax[0].set(xlabel="предсказанная вероятность разрыва", ylabel="доля реальных разрывов", title="Калибровка CatBoost (10 групп)")
sns.kdeplot(x=CA["CatBoost"], hue=pd.Series(yc).map({0: "разрыва не было", 1: "разрыв был"}), common_norm=False, fill=True, ax=ax[1],
            palette={"разрыва не было": "#9aa5b1", "разрыв был": "#d1242f"}, clip=(0, 1))
ax[1].set(xlabel="оценка CatBoost", title="Как модель разделяет два класса")
fig.tight_layout()
figs["cal"] = img(fig)

FM = S["FOLD_METRICS"].copy()
FM = FM[FM["модель"] == "CatBoost"].melt(id_vars=["фолд", "модель"], value_vars=["ROC-AUC", "PR-AUC"], var_name="метрика", value_name="значение")
FM["фолд"] = FM["фолд"].astype(int) + 1
fig, ax = plt.subplots(figsize=(7.5, 3.8))
sns.barplot(data=FM, x="фолд", y="значение", hue="метрика", palette=["#1f6feb", "#8fb8ff"], ax=ax)
ax.set_ylim(0, 1)
ax.set_title("CatBoost: качество по фолдам (компании фолда модель не видела)")
fig.tight_layout()
figs["folds"] = img(fig)

# --- сравнение моделей ---
M = T.reset_index().melt(id_vars="модель", value_vars=["ROC-AUC", "PR-AUC", "precision", "recall", "F1"], var_name="метрика", value_name="значение")
fig, ax = plt.subplots(figsize=(12, 4.4))
sns.barplot(data=M, x="метрика", y="значение", hue="модель", palette=PAL, ax=ax)
ax.set_ylim(0, 1)
for c in ax.containers:
    ax.bar_label(c, fmt="%.2f", fontsize=8, padding=2)
ax.legend(ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.1))
ax.set_xlabel("")
ax.set_title("Метрики поиска разрывов на 30 дней (порог — лучший по F1)")
fig.tight_layout()
figs["bars"] = img(fig)

fig, ax = plt.subplots(1, 4, figsize=(15, 3.6))
for a, m in zip(ax, MODELS):
    cm = confusion_matrix(y, (W[m] >= T.loc[m, "порог"]).astype(int))
    sns.heatmap(cm, annot=True, fmt="d", cmap="Blues", cbar=False, ax=a, xticklabels=["нет", "тревога"], yticklabels=["нет", "разрыв"], annot_kws={"size": 13})
    a.set_title(m, fontsize=10)
fig.tight_layout()
figs["cm_b"] = img(fig)

rows = []
for h, d in v2_all.groupby("h"):
    rows.append({"горизонт": h, "модель": "CatBoost-классификатор", "ROC-AUC": roc_auc_score(d["y"], d["score"]), "PR-AUC": average_precision_score(d["y"], d["score"])})
for h, d in tp_all.groupby("h"):
    rows.append({"горизонт": h, "модель": "TabPFN", "ROC-AUC": roc_auc_score(d["y"], d["score"]), "PR-AUC": average_precision_score(d["y"], d["score"])})
H = pd.DataFrame(rows).melt(id_vars=["горизонт", "модель"], var_name="метрика", value_name="значение")
fig, ax = plt.subplots(1, 2, figsize=(12, 3.9))
for a, mt in zip(ax, ["ROC-AUC", "PR-AUC"]):
    sns.lineplot(data=H[H["метрика"] == mt], x="горизонт", y="значение", hue="модель", palette=PAL, marker="o", lw=2.5, ax=a)
    a.set_xticks([5, 10, 20, 30])
    a.set_title(mt)
    a.set_xlabel("горизонт, рабочих дней")
fig.tight_layout()
figs["hor"] = img(fig)

# --- категоризация: кривая обучения ML-слоя ---
LC = S["LC"].set_index("примеров")
fig, ax = plt.subplots(figsize=(7.5, 3.8))
sns.lineplot(data=LC.reset_index().melt(id_vars="примеров", var_name="метрика", value_name="значение"), x="примеров", y="значение", hue="метрика",
             marker="o", lw=2.5, ax=ax, palette=["#1f6feb", "#d1242f"])
ax.set_xscale("log")
ax.set_ylim(0.7, 1.0)
ax.set_title("Категоризация: качество от размера обучения")
fig.tight_layout()
figs["lc"] = img(fig)

REG = S["REG"].copy()
n, pos = len(W), int(y.sum())
nA, posA = len(C), int(yc.sum())
n_trees_mean, n_trees_q = int(S["FOLDS"]["итераций RMSE"].mean()), int(S["FOLDS"]["итераций квантилей"].mean())
params = pd.DataFrame({"значение": [
    "CatBoost (градиентный бустинг над деревьями), две модели: RMSE и MultiQuantile", f"до {CFG.get('iterations', 1500)}, ранняя остановка через {CFG.get('od_wait', 100)} без улучшений",
    f"в среднем {n_trees_mean} (RMSE) и {n_trees_q} (квантили)", CFG.get("learning_rate", 0.06), CFG.get("depth", 6), CFG.get("l2_leaf_reg", 5.0),
    f"{len(CFG.get('quantiles', []))}: " + ", ".join(str(q) for q in CFG.get("quantiles", [])), f"{CFG.get('n_folds', 5)} фолдов по компаниям (компания целиком в одном фолде)",
    f"{CFG.get('val_frac', 0.15):.0%} обучающих компаний под раннюю остановку", CFG.get("seed", 7), "RMSE и MultiQuantile (потеря квантилей)"]},
    index=["алгоритм", "число итераций (эпох бустинга)", "итераций после ранней остановки", "learning rate", "глубина дерева", "L2-регуляризация",
           "квантили для коридора", "проверка", "доля для ранней остановки", "seed", "функции потерь"])
params["значение"] = params["значение"].astype(str)

page = f"""<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ледокол: метрики CatBoost</title>
<style>
body{{font:16px/1.55 system-ui,"Segoe UI",sans-serif;color:#1c2128;margin:0;background:#f6f8fa}}
main{{max-width:1080px;margin:0 auto;padding:32px 20px 60px}}
h1{{font-size:30px;margin:0 0 4px}} h2{{margin:44px 0 8px;font-size:23px;border-bottom:2px solid #d0d7de;padding-bottom:6px}}
p.lead{{color:#57606a;margin:0 0 20px}} .card{{background:#fff;border:1px solid #d0d7de;border-radius:10px;padding:16px 18px;margin:14px 0;overflow-x:auto}}
img{{max-width:100%;height:auto}} table.t{{border-collapse:collapse;width:100%;font-size:14.5px}}
table.t th,table.t td{{padding:7px 10px;border-bottom:1px solid #eaeef2;text-align:right}} table.t th:first-child,table.t td:first-child{{text-align:left}}
table.p td{{text-align:left}} table.t thead th{{background:#f0f3f6}} .note{{color:#57606a;font-size:14px}} .kpi{{display:flex;gap:12px;flex-wrap:wrap}}
.kpi div{{flex:1;min-width:150px;background:#fff;border:1px solid #d0d7de;border-radius:10px;padding:12px 14px}} .kpi b{{display:block;font-size:26px;color:#1f6feb}}
</style><main>
<h1>Ледокол: метрики CatBoost</h1>
<p class="lead">Поиск кассовых разрывов за 30 рабочих дней вперёд. Данные: 150 компаний, окна прогноза каждые 5 дней. Все числа посчитаны по сохранённым оценкам моделей на компаниях, которых модель при обучении не видела.</p>

<h2>1. Модель в двух словах</h2>
<div class="card"><p>CatBoost оценивает накопленный денежный поток компании за h дней вперёд (h от 1 до 30), в единицах дневных оборотов. Одна модель выдаёт среднюю оценку, вторая 9 квантилей. Из квантилей строится коридор P10–P90 и вероятность разрыва (доля сценариев, где остаток уходит ниже нуля). Признаки: средний поток за 5, 20 и 60 дней, разброс, доля дней с поступлениями, лаги, число налоговых дней, календарь, отрасль.</p>
<p class="note">Слово «эпоха» для бустинга означает итерацию, то есть одно добавленное дерево. Нейросетевых эпох здесь нет.</p></div>
<div class="card">{params.to_html(classes="t p", border=0, header=False)}</div>
<div class="card">{html_table(FD)}<p class="note">«RMSE обучение» ниже «RMSE ранняя остановка» и «RMSE тест», это нормально. Разрыв между проверкой и тестом небольшой, значит модель не переобучена.</p></div>
<div class="card">{figs['learn']}<p class="note">Синие линии — ошибка на обучении, красные — на проверочных компаниях. Пунктир — итерация, на которой обучение остановили. После неё ошибка на проверке перестаёт падать.</p></div>

<h2>2. Метрики CatBoost</h2>
<div class="kpi">
<div><b>{TA.loc['CatBoost','ROC-AUC']:.3f}</b>ROC-AUC</div><div><b>{TA.loc['CatBoost','PR-AUC']:.3f}</b>PR-AUC</div>
<div><b>{TA.loc['CatBoost','precision']:.2f}</b>precision</div><div><b>{TA.loc['CatBoost','recall']:.2f}</b>recall</div><div><b>{TA.loc['CatBoost','F1']:.2f}</b>F1</div></div>
<div class="card">{html_table(TA.drop(columns='порог'))}<p class="note">{nA} окон, из них с разрывом {posA} ({posA/nA:.0%}). Precision, recall и F1 — при пороге, лучшем по F1 (у CatBoost {TA.loc['CatBoost','порог']:.2f}).</p></div>
<div class="card">{figs['cm_a']}<p class="note">Строка — что было на деле, столбец — что сказала модель. Нижний левый угол: пропущенные разрывы, верхний правый: ложные тревоги.</p></div>
<div class="card">{figs['curves_a']}</div>
<div class="card">{figs['cal']}<p class="note">Чем ближе линия калибровки к диагонали, тем честнее вероятности. Справа видно, насколько оценки двух классов перекрываются, это и ограничивает качество.</p></div>
<div class="card">{figs['folds']}</div>

<h2>3. Остаток на счёте</h2>
<div class="card">{html_table(REG)}<p class="note">Ошибки RMSE и MAE в дневных оборотах компании на горизонтах 5–30 дней, покрытие коридора P10–P90 (идеал 0,8) и pinball-loss. Меньше — лучше.</p></div>

<h2>4. Проверка на других моделях</h2>
<p class="lead">Сравнение на {n} одинаковых окнах (с разрывом {pos}, {pos/n:.0%}), горизонт 30 дней, 5 фолдов по компаниям. Гибрид — статистический прогноз (Монте-Карло). CatBoost-классификатор — все признаки, включая прогноз гибрида. TabPFN — готовая предобученная табличная модель. «CatBoost + TabPFN» — среднее их оценок.</p>
<div class="card">{html_table(T.drop(columns=['порог']))}</div>
<div class="card">{figs['bars']}</div>
<div class="card">{figs['curves_b']}</div>
<div class="card">{figs['cm_b']}</div>
<div class="card">{figs['hor']}<p class="note">Качество растёт с горизонтом: на коротких сроках разрывов мало, и их труднее поймать.</p></div>

<h2>5. Категоризация операций</h2>
<div class="card"><p>Отдельная модель: TF-IDF по символьным n-граммам и логистическая регрессия, 27 категорий. На компаниях, которых модель не видела, accuracy 1,00 при исходных назначениях платежей и 0,97 (macro-F1 0,95), когда у каждого назначения вычеркнуто 30% слов. Единица получилась потому, что правильными ответами служит разметка правилами, на которой модель и учится. Модель выучила правила и сохраняет качество на искажённых текстах, к поиску разрывов она отношения не имеет.</p>
{figs['lc']}</div>

<h2>6. Что показывает проверка</h2>
<div class="card"><ul>
<li>Модели близки: ROC-AUC лежит в пределах {T['ROC-AUC'].min():.2f}–{T['ROC-AUC'].max():.2f}. Расширенные признаки, настройка параметров и смеси потолок не сдвинули, он задаётся информацией в данных.</li>
<li>TabPFN даёт лучшую точность тревог (precision {T.loc['TabPFN','precision']:.2f}), CatBoost-классификатор находит больше разрывов (recall {T.loc['CatBoost-классификатор','recall']:.2f}).</li>
<li>Чтобы находить 80% разрывов, приходится терпеть ложные тревоги: precision при recall 0,8 составляет {T['precision при recall 0,8'].min():.2f}–{T['precision при recall 0,8'].max():.2f}. Одновременно 80% по precision и recall на этих данных недостижимы.</li>
</ul></div>
</main></html>"""
OUT.write_text(page, encoding="utf-8")
print("готово:", OUT, f"{OUT.stat().st_size / 1e6:.1f} МБ")
print(CFG)
print(T.round(3).to_string())
print(TA.round(3).to_string())
