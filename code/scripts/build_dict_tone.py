# build_dict_tone.py
# -*- coding: utf-8 -*-
"""
Step 1: 姜富伟 (2021) 情感单元法 (Excel Version)
核心修复：
1. 直接读取 'ChineseSentimentDictionary.xlsx'。
2. 自动识别 Sheet (Positive/Political -> +1, Negative -> -1) 并合并。
3. 严格执行姜富伟的"动态区间扫描"算法。
4. 修复"增长"等关键词缺失问题。
5. 针对 CPI/通胀话题进行专项逻辑修正（上涨=负面，回落=正面）。
"""

import pandas as pd
import jieba
import sys
from pathlib import Path
from tqdm import tqdm

# ========= 1. 文件配置 =========
# 用户指定的文件名
DICT_FILE = "ChineseSentimentDictionary.xlsx"
SENT_PATH = "all_sentences.csv"
OUT_SENT_PATH = "all_sentences_with_dict_scores.csv"

# ========= 2. 算法参数 =========
# 姜富伟标准：剔除数字占比超过 50% 的句子
DIGIT_THRESHOLD = 0.50 

# 否定词典 (姜富伟逻辑核心)
NEGATION_WORDS = {
    "不", "没", "无", "非", "莫", "弗", "勿", "未", "否", "别", 
    "不是", "不要", "没有", "难以", "未曾", "毫无", "摒弃", "休", "未必",
    "并非", "绝不", "从未", "切忌", "严禁"
}

# 否定作用窗口：只在情感词前若干个分词内寻找否定词，避免远距离误伤
NEG_WINDOW = 6

# 语气缓和/边际改善修饰词：修正“衰退放缓 / 降幅收窄 / 压力缓解”等被词袋法误判的问题
# 这些词往往表示“坏消息在减弱/改善”，应当削弱负向强度（而不是简单翻正）。
IMPROVE_MODIFIERS = {
    "放缓", "趋缓", "缓解", "减轻", "收窄", "缩小", "企稳", "趋稳", "稳定", "温和",
    "改善", "好转", "回升", "回稳", "修复", "回暖",
}

# 坏语境触发词 (如 CPI/通胀/价格...)：用于“上涨”在该语境下转为坏消息的修正
BAD_CONTEXT_WORDS = {"CPI", "PPI", "物价", "通胀", "价格", "赤字", "不良", "坏账", "杠杆", "风险", "泡沫"}

# 通用“量增/上行”词：在 CPI/通胀语境中往往是坏消息
VOLUME_UP_WORDS = {"上涨", "上升", "增加", "增高", "攀升", "走高", "上行", "抬升", "反弹", "回升", "新高", "扩大"}

# CPI/通胀话题采用“目标导向”而不是“通用正负面”：
#  - 价格上行（上涨/攀升/反弹）通常是坏消息
#  - 价格回落/温和/稳定通常是好消息
CPI_TOPIC_WORDS = {"CPI", "PPI", "通胀", "物价", "价格", "居民消费价格", "生产者价格", "工业品出厂价格"}
CPI_BAD_WORDS = {"上涨", "上升", "攀升", "走高", "抬升", "反弹", "回升", "上行", "新高", "高位", "严重"}
CPI_GOOD_WORDS = {"回落", "下降", "下行", "走低", "降低", "温和", "稳定", "企稳", "趋稳", "缓解", "趋缓", "收窄"}

# 负向词碰到“边际改善修饰词”时，削弱强度（而不是直接翻正），更稳健。
NEG_IMPROVE_ATTENUATION = 0.5

