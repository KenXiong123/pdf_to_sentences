#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
build_event_shocks_daily.py

输入：
- survey.xlsx   : Bloomberg GDP survey（含 公布日期、观测日期、调查中值/平均、实际）
- S_Policy.xlsx     : Wind 宽表（行=指标，列=日期，包含同业拆借7天加权利率、RRR变动公告日期等）
- policy_dates.xlsx : 你手工整理的政策公告日（借贷利率调整、SLF 等；含 date/rate_policy/slf 列）

输出：
- gdp_events.csv
- policy_events.csv

GDP口径：
- event_date = 公布日期（真实公布日）
- year/quarter = 由观测日期（季度末）推得
- S_gdp = actual - forecast（forecast 优先调查中值，其次平均调查值；缺失则 S_gdp=0 且 forecast_available=0）
- D_gdp = 1

Policy口径：
- D_policy：每个工具若有“公告日期/变动公告日期/公布日期”行→用公告日期；否则用变动点
  * 变动点：
    - 稀疏行：直接用非空日期列
    - 密集水平序列：用数值发生变化的日期（diff != 0）
- S_policy：用 interbank_7d（银行间同业拆借加权利率:7天）
  S_policy(t) = r(t+1) - r(t-1)
  其中 t 为事件日映射到利率序列的最近可用日期（on/after）
