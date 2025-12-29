# -*- coding: utf-8 -*-
"""
build_variance_indicators.py

功能：
  在已有 tone_by_quarter_roberta.csv 的基础上，新增三列：
    1) similarity_prev : 与上一期报告的 TF-IDF 余弦相似度（[0,1]，越大越“相似”）
    2) surprise_prev   : 1 - similarity_prev         （越大越“惊吓”）
    3) avg_sent_len    : 平均句长 = 总字数 / 句子数   （可读性指标，越大越难读）

依赖：
  pip install jieba scikit-learn

假定已有文件：
  - all_sentences_with_roberta_score.csv
        至少包含: year, quarter, text
  - tone_by_quarter_roberta.csv
        至少包含: year, quarter, (tone_all_z / tone_real_z / tone_guid_z 等)
"""

import os
import numpy as np
import pandas as pd
import jieba
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


# ===== 路径配置，根据需要自行修改 =====
SENT_FILE = "all_sentences_with_roberta_score.csv"
TONE_FILE = "tone_by_quarter_roberta.csv"   # 读入 & 覆盖保存
# ====================================


def load_sentence_data(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到句子级文件: {path}")

    df = pd.read_csv(path)
    needed = {"year", "quarter", "text"}
    missing = needed - set(df.columns)
    if missing:
        raise ValueError(f"{path} 缺少必要列 {missing}，当前列为: {list(df.columns)}")

    # 统一类型
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["quarter"] = pd.to_numeric(df["quarter"], errors="coerce").astype("Int64")
    df["text"] = df["text"].astype(str).fillna("")

    return df


def build_doc_level_text(df_sent: pd.DataFrame) -> pd.DataFrame:
    """
    按 (year, quarter) 聚合成整篇报告文本：
      - full_text      : 原始句子拼接
      - avg_sent_len   : 平均句长 (总字数 / 句子数)
    """
    # 每句的字数（中文直接用 len，效果已经足够好）
    df_sent["char_len"] = df_sent["text"].apply(lambda s: len(str(s).replace(" ", "")))

    grp_cols = ["year", "quarter"]

    # 聚合：文本列表 + 总字数 + 句子数
    agg = df_sent.groupby(grp_cols).agg(
        text_list=("text", list),
        total_chars=("char_len", "sum"),
        n_sents=("text", "size"),
    ).reset_index()

    # 平均句长：总字数 / 句子数
    agg["avg_sent_len"] = agg["total_chars"] / agg["n_sents"].replace(0, np.nan)

    # 整篇文本（用于 TF-IDF；句子之间用空格/句号连接均可）
    agg["full_text"] = agg["text_list"].apply(lambda lst: "。".join(lst))

    return agg


def tokenize_with_jieba(text: str) -> str:
    """
    用 jieba 分词后，用空格拼接成字符串。
    TfidfVectorizer 会把空格作为词的分隔符。
    """
    tokens = jieba.lcut(text)
    # 去掉特别短的 token
    tokens = [t.strip() for t in tokens if t.strip()]
    return " ".join(tokens)


def compute_similarity_series(docs: pd.Series) -> pd.Series:
    """
    输入：按时间排好序的 文本 Series (每个元素是一篇报告的全文)
    输出：与上一期报告的 TF-IDF 余弦相似度，第一期为 NaN
    """
    # 1) 先分词
    tokenized_docs = docs.apply(tokenize_with_jieba)

    # 2) 用“已分词”的文本构建 TF-IDF 向量
    vectorizer = TfidfVectorizer(
        tokenizer=lambda s: s.split(),  # 我们已经用空格分词
        preprocessor=lambda s: s,       # 不再做额外预处理
        token_pattern=None              # 关闭默认正则，否则会忽略中文
    )
    tfidf_mat = vectorizer.fit_transform(tokenized_docs)

    n = tfidf_mat.shape[0]
    sims = [np.nan] * n

    for i in range(1, n):
        # 与上一期报告的余弦相似度
        sim = cosine_similarity(tfidf_mat[i - 1], tfidf_mat[i])[0, 0]
        sims[i] = float(sim)

    return pd.Series(sims, index=docs.index, name="similarity_prev")


def main():
    # 1. 读入句子级数据，构建整篇报告文本 & 平均句长
    df_sent = load_sentence_data(SENT_FILE)
    doc_df = build_doc_level_text(df_sent)

    # 2. 按时间排序（year, quarter），计算与上一期的 TF-IDF 相似度
    doc_df = doc_df.sort_values(["year", "quarter"]).reset_index(drop=True)
    doc_df["similarity_prev"] = compute_similarity_series(doc_df["full_text"])

    # 3. 惊吓度 = 1 - similarity
    doc_df["surprise_prev"] = 1.0 - doc_df["similarity_prev"]

    # 4. 只保留需要的列，并与已有的 tone_by_quarter_roberta.csv 合并
    var_cols = ["year", "quarter", "similarity_prev", "surprise_prev", "avg_sent_len"]
    var_df = doc_df[var_cols].copy()

    # 5. 读入 tone_by_quarter_roberta.csv，合并后覆盖保存
    if not os.path.exists(TONE_FILE):
        raise FileNotFoundError(f"找不到 {TONE_FILE}，请先运行构建 tone 的脚本。")

    tone = pd.read_csv(TONE_FILE)
    # 兼容 Year/Quarter 大写
    if "Year" in tone.columns:
        tone = tone.rename(columns={"Year": "year"})
    if "Quarter" in tone.columns:
        tone = tone.rename(columns={"Quarter": "quarter"})

    tone["year"] = pd.to_numeric(tone["year"], errors="coerce").astype("Int64")
    tone["quarter"] = pd.to_numeric(tone["quarter"], errors="coerce").astype("Int64")

    merged = tone.merge(var_df, on=["year", "quarter"], how="left")

    # 6. 保存（直接覆盖原文件；如需备份，可先复制一份）
    merged.to_csv(TONE_FILE, index=False, encoding="utf-8-sig")

    print("[OK] 已在 tone_by_quarter_roberta.csv 中新增列：")
    print("     similarity_prev : 与上一期报告的 TF-IDF 余弦相似度")
    print("     surprise_prev   : 1 - similarity_prev")
    print("     avg_sent_len    : 平均句长（可读性指标）")
    print()
    print(merged.head())


if __name__ == "__main__":
    main()