def load_excel_dictionary():
    """
    直接读取 Excel 并合并所有 Sheet
    """
    print(f"[Dict] Reading {DICT_FILE} ...")
    if not Path(DICT_FILE).exists():
        print(f"❌ Error: {DICT_FILE} not found!")
        sys.exit(1)

    word_dict = {} 
    
    try:
        # 读取所有 Sheet
        xls = pd.read_excel(DICT_FILE, sheet_name=None)
        
        for sheet_name, df in xls.items():
            if df.empty: continue
            
            # 尝试获取第一列数据 (无论列名是什么)
            words = df.iloc[:, 0].dropna().astype(str).str.strip()
            
            # 判定 Sheet 类型
            lower_name = sheet_name.lower()
            
            weight = 0
            label = "Unknown"
            
            if "pos" in lower_name or "正面" in lower_name:
                weight = 1
                label = "Positive"
            elif "pol" in lower_name or "政治" in lower_name:
                weight = 1 # 政治词视为正面
                label = "Political"
            elif "neg" in lower_name or "负面" in lower_name:
                weight = -1
                label = "Negative"
            else:
                print(f"  ⚠️ Skipping unknown sheet: {sheet_name}")
                continue
                
            count = 0
            for w in words:
                # 简单清洗：跳过太短的或者是表头
                if len(w) > 0 and w.lower() != 'word': 
                    word_dict[w] = weight
                    count += 1
            
            print(f"  - Sheet '{sheet_name}' -> Merged as {label} ({count} words)")
            
    except Exception as e:
        print(f"❌ Error reading Excel: {e}")
        sys.exit(1)

    # === 手动补全缺失的关键金融词汇 ===
    # 针对用户反馈的 "增长: Not Found" 问题
    critical_positives = ["增长", "回升", "好转", "改善", "复苏", "繁荣", "稳健", "优化", "合理"]
    critical_negatives = ["衰退", "下滑", "萎缩", "低迷", "恶化", "疲软", "短缺", "不足", "困难"]
    
    print("\n[Dict Supplement]")
    for w in critical_positives:
        if w not in word_dict:
            word_dict[w] = 1
            print(f"  + Added missing positive: {w}")
            
    for w in critical_negatives:
        if w not in word_dict:
            word_dict[w] = -1
            print(f"  + Added missing negative: {w}")

    print(f"  => Total unique sentiment words loaded: {len(word_dict)}")
    
    # === 自检 ===
    print("[Self-Check]")
    for w in ["上涨", "风险", "增长", "物价"]:
        status = f"✅ Score {word_dict.get(w)}" if w in word_dict else "❌ Not Found"
        print(f"  - '{w}': {status}")
        
    return word_dict

