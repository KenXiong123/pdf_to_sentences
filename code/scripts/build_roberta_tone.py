# build_roberta_tone.py (v3)
# -*- coding: utf-8 -*-
"""
Step: 构建季度级文本语气指标（央行季度货币政策报告）

本版本输出 3 个核心指标（季度级）：
1) tone_policy_z  : 主题=货币政策与流动性（zero-shot NLI + 稀疏化）
2) tone_macro_z   : 主题=宏观基本面（zero-shot NLI + 稀疏化）
3) tone_all_z     : 全报告情绪（不依赖 zero-shot；用句子级 roberta_neg_prob 压缩为 1 个数字）

并同时输出：
- tone_by_quarter_roberta.csv（季度指标）
- tone_by_quarter_roberta_coverage.csv（诊断/覆盖）
- all_sentences_with_roberta_score_bucket.csv（句子级：主题分数、Top1、最终权重）

注意：保持输入/输出文件名与旧版本一致。
"""

import os
import math
import warnings
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import torch
from datasets import Dataset
from transformers import pipeline
from transformers.pipelines.pt_utils import KeyDataset

warnings.filterwarnings("ignore", category=UserWarning)

# ========== 文件名（保持不变） ==========
INPUT_FILE = "all_sentences_with_roberta_score.csv"
OUT_FILE = "tone_by_quarter_roberta.csv"
COVERAGE_OUT = "tone_by_quarter_roberta_coverage.csv"
BUCKET_OUT = "all_sentences_with_roberta_score_bucket.csv"

# ========== Zero-shot 配置 ==========
MODEL_NAME = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
HYPOTHESIS_TEMPLATE = "这段文字涉及{}。"

# 两个主题（更平行 + 提示词）
CANDIDATE_LABELS = [
    "货币政策与流动性（降准/降息/LPR/MLF/OMO/再贷款/信贷/社融/M2/资金面）",      # policy
    "经济运行与宏观基本面（GDP/就业/消费/投资/外贸/工业/PMI/景气度）",           # macro
]
TOPIC_KEYS = ["policy", "macro"]

# ========== 稀疏化参数（安全版） ==========
# 句子级：Top1 置信度阈值（基础阈值，季度级还会自适应放宽）
BASE_TAU = 0.50
RELAX_TAUS = [0.50, 0.45, 0.40]
GAP_THRESH = 0.10  # Top1-Top2 区分度阈值（小于则折扣）

# 季度级：Top-N 配额（自适应）
TOPN_FRAC = 0.12
TOPN_MIN = 30
TOPN_MAX = 80

# ========== tone_all 构建参数 ==========
# 每份报告取 Top-K “最有信息量句子”（按 |p - global_median|），再做截尾均值
TONE_ALL_TOPK_MAX = 200
TONE_ALL_TOPK_FRAC = 0.20
TONE_ALL_TOPK_MIN = 50
TONE_ALL_TRIM = 0.10  # 截尾比例（两端各去掉 10%）


# ========= 工具函数 =========
def get_device():
    """优先 MPS，其次 CUDA，否则 CPU"""
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return 0  # pipeline(device=0)
    return -1


def normalize_label_scores(out: Dict) -> Dict[str, float]:
    """把 pipeline 的 labels/scores 转成 dict"""
    labels = out.get("labels", [])
    scores = out.get("scores", [])
    return {str(l): float(s) for l, s in zip(labels, scores)}


def compute_gap_factor(top1: float, top2: float) -> float:
    """区分度折扣：gap>=阈值 -> 1；否则线性折扣到 0"""
    gap = float(top1 - top2)
    if gap >= GAP_THRESH:
        return 1.0
    if gap <= 0:
        return 0.0
    return gap / GAP_THRESH


def calc_topn(n_sent: int) -> int:
    if n_sent <= 0:
        return 0
    n = int(round(TOPN_FRAC * n_sent))
    return int(np.clip(n, TOPN_MIN, TOPN_MAX))


