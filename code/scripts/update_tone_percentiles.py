# update_tone_percentiles.py
# -*- coding: utf-8 -*-
"""
根据句子级 bucket 文件，更新季度 tone_by_quarter_roberta.csv 中的尾部指标。

用途：避免重新运行 build_roberta_tone.py 的 zero-shot 推理，直接在已有的
all_sentences_with_roberta_score_bucket.csv 上重新计算 p95/p97.5 等尾部统计。

输入文件（文件名保持不变）：
- all_sentences_with_roberta_score_bucket.csv
- tone_by_quarter_roberta.csv

输出文件（默认覆盖 tone_by_quarter_roberta.csv）：
- tone_by_quarter_roberta.csv
"""

import argparse
import os
from typing import Iterable

import numpy as np
import pandas as pd

BUCKET_FILE = "all_sentences_with_roberta_score_bucket.csv"
TONE_FILE = "tone_by_quarter_roberta.csv"

TOPIC_KEYS = ["policy", "macro"]


def _require_columns(df: pd.DataFrame, cols: Iterable[str], name: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{name} missing required columns: {missing}")


def _percentile_or_nan(values: np.ndarray, pct: float) -> float:
    if len(values) == 0:
        return float("nan")
    return float(np.percentile(values, pct))


def main() -> None:
    parser = argparse.ArgumentParser(description="Update tone tail percentiles from bucket file")
    parser.add_argument("--bucket", default=BUCKET_FILE, help="Sentence-level bucket CSV")
    parser.add_argument("--tone", default=TONE_FILE, help="Quarterly tone CSV to update")
    parser.add_argument(
        "--percentile",
        type=float,
        default=97.5,
        help="Tail percentile for topic-level tone (e.g., 95 or 97.5)",
    )
    parser.add_argument(
        "--topics",
        nargs="*",
        default=TOPIC_KEYS,
        help="Topics to update (default: policy macro)",
    )
    args = parser.parse_args()

    if not os.path.exists(args.bucket):
        raise FileNotFoundError(f"Bucket file not found: {args.bucket}")
    if not os.path.exists(args.tone):
        raise FileNotFoundError(f"Tone file not found: {args.tone}")

    bucket = pd.read_csv(args.bucket, encoding="utf-8-sig")
    tone = pd.read_csv(args.tone, encoding="utf-8-sig")

    bucket_required = {"year", "quarter", "roberta_neg_prob"}
    _require_columns(bucket, bucket_required, "Bucket file")

    for topic in args.topics:
        wcol = f"weight_{topic}"
        _require_columns(bucket, [wcol], "Bucket file")

    _require_columns(tone, {"year", "quarter"}, "Tone file")

    bucket["year"] = pd.to_numeric(bucket["year"], errors="coerce").astype("Int64")
    bucket["quarter"] = pd.to_numeric(bucket["quarter"], errors="coerce").astype("Int64")
    bucket = bucket.dropna(subset=["year", "quarter"]).copy()
    bucket["roberta_neg_prob"] = pd.to_numeric(bucket["roberta_neg_prob"], errors="coerce")

    tone = tone.copy()
    tone["year"] = pd.to_numeric(tone["year"], errors="coerce").astype("Int64")
    tone["quarter"] = pd.to_numeric(tone["quarter"], errors="coerce").astype("Int64")

    bucket_grouped = bucket.groupby(["year", "quarter"], sort=True)

    for topic in args.topics:
        pct_col = f"tone_p90_{topic}"
        values = []
        for (y, q), g in bucket_grouped:
            vals = pd.to_numeric(
                g.loc[g[f"weight_{topic}"] > 0, "roberta_neg_prob"],
                errors="coerce",
            ).dropna()
            values.append({"year": int(y), "quarter": int(q), pct_col: _percentile_or_nan(vals.values, args.percentile)})

        pct_df = pd.DataFrame(values)
        tone = tone.merge(pct_df, on=["year", "quarter"], how="left", suffixes=("", "_new"))
        if f"{pct_col}_new" in tone.columns:
            tone[pct_col] = tone[f"{pct_col}_new"]
            tone = tone.drop(columns=[f"{pct_col}_new"])

        zcol = f"{pct_col}_z"
        if zcol in tone.columns:
            mu = float(tone[pct_col].mean(skipna=True))
            sigma = float(tone[pct_col].std(skipna=True))
            if sigma == 0.0 or np.isnan(sigma):
                tone[zcol] = 0.0
            else:
                tone[zcol] = (tone[pct_col] - mu) / sigma

    tone = tone.sort_values(["year", "quarter"]).reset_index(drop=True)
    tone = tone.round(6)
    tone.to_csv(args.tone, index=False, encoding="utf-8-sig")

    print(f"✅ Updated {args.tone} using p{args.percentile} tails for topics: {', '.join(args.topics)}")


if __name__ == "__main__":
    main()
