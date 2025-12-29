import os
from pathlib import Path
import pandas as pd
import numpy as np

# ========= 配置 =========
SENT_FILE = "all_sentences_with_roberta_score.csv"
OUT_FILE = "tone_by_quarter_roberta.csv"
SENT_BUCKET_OUT = "all_sentences_with_roberta_score_bucket.csv"
REPORT_DATES_FILE = "report_dates.csv"
AUDIT = True

# 仍然计算 expanding z 作为备选稳健性（不用于主回归）
CALC_EXPANDING_Z = True
MIN_HIST_QUARTERS = 8


# ========= Topic buckets: policy / macro / risk =========
# 说明：
# 1) 先用 section_title（章节标题）判别；若缺失或无法判别，再用句子 text 的关键词兜底。
# 2) 规则完全确定性，可复制；关键词表可在论文附录披露。
# --------------------------------------------------------

TITLE_POLICY_KW = [
    "货币政策", "政策取向", "下一阶段", "政策思路", "政策操作", "政策工具", "操作", "工具",
    "利率", "准备金率", "存款准备金", "流动性", "公开市场", "再贷款", "再贴现", "MLF", "SLF", "LPR",
]
TITLE_MACRO_KW = [
    "经济", "宏观", "形势", "运行", "增长", "物价", "通胀", "就业", "国际收支", "外部环境", "金融形势",
]
TITLE_RISK_KW = [
    "风险", "不确定", "金融稳定", "稳定", "脆弱", "隐患", "压力",
]

TEXT_POLICY_KW = [
    "保持流动性", "合理充裕", "逆周期", "调节", "稳健", "灵活适度", "相机抉择",
    "降准", "降息", "加息", "上调", "下调", "公开市场操作", "利率走廊", "融资成本",
    "MLF", "SLF", "LPR", "再贷款", "再贴现", "中期借贷便利", "常备借贷便利",
]
TEXT_MACRO_KW = [
    "GDP", "经济增长", "消费", "投资", "出口", "进口", "工业", "服务业", "CPI", "PPI",
    "物价", "通胀", "就业", "收入", "PMI", "国际收支", "外需", "汇率", "财政",
]
TEXT_RISK_KW = [
    "风险", "不确定性", "波动", "压力", "脆弱", "隐患", "违约", "信用风险", "系统性",
    "金融稳定", "杠杆", "泡沫", "房地产风险", "地方债", "影子银行", "外溢", "资本流动冲击",
]

def _kw_score(s: str, kws):
    if not isinstance(s, str):
        return 0
    ss = s.strip()
    if not ss:
        return 0
    return sum(1 for kw in kws if kw and (kw in ss))

def assign_bucket(section_title: str, text: str):
    """返回 (bucket, source)，bucket ∈ {policy, macro, risk}"""
    title = section_title if isinstance(section_title, str) else ""
    sent = text if isinstance(text, str) else ""

    # 1) 标题优先（权重更高）
    t_r = _kw_score(title, TITLE_RISK_KW)
    t_p = _kw_score(title, TITLE_POLICY_KW)
    t_m = _kw_score(title, TITLE_MACRO_KW)
    if max(t_r, t_p, t_m) > 0:
        if t_r >= max(t_p, t_m):
            return "risk", "title"
        if t_p >= max(t_r, t_m):
            return "policy", "title"
        return "macro", "title"

    # 2) 句子关键词兜底（risk > policy > macro，避免风险沟通漏判）
    s_r = _kw_score(sent, TEXT_RISK_KW)
    s_p = _kw_score(sent, TEXT_POLICY_KW)
    s_m = _kw_score(sent, TEXT_MACRO_KW)
    if max(s_r, s_p, s_m) > 0:
        if s_r >= max(s_p, s_m):
            return "risk", "text"
        if s_p >= max(s_r, s_m):
            return "policy", "text"
        return "macro", "text"

    # 3) 默认：macro（描述性内容占比最高）
    return "macro", "default"
# =======================


