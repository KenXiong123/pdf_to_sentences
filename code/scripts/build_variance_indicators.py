# -*- coding: utf-8 -*-
"""
build_variance_indicators.py  (Jiang-style aligned, overwrite-safe)

输出/覆盖写入 tone_by_quarter_roberta.csv 的列：
  - similarity_prev        : 本期 vs 上期 TF-IDF cosine similarity（越大越像）
  - surprise_prev          : 1 - similarity_prev（越大越意外）
  - avg_sent_len           : 总字数 / 句子数（按句末标点计句，更贴近姜富伟）
  - avg_sent_len_rows      : 总字数 / 句子行数（备份口径）
  - prev_quarter_available : 1=存在“上一自然季度”，0=缺失上一季度（断档/首期）

关键对齐姜富伟：
  - jieba 分词 + stopwords 去除
  - idf = ln(N/df)（无平滑）
  - tf = count / sum(count)
  - 归一化后点积 = cosine similarity

输入：
  - all_sentences_with_roberta_score.csv（至少 year, quarter, text）
  - tone_by_quarter_roberta.csv（至少 year, quarter）
"""

from __future__ import annotations
import re
import numpy as np
import pandas as pd
import jieba
from pathlib import Path
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.preprocessing import normalize


SENT_FILE = "all_sentences_with_roberta_score.csv"
TONE_FILE = "tone_by_quarter_roberta.csv"

STOPWORDS_FILE_CANDIDATES = [
    "cn_stopwords.txt",
    "stopwords_zh.txt",
    "stopwords.txt",
    "data/stopwords_zh.txt",
    "data/stopwords.txt",
]

# 关键新增：是否强制季度连续性（断档处 sim/surprise 置 NaN）
STRICT_QUARTER_CONTINUITY = True

_punct_re = re.compile(r"^[\W_]+$", flags=re.UNICODE)
_digit_re = re.compile(r"^\d+(\.\d+)?$")


def _resolve(path: str) -> Path:
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


def load_stopwords() -> set[str]:
    for cand in STOPWORDS_FILE_CANDIDATES:
        try:
            p = _resolve(cand)
            sw = set()
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    w = line.strip()
                    if w:
                        sw.add(w)
            print(f"[INFO] Loaded stopwords: {len(sw)} from {p}")
            return sw
        except FileNotFoundError:
            continue

    minimal = {
        "的", "了", "和", "及", "与", "在", "对", "为", "以", "于", "是", "将", "并", "等",
        "我们", "我国", "本期", "上期", "本", "该", "其", "这", "那", "而", "或", "及其",
        "以及", "其中", "有关", "进一步", "继续", "持续", "不断", "加强", "推进", "提高",
        "。", "，", "、", "；", "：", "！", "？", ".", ",", ";", ":", "!", "?", "（", "）", "(", ")",
    }
    print(f"[WARN] Stopwords file not found. Using minimal built-in stopwords only: {len(minimal)}")
    return minimal


def load_sentence_data(path: str) -> pd.DataFrame:
    p = _resolve(path)
    df = pd.read_csv(p)

    needed = {"year", "quarter", "text"}
    miss = needed - set(df.columns)
    if miss:
        raise ValueError(f"{p} 缺少必要列 {miss}，当前列: {list(df.columns)}")

    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["quarter"] = pd.to_numeric(df["quarter"], errors="coerce").astype("Int64")
    df["text"] = df["text"].astype(str).fillna("")
    df = df.dropna(subset=["year", "quarter"]).copy()
    return df


def build_doc_level_text(df_sent: pd.DataFrame) -> pd.DataFrame:
    df = df_sent.copy()
    df["char_len"] = df["text"].apply(lambda s: len(str(s).replace(" ", "")))

    agg = df.groupby(["year", "quarter"]).agg(
        text_list=("text", list),
        total_chars=("char_len", "sum"),
        n_sents_rows=("text", "size"),
    ).reset_index()

    agg["full_text"] = agg["text_list"].apply(lambda lst: "。".join(lst))
    agg["avg_sent_len_rows"] = agg["total_chars"] / agg["n_sents_rows"].replace(0, np.nan)

    def count_sents_by_punct(text: str) -> int:
        if not isinstance(text, str) or not text:
            return 0
        return len(re.findall(r"[。！？.!?]", text))

    agg["n_sents_punct"] = agg["full_text"].apply(count_sents_by_punct)
    agg["n_sents_punct"] = np.where(
        agg["n_sents_punct"] > 0, agg["n_sents_punct"], agg["n_sents_rows"]
    )
    agg["avg_sent_len"] = agg["total_chars"] / pd.Series(agg["n_sents_punct"]).replace(0, np.nan)

    return agg


def tokenize_with_jieba(text: str, stopwords: set[str]) -> str:
    tokens = jieba.lcut(text)
    out = []
    for t in tokens:
        t = t.strip()
        if not t:
            continue
        if t in stopwords:
            continue
        if _digit_re.match(t):
            continue
        if _punct_re.match(t):
            continue
        out.append(t)
    return " ".join(out)


