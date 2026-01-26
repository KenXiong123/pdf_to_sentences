# build_egarch_dataset.py
# -*- coding: utf-8 -*-
"""
构建 EGARCH 回归用的日度数据集：egarch_daily_data_roberta.csv

输入文件（文件名保持不变）：
- daily_returns_4idx.csv
- macro_controls_daily.csv
- gdp_events.csv
- policy_events.csv
- report_dates.csv
- tone_by_quarter_roberta.csv

核心口径（新变量）：
- 文本变量（季度）：tone_p90_policy_z, tone_p90_macro_z, tone_p90_all_z
- 文本质量（季度）：Similarity, Readability（由 similarity_prev / avg_sent_len 构造并在季度层 Z-score）
- 事件映射：strict next trading day（即使 event_date 本身是交易日，也映射到下一交易日）
- 报告窗口：可扩展到 t..t+W（默认 W=0）。为了避免“窗口越大冲击越大”，会对连续变量做等分缩放。

输出列至少包含（供 run_egarch.r 使用）：
date, SH, SZ, HS300, CSI500,
S_gdp, D_gdp, S_policy, D_policy,
D_report, Similarity, Readability,
tone_p90_policy_z, tone_p90_macro_z, tone_p90_all_z
"""

import os
import numpy as np
import pandas as pd

RET_FILE    = "daily_returns_4idx.csv"
MACRO_FILE  = "macro_controls_daily.csv"
GDP_FILE    = "gdp_events.csv"
POLICY_FILE = "policy_events.csv"
REPORT_FILE = "report_dates.csv"
TONEQ_FILE  = "tone_by_quarter_roberta.csv"
OUT_FILE    = "egarch_daily_data_roberta.csv"

# ===== 可调参数 =====
# 报告窗口向后扩展天数：0=只在反应日（t）有冲击；1= t 与 t+1；2= t..t+2
REPORT_WINDOW_FORWARD = 5
# 连续变量（tone/Similarity/Readability/D_report）在窗口内的分配方式：
# - "equal": 等分到窗口每一天（总冲击守恒，推荐）
# - "none" : 每一天都赋同一个值（会放大总冲击，不推荐）
WINDOW_SCALE = "equal"
# ====================


def _strict_next_trading_day(event_dates: pd.Series, trading_days: np.ndarray) -> pd.Series:
    """
    strict next trading day:
    - 若 event_date 是交易日 -> 映射到下一交易日
    - 若 event_date 不是交易日 -> 映射到之后第一个交易日
    - 若超出样本最后交易日 -> NaT
    """
    td = np.asarray(trading_days, dtype="datetime64[ns]")
    ev = pd.to_datetime(event_dates).values.astype("datetime64[ns]")

    # searchsorted: insertion index of ev in td (left)
    idx = np.searchsorted(td, ev, side="left")

    # 如果 ev 恰好等于某个交易日，则 strict next -> idx+1
    in_range = idx < len(td)
    eq_mask = np.zeros_like(in_range, dtype=bool)
    eq_mask[in_range] = td[idx[in_range]] == ev[in_range]
    idx = idx + eq_mask.astype(int)

    # 安全取值：先 mask 再索引，避免 idx==len(td) 触发越界
    out = np.full(len(ev), np.datetime64("NaT"), dtype="datetime64[ns]")
    ok = idx < len(td)
    out[ok] = td[idx[ok]]

    return pd.to_datetime(out)


def _zscore_series(x: pd.Series) -> pd.Series:
    x = pd.to_numeric(x, errors="coerce")
    mu = x.mean(skipna=True)
    sd = x.std(skipna=True)
    if sd is None or not np.isfinite(sd) or sd == 0:
        return pd.Series(np.zeros(len(x)), index=x.index)
    return (x - mu) / sd