def trimmed_mean(x: np.ndarray, trim: float) -> float:
    if len(x) == 0:
        return float("nan")
    x = np.sort(np.asarray(x, dtype=float))
    if not (0.0 <= trim < 0.5):
        return float(np.mean(x))
    k = int(math.floor(trim * len(x)))
    if 2 * k >= len(x):
        return float(np.mean(x))
    return float(np.mean(x[k: len(x) - k]))


def build_tone_all_for_group(g: pd.DataFrame, global_med: float) -> Tuple[float, float, Dict]:
    """
    返回：tone_all（截尾均值）、tone_p90_all，以及 coverage dict
    """
    p = pd.to_numeric(g["roberta_neg_prob"], errors="coerce").dropna().astype(float).values
    n = len(p)
    if n == 0:
        return float("nan"), float("nan"), {"n_sent": 0, "k": 0, "k_eff": 0, "trim": TONE_ALL_TRIM}

    info = np.abs(p - global_med)
    # Top-K：min(200, 20%*n) 且至少 50（不够则取全部）
    k = int(min(TONE_ALL_TOPK_MAX, max(TONE_ALL_TOPK_MIN, int(round(TONE_ALL_TOPK_FRAC * n)))))
    k = int(min(k, n))
    if k <= 0:
        k = n

    # 取 top-k
    idx = np.argpartition(-info, k - 1)[:k]
    sel = p[idx]

    tone_all = trimmed_mean(sel, TONE_ALL_TRIM)
    tone_p90 = float(np.percentile(sel, 90)) if len(sel) > 0 else float("nan")

    cov = {
        "n_sent": int(n),
        "k": int(k),
        "k_eff": int(len(sel)),
        "trim": float(TONE_ALL_TRIM),
        "global_median": float(global_med),
        "tone_all_raw": float(tone_all) if not np.isnan(tone_all) else float("nan"),
        "tone_p90_raw": float(tone_p90) if not np.isnan(tone_p90) else float("nan"),
    }
    return tone_all, tone_p90, cov


