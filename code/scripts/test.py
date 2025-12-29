# -*- coding: utf-8 -*-
"""
QA for sentence extraction results.

Reads `all_sentences.csv` produced by pdf_to_sentences.py and outputs:
1) qa_sentences_summary.csv : per-report metrics + flags
2) qa_sentences_flagged_samples.txt : samples for reports that are flagged

Design goals:
- Catch common PDF noise: page numbers, TOC lines, figure/table captions, sources/notes, excessive duplicates.
- Add "over-cleaning" smoke tests: extremely low digit/monetary-term coverage, abnormal sentence count.

Usage:
    python test_v2.py
    python test_v2.py --input all_sentences.csv --out-summary qa_sentences_summary.csv --out-flagged qa_sentences_flagged_samples.txt
"""
import re
import argparse
import pandas as pd
import numpy as np


# -----------------------------
# Patterns
# -----------------------------
RE_SPACE = re.compile(r"\s+")
RE_PAGE = re.compile(r"^(第?\s*\d+\s*页|page\s*\d+|\d+\s*/\s*\d+|-\s*\d+\s*-|^\d{1,4}\s*$)$", re.I)
RE_TOC = re.compile(r"(\.{3,}|…{2,})\s*\d+\s*$")
RE_TABLEFIG = re.compile(r"(?:^|[（(])\s*(表|图|专栏)\s*\d+|^(表|图|专栏)\s*\d+|数据来源|资料来源|来源[:：]|注[:：]|说明[:：]", re.I)

# monetary / macro terms (rough, conservative)
RE_POLICY_TERMS = re.compile(
    r"(LPR|贷款市场报价利率|MLF|中期借贷便利|逆回购|公开市场|政策利率|降息|加息|"
    r"存款准备金|准备金率|降准|上调准备金率|下调准备金率|"
    r"信贷|贷款|社融|社会融资|融资|"
    r"汇率|外汇|人民币|"
    r"CPI|PPI|通胀|物价|"
    r"GDP|经济增长|增速|"
    r"房地产|住房|按揭|"
    r"利率|国债收益率|收益率曲线)",
    re.I
)

RE_ECON_NUM = re.compile(
    r"(同比|环比|增速|增长|下降|上升|回落|回升|提高|降低|"
    r"百分点|bp|达到|为|分别|高于|低于|保持|持平|"
    r"万亿元|亿元|万|%|％)",
    re.I
)

RE_HAS_DIGIT = re.compile(r"\d")


def normalize_text(s: str) -> str:
    s = str(s or "").strip()
    s = RE_SPACE.sub(" ", s)
    return s


def compute_report_metrics(d: pd.DataFrame) -> dict:
    texts = d["text"].astype(str).map(normalize_text)
    lens = texts.str.len()

    n = int(len(d))
    if n == 0:
        return {
            "n_sentences": 0,
            "mean_len": 0.0,
            "p50_len": 0.0,
            "p90_len": 0.0,
            "share_short": 0.0,
            "share_long": 0.0,
            "dup_ratio": 0.0,
            "share_page": 0.0,
            "share_toc": 0.0,
            "share_tablefig": 0.0,
            "share_digit": 0.0,
            "share_policy_terms": 0.0,
            "share_econ_num": 0.0,
            "keyword_group_count": 0,
        }

    # duplicates within report (normalized)
    dup_ratio = float(texts.duplicated().mean())

    is_page = texts.map(lambda x: bool(RE_PAGE.search(x)))
    is_toc = texts.map(lambda x: bool(RE_TOC.search(x)))
    is_tablefig = texts.map(lambda x: bool(RE_TABLEFIG.search(x)))
    has_digit = texts.map(lambda x: bool(RE_HAS_DIGIT.search(x)))
    has_policy = texts.map(lambda x: bool(RE_POLICY_TERMS.search(x)))
    econ_num = texts.map(lambda x: bool(RE_HAS_DIGIT.search(x) and RE_ECON_NUM.search(x)))

    # keyword groups coverage (for over-cleaning smoke test)
    groups = {
        "rates": re.compile(r"(LPR|贷款市场报价利率|MLF|逆回购|公开市场|政策利率|降息|加息|利率|收益率)", re.I),
        "reserve": re.compile(r"(存款准备金|准备金率|降准|上调准备金率|下调准备金率)", re.I),
        "credit": re.compile(r"(信贷|贷款|社融|社会融资|融资)", re.I),
        "fx": re.compile(r"(汇率|外汇|人民币)", re.I),
        "inflation": re.compile(r"(CPI|PPI|通胀|物价)", re.I),
        "growth": re.compile(r"(GDP|经济增长|增速|增长)", re.I),
        "property": re.compile(r"(房地产|住房|按揭)", re.I),
    }
    group_hits = {k: bool(texts.str.contains(pat).any()) for k, pat in groups.items()}
    group_count = int(sum(group_hits.values()))

    return {
        "n_sentences": n,
        "mean_len": float(lens.mean()),
        "p50_len": float(lens.quantile(0.50)),
        "p90_len": float(lens.quantile(0.90)),
        "share_short": float((lens < 8).mean()),
        "share_long": float((lens > 120).mean()),
        "dup_ratio": dup_ratio,
        "share_page": float(is_page.mean()),
        "share_toc": float(is_toc.mean()),
        "share_tablefig": float(is_tablefig.mean()),
        "share_digit": float(has_digit.mean()),
        "share_policy_terms": float(has_policy.mean()),
        "share_econ_num": float(econ_num.mean()),
        "keyword_group_count": group_count,
        **{f"has_{k}": int(v) for k, v in group_hits.items()},
    }