"""

import argparse
import datetime as dt
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import numpy as np
import pandas as pd

ANNOUNCE_TOKENS = ["公告日期", "变动公告日期", "公布日期"]




# ----------------------------
# New: policy_dates.xlsx loader
# ----------------------------

def _collapse_consecutive_days(dates: List[pd.Timestamp]) -> List[pd.Timestamp]:
    """若同一类事件在数据里出现连续多天=1，仅保留每段连续区间的第一天。"""
    if not dates:
        return []
    ds = sorted(pd.to_datetime(pd.Series(dates)).dt.normalize().unique().tolist())
    out = []
    prev = None
    for d in ds:
        if prev is None or (d - prev).days > 1:
            out.append(d)
        prev = d
    return out


def load_policy_dates_xlsx(policy_dates_xlsx: Path) -> Dict[str, List[pd.Timestamp]]:
    """
    读取你整理的 policy_dates.xlsx（长表），输出：
      - RateAdj: 借贷利率调整公告日（rate_policy==1）
      - SLF    : SLF 公告日（slf==1）
    允许存在重复日期/连续日期；会做去重并压缩连续区间。
    """
    df = pd.read_excel(policy_dates_xlsx, sheet_name=0, engine="openpyxl")
    if df.empty:
        return {"RateAdj": [], "SLF": []}

    # normalize column names
    cols_lower = {c: str(c).strip().lower() for c in df.columns}
    df = df.rename(columns=cols_lower)

    if "date" not in df.columns:
        # fallback: take first column as date
        df = df.rename(columns={df.columns[0]: "date"})

    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["date"]).copy()

    out: Dict[str, List[pd.Timestamp]] = {"RateAdj": [], "SLF": []}

    if "rate_policy" in df.columns:
        out["RateAdj"] = _collapse_consecutive_days(df.loc[df["rate_policy"].astype(int) == 1, "date"].tolist())

    if "slf" in df.columns:
        out["SLF"] = _collapse_consecutive_days(df.loc[df["slf"].astype(int) == 1, "date"].tolist())

    return out

# ----------------------------
# Helpers
# ----------------------------

def _as_float(x):
    if pd.isna(x):
        return np.nan
    if isinstance(x, str):
        s = x.strip()
        if s in ("--", "", "NA", "N/A"):
            return np.nan
    return pd.to_numeric(x, errors="coerce")


def _is_announce_row(name: str) -> bool:
    return isinstance(name, str) and any(tok in name for tok in ANNOUNCE_TOKENS)


def _date_cols_raw(df: pd.DataFrame) -> List:
    """
    S_Policy.xlsx 的日期列通常是 datetime.datetime（而不是 pd.Timestamp）
    这里返回“原始列名”列表，后续用这些列名取数值最稳妥。
    """
    out = []
    for c in df.columns:
        if isinstance(c, (pd.Timestamp, dt.datetime, dt.date)):
            out.append(c)
    return out


def _row_nonnull_count(row: pd.Series, dcols_raw: List) -> int:
    return int(pd.notna(row[dcols_raw]).sum())


def _extract_event_dates_from_sparse_row(row: pd.Series, dcols_raw: List) -> List[pd.Timestamp]:
    """
    稀疏行（或公告日期行）：非空的日期列就是事件日
    """
    ev = []
    for c in dcols_raw:
        if pd.notna(row[c]):
            ev.append(pd.to_datetime(c))
    return ev


def _extract_change_points_from_level_row(row: pd.Series, dcols_raw: List) -> List[pd.Timestamp]:
    """
    密集水平序列：取“数值发生变化”的日期作为变动点
    """
    idx = pd.to_datetime(dcols_raw)
    s = pd.Series(row[dcols_raw].values, index=idx).sort_index()
    s = s.dropna().astype(float)
    if s.empty:
        return []
    diff = s.diff()
    return diff[diff.abs() > 1e-12].index.tolist()


def _map_to_rate_calendar(d: pd.Timestamp, rate_index: pd.DatetimeIndex) -> Optional[pd.Timestamp]:
    """
    将事件日映射到利率序列的“最近可用日期”（>=d），若超出则取最后一天
    """
    if d is pd.NaT or pd.isna(d):
        return None
    pos = rate_index.searchsorted(d)
    if pos < len(rate_index):
        return rate_index[pos]
    return rate_index[-1] if len(rate_index) else None


# ----------------------------
# GDP: survey.xlsx
# ----------------------------

def build_gdp_events_from_survey(survey_xlsx: Path, start_year: int = 2001) -> pd.DataFrame:
    raw = pd.read_excel(survey_xlsx, sheet_name=0, engine="openpyxl")
    cols = list(raw.columns)
    if len(cols) < 7:
        raise ValueError("survey.xlsx format not recognized (need >=7 columns).")

    # 你这份 survey.xlsx 的结构（按截图）：
    # col0: 公布日期  col1: 观测日期  col2: 调查中值  col3: 平均调查值  col6: 实际
    c_release, c_obs, c_median, c_mean, _, _, c_actual = cols[:7]

    df = raw.copy()

    # survey 里是 mm/dd/yyyy 字符串，指定 format 避免 “could not infer format” 警告
    df["release_date"] = pd.to_datetime(df[c_release], errors="coerce", format="%m/%d/%Y")
    df["obs_date"] = pd.to_datetime(df[c_obs], errors="coerce", format="%m/%d/%Y")

    # 只保留真正的数据行
    df = df.dropna(subset=["release_date", "obs_date"]).copy()

    df["median"] = df[c_median].apply(_as_float)
    df["mean"] = df[c_mean].apply(_as_float)
    df["actual"] = df[c_actual].apply(_as_float)

    # year/quarter from obs_date（季度末）
    q = df["obs_date"].dt.to_period("Q")
    df["year"] = q.dt.year.astype(int)
    df["quarter"] = q.dt.quarter.astype(int)

    df = df[df["year"] >= start_year].copy()
    df = df.sort_values(["year", "quarter", "release_date"]).reset_index(drop=True)

    # forecast: median 优先，其次 mean
    df["gdp_forecast"] = df["median"].where(df["median"].notna(), df["mean"])
    df["forecast_available"] = df["gdp_forecast"].notna().astype(int)

    df["gdp_yoy"] = df["actual"]
    df["S_gdp"] = df["gdp_yoy"] - df["gdp_forecast"]
    df.loc[df["forecast_available"] == 0, "S_gdp"] = 0.0

    df["D_gdp"] = 1

    # ✅ 关键修复：先生成 event_date，再去选列
    df["event_date"] = df["release_date"].dt.date.astype(str)
    df["obs_date_str"] = df["obs_date"].dt.date.astype(str)

    out = df[
        ["event_date", "year", "quarter", "obs_date_str",
         "gdp_yoy", "gdp_forecast", "forecast_available",
         "S_gdp", "D_gdp"]
    ].rename(columns={"obs_date_str": "obs_date"}).copy()

    # 若同一季度有重复（极少数情况），保留最后一次 release_date 的记录
    out = out.sort_values(["year", "quarter", "event_date"]).drop_duplicates(["year", "quarter"], keep="last")
    out = out.reset_index(drop=True)
    return out


# ----------------------------
# Policy: S_Policy.xlsx
# ----------------------------

def _extract_tool_events(df: pd.DataFrame, tool_filter, tool_key: str) -> Tuple[List[pd.Timestamp], str]:
    dcols_raw = _date_cols_raw(df)
    cand = df[df["指标名称"].apply(tool_filter)].copy()
    if cand.empty:
        return [], "no_candidates"

    # 1) 如果存在任何“公告日期行”，则 UNION 所有公告日期行（RRR 大小行就需要这样）
    ann = cand[cand["指标名称"].apply(_is_announce_row)]
    if not ann.empty:
        ev_set = set()
        for _, r in ann.iterrows():
            ev_set.update(_extract_event_dates_from_sparse_row(r, dcols_raw))
        return sorted(ev_set), "announce_union"

    # 2) 否则，用最稀疏行作为“变动点载体”
    counts = cand.apply(lambda r: _row_nonnull_count(r, dcols_raw), axis=1)
    row = df.loc[counts.idxmin()]

    nn = _row_nonnull_count(row, dcols_raw)
    if nn > 500:
        return _extract_change_points_from_level_row(row, dcols_raw), "change_points_from_level"
    else:
        return _extract_event_dates_from_sparse_row(row, dcols_raw), "change_points_sparse"


def build_policy_events_from_spolicy(spolicy_xlsx: Path, policy_dates_xlsx: Optional[Path] = None, include_lpr_in_D_policy: bool = False) -> pd.DataFrame:
    df = pd.read_excel(spolicy_xlsx, sheet_name=0, engine="openpyxl")
    df = df.dropna(subset=["指标名称"]).copy()

    dcols_raw = _date_cols_raw(df)
    if len(dcols_raw) == 0:
        raise ValueError("No date columns detected in S_Policy.xlsx")

    # interbank 7d weighted rate series (for S_policy)
    def is_interbank_7d(name: str) -> bool:
        return isinstance(name, str) and ("同业拆借" in name) and ("加权利率" in name) and ("7天" in name)

    inter_cand = df[df["指标名称"].apply(is_interbank_7d)]
    if inter_cand.empty:
        raise ValueError("Cannot find '银行间同业拆借加权利率:7天' in S_Policy.xlsx")
    inter_row = inter_cand.iloc[0]

    interbank = pd.Series(inter_row[dcols_raw].values, index=pd.to_datetime(dcols_raw)).sort_index()
    interbank = interbank.dropna().astype(float)
    if interbank.empty:
        raise ValueError("Interbank 7d series empty after dropping NA.")
    rate_idx = interbank.index
    # ----------------------------
    # Policy event dates (D_policy)
    # ----------------------------
    # 1) RRR announce dates from S_Policy.xlsx (these rows are sparse: non-NA cells indicate change announcement dates)
    def is_rrr_announce(name: str) -> bool:
        return (
            isinstance(name, str)
            and ("存款准备金率" in name)
            and any(tok in name for tok in ANNOUNCE_TOKENS)
        )

    events: Dict[str, List[pd.Timestamp]] = {}

    rrr_ev, _how = _extract_tool_events(df, is_rrr_announce, "RRR")
    events["RRR"] = rrr_ev

    # 2) Additional policy dates from your curated policy_dates.xlsx (RateAdj & SLF)
    if policy_dates_xlsx is not None:
        p = Path(policy_dates_xlsx)
        if p.exists():
            ext = load_policy_dates_xlsx(p)
            if ext.get("RateAdj"):
                events["RateAdj"] = ext["RateAdj"]
            if ext.get("SLF"):
                events["SLF"] = ext["SLF"]

    # 3) (Optional) include LPR 1Y changes into D_policy (only if the sheet provides announce dates; otherwise skip)
    if include_lpr_in_D_policy:
        # Only include LPR if the sheet provides an announce-date style row; do NOT infer from daily level change-points
        def is_lpr_announce(name: str) -> bool:
            return (
                isinstance(name, str)
                and ("LPR" in name)
                and ("1年" in name)
                and any(tok in name for tok in ANNOUNCE_TOKENS)
            )
        ev, _how = _extract_tool_events(df, is_lpr_announce, "LPR1Y")
        if ev:
            events["LPR1Y"] = ev

    # master event dates

    all_dates = sorted({d.normalize() for lst in events.values() for d in lst if d is not pd.NaT})
    out = pd.DataFrame({"event_date_raw": all_dates})

    # component dummies
    for k, lst in events.items():
        sset = {d.normalize() for d in lst}
        out[f"D_{k}"] = out["event_date_raw"].apply(lambda x: 1 if x.normalize() in sset else 0).astype(int)

    d_cols = [c for c in out.columns if c.startswith("D_")]
    out["D_policy"] = (out[d_cols].sum(axis=1) > 0).astype(int)

    # compute S_policy on mapped interbank calendar: r(t+1)-r(t-1) for each event
    mapped_dates = []
    s_policy = []
    avail = []

    for d_raw in out["event_date_raw"]:
        d_used = _map_to_rate_calendar(pd.to_datetime(d_raw), rate_idx)
        mapped_dates.append(d_used)

        if d_used is None or pd.isna(d_used):
            s_policy.append(0.0)
            avail.append(0)
            continue

        pos = rate_idx.searchsorted(d_used)
        if pos >= len(rate_idx) or rate_idx[pos] != d_used:
            # 极少数情况下（重复/精度问题）做一次兜底
            try:
                pos = int(np.where(rate_idx == d_used)[0][0])
            except Exception:
                s_policy.append(0.0)
                avail.append(0)
                continue

        if pos <= 0 or pos >= len(rate_idx) - 1:
            s_policy.append(0.0)
            avail.append(0)
            continue

        s_policy.append(float(interbank.iloc[pos + 1] - interbank.iloc[pos - 1]))
        avail.append(1)

    out["interbank_date_used"] = pd.to_datetime(pd.Series(mapped_dates))
    out["S_policy"] = np.array(s_policy, dtype=float)
    out["S_policy_available"] = np.array(avail, dtype=int)

    # format dates as strings
    out["event_date"] = pd.to_datetime(out["event_date_raw"]).dt.date.astype(str)
    out["event_date_raw"] = pd.to_datetime(out["event_date_raw"]).dt.date.astype(str)
    out["interbank_date_used"] = pd.to_datetime(out["interbank_date_used"]).dt.date.astype("string")

    keep = ["event_date", "event_date_raw", "D_policy", "S_policy", "S_policy_available", "interbank_date_used"] + d_cols
    out = out[keep].sort_values("event_date").reset_index(drop=True)
    return out


# ----------------------------
# Main
# ----------------------------

def main():
    parser = argparse.ArgumentParser(description="Build GDP & Policy event shocks using survey.xlsx + S_Policy.xlsx")

    parser.add_argument("--survey_xlsx", type=str, default="survey.xlsx")
    parser.add_argument("--spolicy_xlsx", type=str, default="S_Policy.xlsx")
    parser.add_argument("--policy_dates_xlsx", type=str, default="policy_dates.xlsx",
                        help="Curated policy announcement dates (date/rate_policy/slf).")

    parser.add_argument("--out_dir", type=str, default=".")
    parser.add_argument("--start_year", type=int, default=2001)

    parser.add_argument("--include_lpr_in_D_policy", action="store_true",
                        help="Include LPR 1Y into D_policy (announce-first else change-point).")

    args = parser.parse_args()

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    survey_path = Path(args.survey_xlsx).expanduser()
    spolicy_path = Path(args.spolicy_xlsx).expanduser()

    if not survey_path.exists():
        raise FileNotFoundError(f"survey_xlsx not found: {survey_path}")
    if not spolicy_path.exists():
        raise FileNotFoundError(f"spolicy_xlsx not found: {spolicy_path}")

    gdp_events = build_gdp_events_from_survey(survey_path, start_year=args.start_year)
    gdp_out = out_dir / "gdp_events.csv"
    gdp_events.to_csv(gdp_out, index=False, encoding="utf-8-sig")
    print(f"[OK] wrote: {gdp_out}  rows={len(gdp_events)}")

    policy_events = build_policy_events_from_spolicy(
        spolicy_path,
        policy_dates_xlsx=Path(args.policy_dates_xlsx).expanduser(),
        include_lpr_in_D_policy=args.include_lpr_in_D_policy
    )
    pol_out = out_dir / "policy_events.csv"
    policy_events.to_csv(pol_out, index=False, encoding="utf-8-sig")
    print(f"[OK] wrote: {pol_out}  rows={len(policy_events)}")


if __name__ == "__main__":
    main()