def _resolve(path_str: str) -> Path:
    """优先当前工作目录，其次脚本目录。"""
    p = Path(path_str)
    if p.exists():
        return p
    p2 = Path(__file__).resolve().parent / path_str
    if p2.exists():
        return p2
    raise FileNotFoundError(f"找不到文件：{path_str}（当前目录或脚本目录）")


def zscore_full_sample(s: pd.Series) -> pd.Series:
    """全样本 z-score（主回归口径）"""
    m = s.mean()
    std = s.std(ddof=1)
    if std == 0 or pd.isna(std):
        return pd.Series([0.0] * len(s), index=s.index)
    return (s - m) / std


def zscore_full(s: pd.Series):
    """full-sample z-score（用于主回归，与你当前 tone_all_z 一致）"""
    mu = s.mean(skipna=True)
    sd = s.std(ddof=1, skipna=True)
    if sd is None or sd == 0 or np.isnan(sd):
        return (s * 0.0).fillna(0.0)
    z = (s - mu) / sd
    z = z.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return z


def zscore_expanding_no_lookahead(s: pd.Series, min_hist_quarters: int = 8):
    """
    expanding z-score（无前视，备选稳健性）：
    z_t 使用 t 之前的历史均值与标准差；历史不足期 z=0，并给出 avail=0。
    """
    hist_mean = s.expanding(min_periods=min_hist_quarters).mean().shift(1)
    hist_std = s.expanding(min_periods=min_hist_quarters).std(ddof=1).shift(1)
    z = (s - hist_mean) / hist_std
    avail = hist_std.notna().astype(int)
    z = z.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return z, avail


def _is_real_part(year, quarter, section: str) -> bool:
    sec = str(section).strip()
    try:
        y = int(year)
        q = int(quarter)
    except Exception:
        return False
    if y == 2002 and q == 3:
        return sec in ["S1", "S2", "S3"]
    return sec in ["S1", "S2", "S3", "S4"]


def _is_guidance_part(year, quarter, section: str) -> bool:
    sec = str(section).strip()
    try:
        y = int(year)
        q = int(quarter)
    except Exception:
        return False
    if y == 2002 and q == 3:
        return sec == "S4"
    return sec == "S5"