def robust_bounds(x: pd.Series) -> tuple[float, float]:
    """IQR-based robust bounds."""
    q1 = x.quantile(0.25)
    q3 = x.quantile(0.75)
    iqr = q3 - q1
    lo = q1 - 1.5 * iqr
    hi = q3 + 1.5 * iqr
    return float(lo), float(hi)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="all_sentences.csv")
    ap.add_argument("--out-summary", default="qa_sentences_summary.csv")
    ap.add_argument("--out-flagged", default="qa_sentences_flagged_samples.txt")
    ap.add_argument("--sample-per-flag", type=int, default=6, help="how many sample sentences per report per reason")
    args = ap.parse_args()

    df = pd.read_csv(args.input, dtype={"year": int, "quarter": int})
    need_cols = {"year", "quarter", "section", "section_title", "sent_id_in_report", "text"}
    missing = need_cols - set(df.columns)
    if missing:
        raise ValueError(f"缺列：{missing}")

    # basic clean
    df["text"] = df["text"].astype(str).map(normalize_text)
    df["section_title"] = df["section_title"].astype(str).fillna("").map(normalize_text)
    df["len"] = df["text"].str.len()

    # compute metrics per report
    rows = []
    keys = df[["year", "quarter"]].drop_duplicates().sort_values(["year", "quarter"])
    for y, q in keys.itertuples(index=False):
        d = df[(df["year"] == y) & (df["quarter"] == q)].copy()
        m = compute_report_metrics(d)
        m["year"] = int(y)
        m["quarter"] = int(q)
        rows.append(m)

    s = pd.DataFrame(rows).sort_values(["year", "quarter"]).reset_index(drop=True)

    # -----------------------------
    # Flagging rules (data-driven + conservative hard thresholds)
    # -----------------------------
    # sentence count: use robust bounds, plus keep your original intuition that <300 or >650 is worth a look
    lo_n, hi_n = robust_bounds(s["n_sentences"])
    # shares: robust bounds
    lo_tf, hi_tf = robust_bounds(s["share_tablefig"])
    lo_page, hi_page = robust_bounds(s["share_page"])
    lo_dup, hi_dup = robust_bounds(s["dup_ratio"])
    lo_digit, hi_digit = robust_bounds(s["share_digit"])
    lo_policy, hi_policy = robust_bounds(s["share_policy_terms"])
    lo_econ, hi_econ = robust_bounds(s["share_econ_num"])

    def add_flags(r):
        flags = []

        # count outliers
        if r["n_sentences"] < max(50, lo_n, 300):  # 300 is a practical low bound for this dataset
            flags.append("LOW_N")
        if r["n_sentences"] > min(5000, hi_n, 700):  # keep conservative high bound
            flags.append("HIGH_N")

        # noise shares
        if r["share_tablefig"] > max(0.02, hi_tf):  # 2% is a practical threshold
            flags.append("HAS_TABLEFIG")
        if r["share_page"] > max(0.005, hi_page):  # >0.5% page-ish lines
            flags.append("HAS_PAGE")
        if r["share_toc"] > 0.002:
            flags.append("HAS_TOC")
        if r["dup_ratio"] > max(0.01, hi_dup):
            flags.append("HIGH_DUP")

        # over-cleaning smoke tests:
        # Extremely low digit/policy/econ-numeric coverage relative to dataset
        # (flag only when it's a strong outlier)
        if (r["share_digit"] < max(0.01, lo_digit) and r["n_sentences"] < s["n_sentences"].median()):
            flags.append("SUSPECT_OVERCLEAN_DIGIT")
        if (r["share_policy_terms"] < max(0.005, lo_policy) and r["year"] >= 2010):
            flags.append("SUSPECT_OVERCLEAN_POLICY")
        if (r["share_econ_num"] < max(0.003, lo_econ) and r["year"] >= 2010):
            flags.append("SUSPECT_OVERCLEAN_ECONNUM")

        # content coverage heuristic (avoid early years)
        if r["year"] >= 2015 and r["keyword_group_count"] <= 1:
            flags.append("LOW_COVERAGE")

        return ",".join(flags)

    s["flags"] = s.apply(add_flags, axis=1)

    # Save summary
    s.to_csv(args.out_summary, index=False, encoding="utf-8-sig")
    print(f"[OK] summary saved -> {args.out_summary}")

    # -----------------------------
    # Flagged samples
    # -----------------------------
    flagged = s[s["flags"] != ""].copy()
    print(f"[INFO] flagged count: {len(flagged)}")

    def top_examples(d: pd.DataFrame, mask: pd.Series, k: int) -> list[str]:
        dd = d[mask].copy()
        if dd.empty:
            return []
        # prefer longer examples for easier diagnosis
        return dd.sort_values("len", ascending=False)["text"].head(k).tolist()

    with open(args.out_flagged, "w", encoding="utf-8") as f:
        for _, r in flagged.iterrows():
            y, q = int(r["year"]), int(r["quarter"])
            f.write("=" * 90 + "\n")
            f.write(f"{y}Q{q} | flags={r['flags']}\n")
            f.write(f"n={r['n_sentences']}, tablefig={r['share_tablefig']:.4f}, page={r['share_page']:.4f}, "
                    f"dup={r['dup_ratio']:.4f}, digit={r['share_digit']:.4f}, policy={r['share_policy_terms']:.4f}, "
                    f"econ_num={r['share_econ_num']:.4f}, group_cnt={int(r['keyword_group_count'])}\n")

            d = df[(df["year"] == y) & (df["quarter"] == q)].copy()

            # section title preview
            titles = (d.groupby("section")["section_title"]
                      .agg(lambda x: list(pd.unique([t for t in x if t]))[:2])).to_dict()
            f.write("section_titles: " + str(titles) + "\n")

            # samples by reason
            f.write("\n-- Examples: TABLE/FIG-like (if any)\n")
            for t in top_examples(d, d["text"].str.contains(RE_TABLEFIG), args.sample_per_flag):
                f.write("  " + t + "\n")

            f.write("\n-- Examples: PAGE-like (if any)\n")
            for t in top_examples(d, d["text"].map(lambda x: bool(RE_PAGE.search(x))), args.sample_per_flag):
                f.write("  " + t + "\n")

            f.write("\n-- Examples: very short (<8 chars)\n")
            for t in top_examples(d, d["len"] < 8, args.sample_per_flag):
                f.write("  " + t + "\n")

            f.write("\n-- Examples: econ-numeric (digit + econ words)\n")
            econ_mask = d["text"].str.contains(RE_HAS_DIGIT) & d["text"].str.contains(RE_ECON_NUM)
            for t in top_examples(d, econ_mask, args.sample_per_flag):
                f.write("  " + t + "\n")

            f.write("\n-- TOP longest\n")
            for t in d.sort_values("len", ascending=False)["text"].head(3).tolist():
                f.write("  " + t + "\n")

    print(f"[OK] flagged samples -> {args.out_flagged}")


if __name__ == "__main__":
    main()