def calculate_jiang_tone_strict(text, word_dict):
    """
    姜富伟情感单元法 (完美复现版)
    """
    if not isinstance(text, str): 
        return pd.Series({"dict_tone": 0, "is_valid_unit": 0})
    
    # 1. 预清洗
    digit_count = sum(c.isdigit() for c in text)
    if len(text) > 0 and (digit_count / len(text) > DIGIT_THRESHOLD):
        return pd.Series({"dict_tone": 0, "is_valid_unit": 0})
    
    # 2. 分词
    words = jieba.lcut(text)
    if len(words) == 0: 
        return pd.Series({"dict_tone": 0, "is_valid_unit": 0})

    # 主题识别：CPI/通胀话题采用“目标导向”方向（价格上行偏负、回落/稳定偏正）
    is_cpi_topic = any(w in CPI_TOPIC_WORDS for w in words)
    
    # 3. 锚点定位
    sentiment_hits = []
    for i, w in enumerate(words):
        if w in word_dict:
            sentiment_hits.append((i, w, word_dict[w]))
            
    if not sentiment_hits:
        return pd.Series({"dict_tone": 0, "is_valid_unit": 1}) 
    
    total_score = 0
    prev_idx = -1 
    
    # 4. 核心循环：动态区间扫描
    for curr_idx, word, raw_weight in sentiment_hits:
        
        current_weight = raw_weight

        # --- 逻辑 A1: CPI/通胀话题“目标导向”修正 ---
        # 关键：在 CPI 话题内，“上涨/攀升/反弹...”应视为负面，“回落/稳定/温和...”应视为正面。
        if is_cpi_topic:
            if word in CPI_BAD_WORDS:
                current_weight = -1 # 强制转负 (CPI上涨)
            elif word in CPI_GOOD_WORDS:
                current_weight = 1  # 强制转正 (CPI回落)

        # --- 逻辑 A2: 语境修正（非 CPI 话题也可触发）：坏语境 + 上行词 => 更偏负 ---
        # 例如“通胀压力反弹/物价上涨”
        # 只有当 current_weight 还是 1 时才检查，避免已经转负的被重复处理
        if current_weight == 1 and word in VOLUME_UP_WORDS:
            start_check = max(0, curr_idx - 5)
            context_window = words[start_check:curr_idx]
            # 检查是否有坏词 (Substring match for robustness)
            has_bad_context = False
            for w in context_window:
                for bad in BAD_CONTEXT_WORDS:
                    if bad in w:
                        has_bad_context = True
                        break
                if has_bad_context: break
            
            if has_bad_context:
                current_weight = -1

        # --- 逻辑 A3: 边际改善修饰词削弱负向强度 ---
        # 例如“衰退放缓/下滑收窄/压力缓解/降幅收窄”
        if current_weight < 0:
            right_window = words[curr_idx + 1: min(len(words), curr_idx + 1 + 3)]
            left_window = words[max(0, curr_idx - 3): curr_idx]
            has_improvement = False
            for w in right_window + left_window:
                if w in IMPROVE_MODIFIERS:
                    has_improvement = True
                    break
            
            if has_improvement:
                current_weight = current_weight * NEG_IMPROVE_ATTENUATION

        # --- 逻辑 B: 否定词翻转（缩小作用范围，避免远距离误伤） ---
        # 姜富伟原始是“上一个情感词到当前情感词之间扫描”。这里保留思想但只取最近 NEG_WINDOW 个词。
        seg_start = max(prev_idx + 1, curr_idx - NEG_WINDOW)
        scan_segment = words[seg_start:curr_idx]
        neg_count = sum(1 for w in scan_segment if w in NEGATION_WORDS)
        
        # 极性翻转公式: Weight * (-1)^n
        final_weight = current_weight * ((-1) ** neg_count)
        
        total_score += final_weight
        prev_idx = curr_idx
        
    # 5. 归一化
    tone = total_score / len(words)
    
    return pd.Series({
        "dict_tone": tone,
        "is_valid_unit": 1
    })

def main():
    print("==================================================")
    print("   Running Jiang Fuwei Method (Excel Direct Read)")
    print("==================================================")
    
    # 1. 读取 Excel 词典
    word_dict = load_excel_dictionary()
    
    # 2. 读取句子
    print(f"\n[Data] Reading {SENT_PATH} ...")
    try:
        df = pd.read_csv(SENT_PATH)
        df["text"] = df["text"].astype(str)
    except FileNotFoundError:
        print(f"❌ Error: {SENT_PATH} not found.")
        sys.exit(1)
        
    # 3. 计算打分
    print(f"[Calc] Scoring {len(df)} sentences...")
    tqdm.pandas()
    scores = df["text"].progress_apply(lambda x: calculate_jiang_tone_strict(x, word_dict))
    
    df = pd.concat([df, scores], axis=1)
    
    # 4. 输出
    df_valid = df[df["is_valid_unit"] == 1].copy()
    
    print(f"\n[Result]")
    print(f"  - Valid units retained: {len(df_valid)}")
    
    # 检查非零分
    non_zero = (df_valid["dict_tone"] != 0).sum()
    print(f"  - Non-zero score sentences: {non_zero}")
    
    if non_zero == 0:
        print("⚠️ WARNING: All scores are 0! Dictionary matching failed.")
    else:
        print("✅ Success: Scores generated.")

    df_valid.to_csv(OUT_SENT_PATH, index=False, encoding="utf-8-sig")
    print(f"Saved to: {OUT_SENT_PATH}")

if __name__ == "__main__":
    main()