def compute_similarity_prev(docs: pd.Series, stopwords: set[str]) -> pd.Series:
    tokenized = docs.fillna("").astype(str).apply(lambda s: tokenize_with_jieba(s, stopwords))

    cv = CountVectorizer(
        tokenizer=lambda s: s.split(),
        preprocessor=lambda s: s,
        token_pattern=None
    )
    X = cv.fit_transform(tokenized)
    N = X.shape[0]
    if N <= 1:
        return pd.Series([np.nan] * N, index=docs.index, name="similarity_prev")

    # TF
    row_sum = np.asarray(X.sum(axis=1)).ravel()
    row_sum[row_sum == 0] = 1.0
    TF = X.multiply(1.0 / row_sum[:, None])

    # DF
    DF = np.asarray((X > 0).sum(axis=0)).ravel()
    DF[DF == 0] = 1

    # IDF = ln(N/DF) (no smoothing)
    IDF = np.log(N / DF)

    TFIDF = TF.multiply(IDF)
    TFIDF = normalize(TFIDF, norm="l2", axis=1, copy=False)

    sims = [np.nan] * N
    for i in range(1, N):
        sims[i] = float(TFIDF[i - 1].multiply(TFIDF[i]).sum())

    s = pd.Series(sims, index=docs.index, name="similarity_prev")

    # 数值稳健：极小概率出现 -1e-12 / 1+1e-12，clip 到 [0,1]
    s = s.clip(lower=0.0, upper=1.0)
    return s


def quarter_continuity_flags(df_quarter: pd.DataFrame) -> pd.DataFrame:
    """
    返回包含 prev_quarter_available 的 df：
      prev_quarter_available=1 表示存在上一自然季度（year*4+quarter 连续差=1）
      prev_quarter_available=0 表示首期或季度断档
    """
    out = df_quarter.sort_values(["year", "quarter"]).reset_index(drop=True).copy()
    out["q_idx"] = out["year"].astype(int) * 4 + out["quarter"].astype(int)
    out["prev_quarter_available"] = (out["q_idx"].diff() == 1).astype(int)
    out.loc[0, "prev_quarter_available"] = 0  # 第一条必然没有上一期
    return out


def main():
    stopwords = load_stopwords()

    df_sent = load_sentence_data(SENT_FILE)
    doc_df = build_doc_level_text(df_sent).sort_values(["year", "quarter"]).reset_index(drop=True)

    # ===== 新增：季度连续性检查 =====
    doc_df = quarter_continuity_flags(doc_df)

    gap_rows = doc_df[(doc_df["prev_quarter_available"] == 0)].copy()
    # 第一行是“首期”不是断档；断档从第二个 prev=0 开始才值得提示
    real_gaps = gap_rows.iloc[1:] if len(gap_rows) > 1 else gap_rows.iloc[0:0]

    if len(real_gaps) > 0:
        print("[WARN] Quarter gaps detected (missing previous natural quarter).")
        print(real_gaps[["year", "quarter"]].to_string(index=False))
        print("[WARN] For these quarters, similarity_prev/surprise_prev will be set to NaN "
              "to avoid comparing with a non-adjacent quarter.")
    else:
        print("[INFO] No quarter gaps detected (quarter series is continuous).")

    # ===== 相似度（按数据顺序先算出来）=====
    doc_df["similarity_prev"] = compute_similarity_prev(doc_df["full_text"], stopwords)
    doc_df["surprise_prev"] = 1.0 - doc_df["similarity_prev"]

    # ===== 断档处修正：置 NaN（严格口径）=====
    if STRICT_QUARTER_CONTINUITY:
        mask_gap = (doc_df["prev_quarter_available"] == 0)
        mask_gap.iloc[0] = False  # 首期本来就是 NaN，不需要再强调
        if mask_gap.any():
            doc_df.loc[mask_gap, "similarity_prev"] = np.nan
            doc_df.loc[mask_gap, "surprise_prev"] = np.nan

    # 准备要写回 tone 的变量表
    var_df = doc_df[[
        "year", "quarter",
        "similarity_prev", "surprise_prev",
        "avg_sent_len", "avg_sent_len_rows",
        "prev_quarter_available"
    ]].copy()

    # 读 tone 文件
    tone_path = _resolve(TONE_FILE)
    tone = pd.read_csv(tone_path)

    if "Year" in tone.columns and "year" not in tone.columns:
        tone = tone.rename(columns={"Year": "year"})
    if "Quarter" in tone.columns and "quarter" not in tone.columns:
        tone = tone.rename(columns={"Quarter": "quarter"})

    tone["year"] = pd.to_numeric(tone["year"], errors="coerce").astype("Int64")
    tone["quarter"] = pd.to_numeric(tone["quarter"], errors="coerce").astype("Int64")

    # ===== overwrite-safe：用 index 对齐覆盖写入，避免 merge 产生 _x/_y =====
    tone = tone.set_index(["year", "quarter"])
    var_df = var_df.set_index(["year", "quarter"])

    for col in ["similarity_prev", "surprise_prev", "avg_sent_len", "avg_sent_len_rows", "prev_quarter_available"]:
        tone[col] = var_df[col]

    out = tone.reset_index()
    out.to_csv(tone_path, index=False, encoding="utf-8-sig")

    # 诊断输出
    s = out["similarity_prev"].dropna()
    u = out["surprise_prev"].dropna()

    print("[OK] Updated tone_by_quarter_roberta.csv (overwrite-safe).")
    if len(s) > 0:
        print("[DIAG] similarity_prev quantiles:")
        print(s.quantile([0, 0.1, 0.25, 0.5, 0.75, 0.9, 1]).to_string())
        oob = ((s < 0) | (s > 1)).sum()
        print(f"[DIAG] similarity_prev out of [0,1] count: {int(oob)}")
    if len(u) > 0:
        print("\n[DIAG] surprise_prev quantiles:")
        print(u.quantile([0, 0.1, 0.25, 0.5, 0.75, 0.9, 1]).to_string())

    print("\n[DIAG] head:")
    print(out[["year","quarter","prev_quarter_available","similarity_prev","surprise_prev","avg_sent_len","avg_sent_len_rows"]]
          .head(12).to_string(index=False))


if __name__ == "__main__":
    main()
