# build_egarch_dataset.py
# -*- coding: utf-8 -*-

from __future__ import annotations
import pandas as pd
import numpy as np
from pathlib import Path


# =========================
# 配置：文件名（默认都在 scripts/ 下）
# =========================
DAILY_RETURNS = "daily_returns_4idx.csv"
MACRO_CONTROLS = "macro_controls_daily.csv"
TONE_QUARTER = "tone_by_quarter_roberta.csv"
REPORT_DATES = "report_dates.csv"
GDP_EVENTS = "gdp_events.csv"
POLICY_EVENTS = "policy_events.csv"

OUT_FILE = "egarch_daily_data_roberta.csv"

# 映射“事件自然日 -> 交易日”的规则：
# False = 严格用下一交易日（date > event_date）
# True  = 如果事件日当天就是交易日，则用当天（date >= event_date）
INCLUDE_SAME_DAY = False  # legacy (unused; kept for backward compat)
REPORT_INCLUDE_SAME_DAY = True   # 报告：若发布日是交易日则用当日，否则映射到下一交易日
GDP_INCLUDE_SAME_DAY = True      # GDP：同上（若公告日是交易日则用当日）
POLICY_INCLUDE_SAME_DAY = True   # 政策公告：同上（事件日是交易日则用当日）

# 分布滞后：为 tone 构造 L1..LK（交易日滞后）
# 建议 K=2 或 3；K 越大，事件稀疏时估计更不稳。
TONE_LAGS = 3


def _resolve(path: str) -> Path:
    """优先 scripts/，否则 code/data/，否则 code/"""
    script_dir = Path(__file__).resolve().parent
    base_dir = script_dir.parent

    cands = [
        script_dir / path,
        base_dir / "data" / path,
        base_dir / path,
    ]
    for p in cands:
        if p.exists():
            return p
    raise FileNotFoundError(f"找不到文件: {path}\n尝试路径:\n" + "\n".join(str(x) for x in cands))


def _output_path(filename: str) -> Path:
    """输出统一写到 scripts/ 下（不要求文件已存在）"""
    script_dir = Path(__file__).resolve().parent
    return script_dir / filename


def _map_to_trade_day(event_dates: pd.Series, trading_dates: np.ndarray, include_same_day: bool) -> pd.Series:
    """
    将自然日 event_date 映射到交易日：
      include_same_day=False: 取第一个 trading_date > event_date
      include_same_day=True : 取第一个 trading_date >= event_date
    """
    trade = []
    for d in event_dates:
        if pd.isna(d):
            trade.append(pd.NaT)
            continue

        if include_same_day:
            mask = trading_dates >= np.datetime64(d)
        else:
            mask = trading_dates > np.datetime64(d)

        if mask.sum() == 0:
            trade.append(pd.NaT)
        else:
            trade.append(trading_dates[mask.argmax()])

    return pd.to_datetime(trade)