def main():
    if not os.path.exists(INPUT_FILE):
        raise FileNotFoundError(f"Input file not found: {INPUT_FILE}")

    print(f"[Info] Loading {INPUT_FILE} ...")
    df = pd.read_csv(INPUT_FILE, encoding="utf-8-sig")
    required = {"year", "quarter", "text", "roberta_neg_prob"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns in {INPUT_FILE}: {missing}")

    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["quarter"] = pd.to_numeric(df["quarter"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["year", "quarter", "text"]).copy()
    df["text"] = df["text"].astype(str)
    df["roberta_neg_prob"] = pd.to_numeric(df["roberta_neg_prob"], errors="coerce")

    # ========== 0) 全局中位数（tone_all 用） ==========
    global_med = float(df["roberta_neg_prob"].median(skipna=True))
    print(f"[Info] Global median(roberta_neg_prob) = {global_med:.6f}")

    # ========== 1) Zero-shot 分类 ==========
    print("[Info] Building zero-shot pipeline ...")
    device = get_device()
    clf = pipeline(
        "zero-shot-classification",
        model=MODEL_NAME,
        device=device,
    )

    # 只对文本做推理
    ds = Dataset.from_pandas(df[["text"]].reset_index(drop=True))
    print("[Info] Running zero-shot classification (this can take a while) ...")

    outputs = []
    for out in clf(
        KeyDataset(ds, "text"),
        candidate_labels=CANDIDATE_LABELS,
        hypothesis_template=HYPOTHESIS_TEMPLATE,
        multi_label=True,
        batch_size=16,
        truncation=True,
    ):
        outputs.append(out)

    # 把输出拼回 df
    score_policy = []
    score_macro = []
    top1_label = []
    top1_score = []
    top2_score = []
    gap_factor = []

    for out in outputs:
        sc = normalize_label_scores(out)
        sp = float(sc.get(CANDIDATE_LABELS[0], 0.0))
        sm = float(sc.get(CANDIDATE_LABELS[1], 0.0))
        score_policy.append(sp)
        score_macro.append(sm)

        # Top1/Top2
        if sp >= sm:
            top1_label.append("policy")
            top1_score.append(sp)
            top2_score.append(sm)
            gap_factor.append(compute_gap_factor(sp, sm))
        else:
            top1_label.append("macro")
            top1_score.append(sm)
            top2_score.append(sp)
            gap_factor.append(compute_gap_factor(sm, sp))

    df["score_policy"] = score_policy
    df["score_macro"] = score_macro
    df["top1_label"] = top1_label
    df["top1_score"] = top1_score
    df["top2_score"] = top2_score
    df["gap_factor"] = gap_factor

    # ========== 2) 句子级：硬分配 Top1 + 折扣权重 ==========
    df["weight_policy_raw"] = 0.0
    df["weight_macro_raw"] = 0.0

    wraw = (df["top1_score"].astype(float) * df["gap_factor"].astype(float)).fillna(0.0)
    df.loc[df["top1_label"] == "policy", "weight_policy_raw"] = wraw[df["top1_label"] == "policy"]
    df.loc[df["top1_label"] == "macro", "weight_macro_raw"] = wraw[df["top1_label"] == "macro"]

    # ========== 3) 季度级：Top-N + 自适应阈值 ==========
    coverage_rows: List[Dict] = []
    results: List[Dict] = []

    grouped = df.groupby(["year", "quarter"], sort=True)

    for (y, q), g in grouped:
        g = g.copy()
        n_total = len(g)
        n_target = calc_topn(n_total)

        row = {"year": int(y), "quarter": int(q), "n_sentences": int(n_total), "topn_target": int(n_target)}

        # --- tone_all（不依赖 zero-shot） ---
        tone_all, tone_p90_all, cov_all = build_tone_all_for_group(g, global_med)
        row["tone_all"] = tone_all
        row["tone_p90_all"] = tone_p90_all

        coverage_rows.append({
            "year": int(y), "quarter": int(q), "topic": "all",
            "total_sentences_quarter": int(n_total),
            "n_target": int(min(n_target, cov_all.get("k", 0))),  # 仅做参考
            "n_selected": int(cov_all.get("k_eff", 0)),
            "coverage_selected": float(cov_all.get("k_eff", 0) / n_total) if n_total else 0.0,
            "tau_used": np.nan,
            "avg_weight_selected": np.nan,
            "avg_top_score_selected": np.nan,
            "avg_gap_selected": np.nan,
            "note": f"tone_all: topK={cov_all.get('k',0)} trim={cov_all.get('trim',0)}"
        })

        # --- 两个主题 ---
        for topic in TOPIC_KEYS:
            wcol_raw = f"weight_{topic}_raw"
            # 分阶段放宽 tau，直到 eligible >= TOPN_MIN 或到最小阈值
            tau_used = RELAX_TAUS[-1]
            eligible = g[(g["top1_score"] >= RELAX_TAUS[0]) & (g[wcol_raw] > 0)]
            for tau in RELAX_TAUS:
                eligible = g[(g["top1_score"] >= tau) & (g[wcol_raw] > 0)]
                tau_used = tau
                if len(eligible) >= TOPN_MIN or tau == RELAX_TAUS[-1]:
                    break

            # 取 Top-N（按 weight_raw）
            if n_target > 0 and len(eligible) > 0:
                selected = eligible.nlargest(min(n_target, len(eligible)), columns=[wcol_raw]).copy()
            else:
                selected = eligible.copy()

            # 最终权重列：只保留 selected，其余为 0（pandas 索引对齐）
            wcol_final = f"weight_{topic}"
            g[wcol_final] = 0.0
            if len(selected) > 0:
                g.loc[selected.index, wcol_final] = pd.to_numeric(selected[wcol_raw], errors="coerce").fillna(0.0)

            # tone：加权平均（权重归一化）
            denom = float(g[wcol_final].sum())
            if denom > 0 and not np.isnan(denom):
                p = pd.to_numeric(g["roberta_neg_prob"], errors="coerce").fillna(0.0)
                tone = float((g[wcol_final] * p).sum() / denom)
                tone_p90 = float(np.percentile(g.loc[g[wcol_final] > 0, "roberta_neg_prob"].dropna().values, 90))
            else:
                tone = float("nan")
                tone_p90 = float("nan")

            row[f"tone_{topic}"] = tone
            row[f"tone_p90_{topic}"] = tone_p90

            # coverage row
            # 选中句子的 top1/gap/weight 统计
            if len(selected) > 0:
                avg_w = float(selected[wcol_raw].mean())
                avg_s = float(selected["top1_score"].mean())
                avg_gap = float((selected["top1_score"] - selected["top2_score"]).mean())
            else:
                avg_w = avg_s = avg_gap = 0.0

            coverage_rows.append({
                "year": int(y), "quarter": int(q), "topic": topic,
                "total_sentences_quarter": int(n_total),
                "n_top1": int((g["top1_label"] == topic).sum()),
                "n_conf_ge_0_50": int(((g["top1_label"] == topic) & (g["top1_score"] >= 0.50)).sum()),
                "tau_used": float(tau_used),
                "n_eligible": int(len(eligible)),
                "n_target": int(n_target),
                "n_selected": int(len(selected)),
                "coverage_selected": float(len(selected) / n_total) if n_total else 0.0,
                "avg_weight_selected": float(avg_w),
                "avg_top_score_selected": float(avg_s),
                "avg_gap_selected": float(avg_gap),
            })

        results.append(row)

        # 把最终权重回写到 df（对 bucket 输出很重要）
        df.loc[g.index, "weight_policy"] = g.get("weight_policy", 0.0)
        df.loc[g.index, "weight_macro"] = g.get("weight_macro", 0.0)

    final_df = pd.DataFrame(results).sort_values(["year", "quarter"]).reset_index(drop=True)

    # ========== 4) Z-score（季度层） ==========
    print("[Info] Calculating Z-scores ...")
    tone_cols = [c for c in final_df.columns if c.startswith("tone_")]
    for c in tone_cols:
        mu = float(final_df[c].mean(skipna=True))
        sigma = float(final_df[c].std(skipna=True))
        if sigma == 0.0 or np.isnan(sigma):
            final_df[f"{c}_z"] = 0.0
        else:
            final_df[f"{c}_z"] = (final_df[c] - mu) / sigma

    # ========== 5) 输出 ==========
    # 5.1 季度指标
    out = final_df.round(6)
    out.to_csv(OUT_FILE, index=False, encoding="utf-8-sig")
    print(f"✅ [DONE] Saved quarterly tone series to {OUT_FILE}")

    # 5.2 coverage
    cov_df = pd.DataFrame(coverage_rows).sort_values(["year", "quarter", "topic"]).reset_index(drop=True)
    cov_df = cov_df.round(6)
    cov_df.to_csv(COVERAGE_OUT, index=False, encoding="utf-8-sig")
    print(f"✅ [DONE] Saved coverage report to {COVERAGE_OUT}")

    # 5.3 bucket（句子级）
    bucket_cols = [
        "id", "year", "quarter", "section", "section_title", "sent_id_in_report",
        "text", "roberta_neg_prob",
        "score_policy", "score_macro",
        "top1_label", "top1_score", "top2_score", "gap_factor",
        "weight_policy_raw", "weight_macro_raw",
        "weight_policy", "weight_macro",
    ]
    bucket = df[[c for c in bucket_cols if c in df.columns]].copy()
    bucket = bucket.round(6)
    bucket.to_csv(BUCKET_OUT, index=False, encoding="utf-8-sig")
    print(f"✅ [DONE] Saved sentence-level bucket to {BUCKET_OUT}")

    print("-" * 60)
    print("All done.")
    print("-" * 60)


if __name__ == "__main__":
    main()