def main():
    print("[INFO] Building EGARCH daily dataset (p90 tone + similarity/readability)...")

    # -------- 1) 日度收益率（交易日基准） --------
    if not os.path.exists(RET_FILE):
        raise FileNotFoundError(f"Missing {RET_FILE}")
    df = pd.read_csv(RET_FILE)
    if "date" not in df.columns:
        raise ValueError("daily_returns_4idx.csv must contain 'date'")
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    trading_days = df["date"].values.astype("datetime64[ns]")

    # 初始化事件列
    for c in ["S_gdp", "D_gdp", "S_policy", "D_policy"]:
        if c not in df.columns:
            df[c] = 0.0
    df["D_report"] = 0.0
    df["Similarity"] = 0.0
    df["Readability"] = 0.0
    for c in ["tone_p90_policy_z", "tone_p90_macro_z", "tone_p90_all_z"]:
        df[c] = 0.0

    # -------- 2) 合并宏观控制（可选） --------
    if os.path.exists(MACRO_FILE):
        mc = pd.read_csv(MACRO_FILE)
        if "date" in mc.columns:
            mc["date"] = pd.to_datetime(mc["date"])
            df = df.merge(mc, on="date", how="left")

    # -------- 3) GDP 事件：strict next trading day --------
    if os.path.exists(GDP_FILE):
        g = pd.read_csv(GDP_FILE)
        if "event_date" not in g.columns:
            raise ValueError("gdp_events.csv must contain 'event_date'")
        for col in ["S_gdp", "D_gdp"]:
            if col not in g.columns:
                raise ValueError(f"gdp_events.csv missing '{col}'")
        g["event_date"] = pd.to_datetime(g["event_date"])
        # 只保留样本期内的事件（避免样本外事件被映射到样本首日造成堆叠）
        g = g[(g["event_date"] >= df["date"].min()) & (g["event_date"] <= df["date"].max())]
        if len(g) == 0:
            pass

        g["date_mapped"] = _strict_next_trading_day(g["event_date"], trading_days)
        g = g.dropna(subset=["date_mapped"])
        g = g.groupby("date_mapped", as_index=False).agg({"S_gdp": "sum", "D_gdp": "max"})
        df = df.merge(g.rename(columns={"date_mapped": "date"}), on="date", how="left", suffixes=("", "_g"))
        df["S_gdp"] = df["S_gdp_g"].fillna(df["S_gdp"])
        df["D_gdp"] = df["D_gdp_g"].fillna(df["D_gdp"])
        df = df.drop(columns=["S_gdp_g", "D_gdp_g"])

    # -------- 4) Policy 事件：strict next trading day --------
    if os.path.exists(POLICY_FILE):
        p = pd.read_csv(POLICY_FILE)
        if "event_date" not in p.columns:
            raise ValueError("policy_events.csv must contain 'event_date'")
        for col in ["S_policy", "D_policy"]:
            if col not in p.columns:
                raise ValueError(f"policy_events.csv missing '{col}'")
        p["event_date"] = pd.to_datetime(p["event_date"])
        # 只保留样本期内的事件（避免样本外事件被映射到样本首日造成堆叠）
        p = p[(p["event_date"] >= df["date"].min()) & (p["event_date"] <= df["date"].max())]
        if len(p) == 0:
            pass

        p["date_mapped"] = _strict_next_trading_day(p["event_date"], trading_days)
        p = p.dropna(subset=["date_mapped"])
        p = p.groupby("date_mapped", as_index=False).agg({"S_policy": "sum", "D_policy": "max"})
        df = df.merge(p.rename(columns={"date_mapped": "date"}), on="date", how="left", suffixes=("", "_p"))
        df["S_policy"] = df["S_policy_p"].fillna(df["S_policy"])
        df["D_policy"] = df["D_policy_p"].fillna(df["D_policy"])
        df = df.drop(columns=["S_policy_p", "D_policy_p"])

    # -------- 5) 报告日 + tone（季度 -> 映射到报告反应日，支持窗口） --------
    if not os.path.exists(REPORT_FILE):
        raise FileNotFoundError(f"Missing {REPORT_FILE}")
    rpt = pd.read_csv(REPORT_FILE)
    if not {"year", "quarter", "report_date"}.issubset(rpt.columns):
        raise ValueError("report_dates.csv must contain columns: year, quarter, report_date")
    rpt["report_date"] = pd.to_datetime(rpt["report_date"])
    # 只保留样本期内的报告（避免样本外报告被映射到样本首日造成堆叠）
    rpt = rpt[(rpt["report_date"] >= df["date"].min()) & (rpt["report_date"] <= df["date"].max())]

    rpt["date_mapped"] = _strict_next_trading_day(rpt["report_date"], trading_days)
    rpt = rpt.dropna(subset=["date_mapped"])

    if not os.path.exists(TONEQ_FILE):
        raise FileNotFoundError(f"Missing {TONEQ_FILE}")
    tq = pd.read_csv(TONEQ_FILE)

    required_tone_cols = {"year", "quarter", "tone_p90_policy_z", "tone_p90_macro_z", "tone_p90_all_z"}
    if not required_tone_cols.issubset(tq.columns):
        miss = sorted(list(required_tone_cols - set(tq.columns)))
        raise ValueError(f"tone_by_quarter_roberta.csv missing columns: {miss}")

    # 构造季度层 Similarity/Readability（Z-score）
    # Similarity: similarity_prev（季度之间相似度），Readability: avg_sent_len（句长越长越难读）
    if "similarity_prev" in tq.columns:
        tq["Similarity_q"] = _zscore_series(tq["similarity_prev"]).fillna(0.0)
    else:
        tq["Similarity_q"] = 0.0

    if "avg_sent_len" in tq.columns:
        tq["Readability_q"] = _zscore_series(tq["avg_sent_len"]).fillna(0.0)
    else:
        tq["Readability_q"] = 0.0

    tq_keep = tq[["year", "quarter", "tone_p90_policy_z", "tone_p90_macro_z", "tone_p90_all_z", "Similarity_q", "Readability_q"]].copy()
    rpt = rpt.merge(tq_keep, on=["year", "quarter"], how="left")

    # 缺失按 0（只影响少数季度）
    for c in ["tone_p90_policy_z", "tone_p90_macro_z", "tone_p90_all_z", "Similarity_q", "Readability_q"]:
        rpt[c] = pd.to_numeric(rpt[c], errors="coerce").fillna(0.0)

    # 把季度值写入日度（支持窗口）
    # 为避免窗口扩大导致总冲击放大：WINDOW_SCALE="equal" 时按 (W+1) 等分
    W = int(REPORT_WINDOW_FORWARD)
    scale = 1.0
    if WINDOW_SCALE == "equal":
        scale = 1.0 / (W + 1.0)
    elif WINDOW_SCALE == "none":
        scale = 1.0
    else:
        raise ValueError("WINDOW_SCALE must be 'equal' or 'none'")

    date_to_idx = {pd.Timestamp(d): i for i, d in enumerate(df["date"])}

    for _, row in rpt.iterrows():
        t0 = pd.Timestamp(row["date_mapped"])
        if t0 not in date_to_idx:
            continue
        i0 = date_to_idx[t0]
        for k in range(0, W + 1):
            j = i0 + k
            if j >= len(df):
                break
            # 连续冲击/质量指标按 scale 分摊
            df.loc[j, "D_report"] += 1.0 * scale
            df.loc[j, "tone_p90_policy_z"] += float(row["tone_p90_policy_z"]) * scale
            df.loc[j, "tone_p90_macro_z"]  += float(row["tone_p90_macro_z"]) * scale
            df.loc[j, "tone_p90_all_z"]    += float(row["tone_p90_all_z"]) * scale
            df.loc[j, "Similarity"]        += float(row["Similarity_q"]) * scale
            df.loc[j, "Readability"]       += float(row["Readability_q"]) * scale

    # -------- 6) 整理输出 --------
    # 事件列缺失 -> 0
    for c in ["S_gdp", "D_gdp", "S_policy", "D_policy", "D_report", "Similarity", "Readability",
              "tone_p90_policy_z", "tone_p90_macro_z", "tone_p90_all_z"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    # 输出列：先保证 R 端需要的列都在，再附加其他控制变量
    core_cols = [
        "date", "SH", "SZ", "HS300", "CSI500",
        "S_gdp", "D_gdp", "S_policy", "D_policy",
        "D_report", "Readability", "Similarity",
        "tone_p90_policy_z", "tone_p90_macro_z", "tone_p90_all_z"
    ]
    missing_core = [c for c in core_cols if c not in df.columns]
    if missing_core:
        raise ValueError(f"Output is missing required columns (unexpected): {missing_core}")

    other_cols = [c for c in df.columns if c not in core_cols]
    out = df[core_cols + other_cols].copy()

    out.to_csv(OUT_FILE, index=False)
    print(f"[OK] Saved: {OUT_FILE}")
    print("[CHECK] Nonzero counts:",
          "D_report=", int((out["D_report"] != 0).sum()),
          "tone_policy=", int((out["tone_p90_policy_z"] != 0).sum()),
          "tone_macro=", int((out["tone_p90_macro_z"] != 0).sum()),
          "tone_all=", int((out["tone_p90_all_z"] != 0).sum()),
          "Similarity=", int((out["Similarity"] != 0).sum()),
          "Readability=", int((out["Readability"] != 0).sum()),
          )
    print("[CHECK] Std:",
          "Similarity=", float(out["Similarity"].std()),
          "Readability=", float(out["Readability"].std())
          )


if __name__ == "__main__":
    main()