def main():
    # -----------------------
    # 1) 读日度收益（交易日序列基准）
    # -----------------------
    daily = pd.read_csv(_resolve(DAILY_RETURNS))
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.sort_values("date").reset_index(drop=True)

    trading_dates = daily["date"].values

    # -----------------------
    # 2) 合并日度宏观控制（可选）
    # -----------------------
    try:
        macro = pd.read_csv(_resolve(MACRO_CONTROLS))
        macro["date"] = pd.to_datetime(macro["date"])
        daily = daily.merge(macro, on="date", how="left")
    except FileNotFoundError:
        pass

    # -----------------------
    # 3) 读季度 tone + 方差指标（tone_by_quarter_roberta.csv 已被 build_variance_indicators.py 补了 similarity/readability）
    # -----------------------
    tone = pd.read_csv(_resolve(TONE_QUARTER))
    if "Year" in tone.columns:
        tone = tone.rename(columns={"Year": "year"})
    if "Quarter" in tone.columns:
        tone = tone.rename(columns={"Quarter": "quarter"})

    tone["year"] = pd.to_numeric(tone["year"], errors="coerce").astype("Int64")
    tone["quarter"] = pd.to_numeric(tone["quarter"], errors="coerce").astype("Int64")

    if "tone_all" not in tone.columns:
        raise ValueError("tone_by_quarter_roberta.csv 缺少 tone_all，请先运行 build_roberta_tone.py")
    if "tone_all_z" not in tone.columns:
        # 全样本 z-score 兜底（你现在也偏好全样本口径）
        m = tone["tone_all"].mean()
        s = tone["tone_all"].std()
        tone["tone_all_z"] = 0.0 if (pd.isna(s) or s == 0) else (tone["tone_all"] - m) / s

    # 方差方程用到的列（有就用，没有就置 NA）
    for c in ["similarity_prev", "surprise_prev", "avg_sent_len"]:
        if c not in tone.columns:
            tone[c] = np.nan

    tone_keep = tone[["year", "quarter", "tone_all", "tone_all_z", "similarity_prev", "surprise_prev", "avg_sent_len"]].copy()

    # -----------------------
    # 4) 读报告发布日期 -> 映射到交易日 -> 生成 ToneAllEvent + D_report + Read/Sim/Surprise
    # -----------------------
    report = pd.read_csv(_resolve(REPORT_DATES))
    report["report_date"] = pd.to_datetime(report["report_date"])

    rep_tone = report.merge(tone_keep, on=["year", "quarter"], how="inner").sort_values("report_date").reset_index(drop=True)
    rep_tone["trade_date"] = _map_to_trade_day(rep_tone["report_date"], trading_dates, REPORT_INCLUDE_SAME_DAY)
    rep_tone = rep_tone.dropna(subset=["trade_date"]).copy()

    # 同一天若有多个报告（极少），取均值
    rep_by_day = (
        rep_tone.groupby("trade_date")
        .agg(
            tone_all=("tone_all", "mean"),
            tone_all_z=("tone_all_z", "mean"),
            similarity_prev=("similarity_prev", "mean"),
            surprise_prev=("surprise_prev", "mean"),
            avg_sent_len=("avg_sent_len", "mean"),
        )
        .reset_index()
        .rename(columns={"trade_date": "date"})
    )

    maps = {c: dict(zip(rep_by_day["date"], rep_by_day[c])) for c in rep_by_day.columns if c != "date"}

    def map_or_zero(src_col: str, dst_col: str):
        daily[dst_col] = daily["date"].map(maps.get(src_col, {})).fillna(0.0)

    map_or_zero("tone_all", "ToneAllEvent_raw")
    map_or_zero("tone_all_z", "ToneAllEvent_z")
    map_or_zero("avg_sent_len", "ReadabilityEvent")
    map_or_zero("similarity_prev", "SimilarityEvent")
    map_or_zero("surprise_prev", "PolicySurpriseEvent")

    # ✅ 修正：D_report 用“是否为报告事件日”判定，而不是靠 ToneAllEvent_z 是否为 0
    report_event_days = set(pd.to_datetime(rep_by_day["date"]))
    daily["D_report"] = daily["date"].isin(report_event_days).astype(int)

    # -----------------------
    # 4b) 分布滞后：构造 tone 的交易日滞后项
    #   - L0 为原始列（ToneAllEvent_raw / ToneAllEvent_z）
    #   - L1 表示前一交易日的 tone，依此类推
    # -----------------------
    for base in ["ToneAllEvent_raw", "ToneAllEvent_z"]:
        for k in range(1, TONE_LAGS + 1):
            daily[f"{base}_L{k}"] = daily[base].shift(k).fillna(0.0)


    # -----------------------
    # 5) 合并 GDP 事件（S_gdp, D_gdp, forecast availability）
    # -----------------------
    gdp = pd.read_csv(_resolve(GDP_EVENTS))
    if "event_date" not in gdp.columns:
        raise ValueError("gdp_events.csv 缺少 event_date 列（应为真实公布日）")
    if "S_gdp" not in gdp.columns or "D_gdp" not in gdp.columns or "forecast_available" not in gdp.columns:
        raise ValueError("gdp_events.csv 缺少必要列：S_gdp / D_gdp / forecast_available")

    gdp["event_date"] = pd.to_datetime(gdp["event_date"])
    gdp["trade_date"] = _map_to_trade_day(gdp["event_date"], trading_dates, GDP_INCLUDE_SAME_DAY)
    gdp = gdp.dropna(subset=["trade_date"]).copy()

    gdp_day = (
        gdp.groupby("trade_date")
        .agg(
            S_gdp=("S_gdp", "mean"),
            D_gdp=("D_gdp", "max"),
            GDPForecastAvailEvent=("forecast_available", "max"),
        )
        .reset_index()
        .rename(columns={"trade_date": "date"})
    )

    gdp_map = {c: dict(zip(gdp_day["date"], gdp_day[c])) for c in gdp_day.columns if c != "date"}
    daily["S_gdp"] = daily["date"].map(gdp_map.get("S_gdp", {})).fillna(0.0)
    daily["D_gdp"] = daily["date"].map(gdp_map.get("D_gdp", {})).fillna(0).astype(int)
    daily["GDPForecastAvailEvent"] = daily["date"].map(gdp_map.get("GDPForecastAvailEvent", {})).fillna(0).astype(int)

    # -----------------------
    # 6) 合并 Policy 事件（S_policy, D_policy）
    # -----------------------
    pol = pd.read_csv(_resolve(POLICY_EVENTS))
    if "event_date" not in pol.columns or "S_policy" not in pol.columns:
        raise ValueError("policy_events.csv 缺少必要列：event_date / S_policy")
    # 兼容：有的版本里可能是 D_policy_any
    dcol = "D_policy"
    if dcol not in pol.columns and "D_policy_any" in pol.columns:
        dcol = "D_policy_any"
    if dcol not in pol.columns:
        raise ValueError("policy_events.csv 缺少 D_policy（或 D_policy_any）列")

    pol["event_date"] = pd.to_datetime(pol["event_date"])
    pol["trade_date"] = _map_to_trade_day(pol["event_date"], trading_dates, POLICY_INCLUDE_SAME_DAY)
    pol = pol.dropna(subset=["trade_date"]).copy()

    pol_day = (
        pol.groupby("trade_date")
        .agg(
            S_policy=("S_policy", "mean"),
            D_policy=(dcol, "max"),
        )
        .reset_index()
        .rename(columns={"trade_date": "date"})
    )

    pol_map = {c: dict(zip(pol_day["date"], pol_day[c])) for c in pol_day.columns if c != "date"}
    daily["S_policy"] = daily["date"].map(pol_map.get("S_policy", {})).fillna(0.0)
    daily["D_policy"] = daily["date"].map(pol_map.get("D_policy", {})).fillna(0).astype(int)

    # -----------------------
    # 7) 保存（✅ 修复输出路径）
    # -----------------------
    out_path = _output_path(OUT_FILE)
    daily.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(f"[OK] 输出完成：{out_path}")
    print("[INFO] D_report=1 个数：", int(daily["D_report"].sum()))
    print("[INFO] D_gdp=1 个数：", int(daily["D_gdp"].sum()))
    print("[INFO] D_policy=1 个数：", int(daily["D_policy"].sum()))
    print(daily.head())


if __name__ == "__main__":
    main()