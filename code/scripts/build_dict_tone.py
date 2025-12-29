# -*- coding: utf-8 -*-
"""
build_dict_tone.py (Final Version)

策略：回归单词典 (Du/L&M) 以保证央行语境的纯净度，但保留“反转短语”逻辑以修正语义。

处理逻辑：
1. 加载 Du 情感词典。
2. 预处理：检测“降幅收窄”等反转短语，给予正向加分。
3. 分词 & 匹配：计算 Pos/Neg 词数。
4. 否定逻辑：处理“不/非/无”。
5. 输出：Neg_net (供 RoBERTa 训练的弱标签) 和 is_numeric (供过滤)。
"""

import pandas as pd
import jieba
import re
from typing import Set

# ========= 0. 基础路径配置 =========
DICT_PATH = "ChineseSentimentDictionary.xlsx"      # 仅使用 Du 词典
SENT_PATH = "all_sentences.csv"
OUT_SENT_PATH = "all_sentences_with_dict_scores.csv"
OUT_TONE_Q_PATH = "tone_by_quarter_dict.csv"

TEXT_COL = "text"
YEAR_COL = "year"
QUARTER_COL = "quarter"

# ========= 1. 读取 Du 词典 =========

def load_words_from_sheet(xls: pd.ExcelFile, sheet_name: str) -> Set[str]:
    # 容错读取 sheet
    real_sheet_name = sheet_name
    if sheet_name not in xls.sheet_names:
        for s in xls.sheet_names:
            if s.lower() == sheet_name.lower():
                real_sheet_name = s
                break
    
    if real_sheet_name not in xls.sheet_names:
        print(f"[ERROR] Sheet '{sheet_name}' not found!")
        return set()

    df = pd.read_excel(xls, sheet_name=real_sheet_name)
    col = df.columns[0]
    words = df[col].dropna().astype(str).str.strip().tolist()
    return set(words)

print("[INFO] Loading Du sentiment dictionary from:", DICT_PATH)
try:
    xls_du = pd.ExcelFile(DICT_PATH)
    POS_DU = load_words_from_sheet(xls_du, "Positive")
    NEG_DU = load_words_from_sheet(xls_du, "Negative")
    print(f"[INFO] Positive words: {len(POS_DU)}")
    print(f"[INFO] Negative words: {len(NEG_DU)}")
except Exception as e:
    print(f"[ERROR] Loading Dictionary Failed: {e}")
    POS_DU, NEG_DU = set(), set()

# 否定词
NEGATION_WORDS = set(["不", "非", "没", "沒有", "无", "未", "莫", "勿", "难以", "并未", "不再", "无法", "未能"])

# 停用词
STOP_WORDS = set(["的", "了", "在", "是", "和", "与", "对", "等", "及", "之", "其", "于", "但", "则", "所", "，", "。", "、", "：", "；", "！", "？", "（", "）", "“", "”", "%"])

# 【保留精华】反转短语 (Reversal Phrases)
# 这些词虽然含负面字，但在央行报告中通常是好事，给予加分
REVERSAL_PHRASES = [
    "降幅收窄", "降幅缩小", "跌幅收窄", "止跌回升", 
    "由负转正", "低位回升", "触底反弹", "增速回升",
    "负增长收窄", "亏损减少", "降幅明显收窄"
]

# ========= 2. 句子打分核心函数 =========

def score_sentence_optimized(text: str) -> pd.Series:
    text_str = str(text).strip()
    if not text_str:
        return pd.Series({"Pos":0, "Neg":0, "Neg_net":0, "is_numeric":0})

    # 1. 反转短语检测 (Bonus)
    reversal_bonus = 0
    for phrase in REVERSAL_PHRASES:
        if phrase in text_str:
            reversal_bonus += 1.0 # 视为正向信号

    # 2. 分词
    tokens = list(jieba.cut(text_str))
    if not tokens:
        return pd.Series({"Pos":0, "Neg":0, "Neg_net":0, "is_numeric":0})

    pos_cnt = 0 + reversal_bonus
    neg_cnt = 0
    valid_tokens_count = 0

    for idx, w in enumerate(tokens):
        w = w.strip()
        if not w: continue
        if w in STOP_WORDS: continue

        valid_tokens_count += 1

        # 否定检查
        is_negated = False
        if idx > 0:
            prev = tokens[idx - 1].strip()
            if prev in NEGATION_WORDS:
                is_negated = True
        
        # Du 词典匹配
        if w in POS_DU:
            if is_negated: neg_cnt += 1
            else:          pos_cnt += 1
        elif w in NEG_DU:
            if is_negated: pos_cnt += 1
            else:          neg_cnt += 1

    # 3. 计算分数
    total = max(valid_tokens_count, 1)
    pos_pct = pos_cnt / total
    neg_pct = neg_cnt / total
    neg_net = neg_pct - pos_pct # 越大越负面

    # 4. 数字句标记
    digit_count = sum(c.isdigit() for c in text_str)
    is_numeric = 1 if (len(text_str) > 0 and digit_count / len(text_str) > 0.15) else 0

    return pd.Series({
        "Pos": pos_pct,
        "Neg": neg_pct,
        "Neg_net": neg_net,
        "is_numeric": is_numeric
    })

# ========= 3. 主流程 =========

def main():
    print(f"[INFO] Processing {SENT_PATH} ...")
    df_sent = pd.read_csv(SENT_PATH)
    
    # 清洗
    df_sent[TEXT_COL] = df_sent[TEXT_COL].astype(str).str.strip()
    df_sent = df_sent[df_sent[TEXT_COL] != ""].reset_index(drop=True)

    print("[INFO] Scoring sentences (Du Dictionary + Logic Fixes)...")
    scores = df_sent[TEXT_COL].apply(score_sentence_optimized)
    
    df_all = pd.concat([df_sent, scores], axis=1)
    
    # 保存结果 (供 RoBERTa 使用)
    df_all.to_csv(OUT_SENT_PATH, index=False, encoding="utf-8-sig")
    print(f"[OK] Saved sentence scores: {OUT_SENT_PATH}")

    # 自检
    print("\n>>> Check Positive Samples (Lowest Neg_net):")
    print(df_all.sort_values("Neg_net").head(3)[TEXT_COL].values)
    
    print("\n>>> Check Negative Samples (Highest Neg_net):")
    print(df_all.sort_values("Neg_net", ascending=False).head(3)[TEXT_COL].values)

    # 聚合季度数据
    if YEAR_COL in df_all.columns and QUARTER_COL in df_all.columns:
        df_q = df_all.groupby([YEAR_COL, QUARTER_COL], as_index=False)[["Pos", "Neg", "Neg_net"]].mean()
        df_q.to_csv(OUT_TONE_Q_PATH, index=False, encoding="utf-8-sig")
        print(f"[OK] Saved quarterly tone: {OUT_TONE_Q_PATH}")

if __name__ == "__main__":
    main()