def main():
    # ---------- 读句子数据 ----------
    df = pd.read_csv(_resolve(SENT_FILE))

    required_cols = {"year", "quarter", "section", "roberta_neg_prob", "text"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"{SENT_FILE} 缺少必要列：{missing}")

    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["quarter"] = pd.to_numeric(df["quarter"], errors="coerce").astype("Int64")

    if AUDIT:
        bad_yq = df["year"].isna() | df["quarter"].isna()
        print(f"[AUDIT] year/quarter NA rows: {bad_yq.sum()} / {len(df)}")
        bad_q = (~df["quarter"].isin([1, 2, 3, 4])) & df["quarter"].notna()
        print(f"[AUDIT] quarter not in 1-4 rows: {bad_q.sum()} / {len(df)}")
        neg = df["roberta_neg_prob"]
        out01 = ((neg < 0) | (neg > 1)) & neg.notna()
        print(f"[AUDIT] roberta_neg_prob out of [0,1]: {out01.sum()} / {len(df)}")

    # ---------- 句子 tone ----------
    df["tone_sent"] = 1.0 - df["roberta_neg_prob"]

    # ---------- Bucket（policy/macro/risk） ----------
    if "section_title" not in df.columns:
        df["section_title"] = ""
    bucket_out = df.apply(lambda r: assign_bucket(r.get("section_title", ""), r.get("text", "")), axis=1)
    df["bucket"] = bucket_out.apply(lambda x: x[0])
    df["bucket_source"] = bucket_out.apply(lambda x: x[1])

    if AUDIT:
        print("[AUDIT] bucket_source distribution:")
        print(df["bucket_source"].value_counts(dropna=False).to_string())
        print("[AUDIT] bucket distribution:")
        print(df["bucket"].value_counts(dropna=False).to_string())

        # 输出带 bucket 的句子级数据（便于审计/复现实验）
        try:
            keep_cols = [c for c in ["id","year","quarter","section","section_title","bucket","bucket_source","roberta_neg_prob","tone_sent","text"] if c in df.columns]
            df[keep_cols].to_csv(_resolve(SENT_BUCKET_OUT), index=False, encoding="utf-8-sig")
            print(f"[AUDIT] sentence-level bucket file saved: {SENT_BUCKET_OUT}")
        except Exception as e:
            print(f"[AUDIT] failed to save sentence-level bucket file: {e}")



    # ---------- Real / Guidance 标记 ----------
    df["is_real"] = df.apply(lambda r: _is_real_part(r["year"], r["quarter"], r["section"]), axis=1)
    df["is_guid"] = df.apply(lambda r: _is_guidance_part(r["year"], r["quarter"], r["section"]), axis=1)

    grp = ["year", "quarter"]

    # ---------- Bucket 季度聚合（mean / p90 / std） ----------
    g = df.groupby(grp + ["bucket"], dropna=True)["tone_sent"]
    bucket_agg = g.agg(
        tone_mean="mean",
        tone_p90=lambda x: x.quantile(0.9),
        tone_std=lambda x: x.std(ddof=1),
        n="size",
    ).reset_index()

    # pivot 到宽表
    def _pivot(metric, prefix):
        wide = bucket_agg.pivot_table(index=grp, columns="bucket", values=metric, aggfunc="first").reset_index()
        wide.columns = [c if c in grp else f"{prefix}_{c}" for c in wide.columns]
        return wide

    tone_bucket_mean = _pivot("tone_mean", "tone")
    tone_bucket_p90 = _pivot("tone_p90", "tone_p90")
    tone_bucket_std = _pivot("tone_std", "tone_std")
    tone_bucket_n = _pivot("n", "n")

    # 合并 bucket 指标（与 tone_all/real/guid 并存）
    tone_bucket = tone_bucket_mean.merge(tone_bucket_p90, on=grp, how="left") \
                                .merge(tone_bucket_std, on=grp, how="left") \
                                .merge(tone_bucket_n, on=grp, how="left")

    # 缺失填充：n=0；tone 指标缺失保留 NaN（后续 z-score 会转 0）
    for c in [c for c in tone_bucket.columns if c.startswith("n_")]:
        tone_bucket[c] = tone_bucket[c].fillna(0).astype(int)


    # ---------- 季度聚合 ----------
    tone_all = (
        df.groupby(grp, dropna=True)["tone_sent"]
        .mean()
        .reset_index()
        .rename(columns={"tone_sent": "tone_all"})
    )
    tone_real = (
        df[df["is_real"]]
        .groupby(grp, dropna=True)["tone_sent"]
        .mean()
        .reset_index()
        .rename(columns={"tone_sent": "tone_real"})
    )
    tone_guid = (
        df[df["is_guid"]]
        .groupby(grp, dropna=True)["tone_sent"]
        .mean()
        .reset_index()
        .rename(columns={"tone_sent": "tone_guid"})
    )

    tone_q = (
        tone_all
        .merge(tone_real, on=grp, how="left")
        .merge(tone_guid, on=grp, how="left")
        .sort_values(grp)
        .reset_index(drop=True)
    )

    # ---------- merge bucket metrics ----------
    tone_q = tone_q.merge(tone_bucket, on=grp, how="left")

    # ---------- 主口径：全样本 z-score（用于回归） ----------
    tone_q["tone_all_z"] = zscore_full_sample(tone_q["tone_all"])
    tone_q["tone_real_z"] = zscore_full_sample(tone_q["tone_real"])
    tone_q["tone_guid_z"] = zscore_full_sample(tone_q["tone_guid"])

    # ---------- Bucket z-score（full-sample；用于主回归） ----------
    for base in ["tone_policy", "tone_macro", "tone_risk",
                 "tone_p90_policy", "tone_p90_macro", "tone_p90_risk",
                 "tone_std_policy", "tone_std_macro", "tone_std_risk"]:
        if base in tone_q.columns:
            tone_q[base + "_z"] = zscore_full(tone_q[base])


    # ---------- 备选：expanding z-score（不用于主回归，仅供稳健性） ----------
    if CALC_EXPANDING_Z:
        tone_q["tone_all_z_exp"], tone_q["tone_all_z_exp_avail"] = zscore_expanding_no_lookahead(
            tone_q["tone_all"], MIN_HIST_QUARTERS
        )
        tone_q["tone_real_z_exp"], tone_q["tone_real_z_exp_avail"] = zscore_expanding_no_lookahead(
            tone_q["tone_real"], MIN_HIST_QUARTERS
        )
        tone_q["tone_guid_z_exp"], tone_q["tone_guid_z_exp_avail"] = zscore_expanding_no_lookahead(
            tone_q["tone_guid"], MIN_HIST_QUARTERS
        )

        # bucket mean 的 expanding z（可选稳健性）
        for base in ["tone_policy", "tone_macro", "tone_risk"]:
            if base in tone_q.columns:
                tone_q[base + "_z_exp"], tone_q[base + "_z_exp_avail"] = zscore_expanding_no_lookahead(
                    tone_q[base], MIN_HIST_QUARTERS
                )

    # ---------- 合并报告日期（按 tone_q 的季度做 inner，自动丢弃 2025Q1-Q3） ----------
    try:
        rep = pd.read_csv(_resolve(REPORT_DATES_FILE))
        if {"year", "quarter"}.issubset(rep.columns):
            rep["year"] = pd.to_numeric(rep["year"], errors="coerce").astype("Int64")
            rep["quarter"] = pd.to_numeric(rep["quarter"], errors="coerce").astype("Int64")
            rep = rep.dropna(subset=["year", "quarter"]).drop_duplicates(subset=["year", "quarter"])

            # 关键：只保留在 tone_q 中存在的季度（解决你看到的 3/99 缺失）
            rep = rep.merge(tone_q[["year", "quarter"]], on=["year", "quarter"], how="inner")

            keep = ["year", "quarter"] + (["report_date"] if "report_date" in rep.columns else [])
            tone_q = tone_q.merge(rep[keep], on=["year", "quarter"], how="left")

            if AUDIT:
                chk = rep[["year", "quarter"]].merge(
                    tone_q[["year", "quarter", "tone_all"]],
                    on=["year", "quarter"],
                    how="left",
                )
                miss_tone = chk["tone_all"].isna().sum()
                print(f"[AUDIT] report quarters missing tone_all: {miss_tone} / {len(chk)}")
        else:
            print(f"[WARN] {REPORT_DATES_FILE} 不含 year/quarter，跳过合并。")
    except FileNotFoundError:
        print(f"[WARN] 未找到 {REPORT_DATES_FILE}，跳过合并报告日期。")

    # ---------- Guidance 覆盖审计 ----------
    if AUDIT:
        cnt_guid = (
            df[df["is_guid"]]
            .groupby(grp, dropna=True)
            .size()
            .rename("n_guid")
            .reset_index()
        )
        tmp = tone_q.merge(cnt_guid, on=grp, how="left")
        tmp["n_guid"] = tmp["n_guid"].fillna(0).astype(int)
        zero_guid = tmp[tmp["n_guid"] == 0]
        print(f"[AUDIT] quarters with n_guid==0: {len(zero_guid)}")

    # ---------- 保护：如果 OUT_FILE 已有额外列（如 similarity_prev/avg_sent_len），合并保留 ----------
    out_path = Path(OUT_FILE)
    if out_path.exists():
        old = pd.read_csv(out_path)
        if {"year", "quarter"}.issubset(old.columns):
            old["year"] = pd.to_numeric(old["year"], errors="coerce").astype("Int64")
            old["quarter"] = pd.to_numeric(old["quarter"], errors="coerce").astype("Int64")
            extra_cols = [c for c in old.columns if c not in tone_q.columns]
            if extra_cols:
                tone_q = tone_q.merge(old[["year", "quarter"] + extra_cols], on=["year", "quarter"], how="left")

    tone_q.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"[OK] RoBERTa 季度语气指标已保存到：{out_path}")
    if AUDIT:
        print(tone_q.head())


if __name__ == "__main__":
    main()
