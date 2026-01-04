# roberta_pipeline.py
# -*- coding: utf-8 -*-
"""
Step 2 (M1 Max Optimized): 深度学习情感分析 (MacBERT Large)
硬件优化：
1. [Tokenization] 开启 num_proc=8 多核并行。
2. [Training] 开启 dataloader_num_workers=4 实现 CPU/GPU 流水线。
3. [MPS] 强制使用 Metal Performance Shaders 加速。
"""

import argparse
import pandas as pd
import numpy as np
from tqdm import tqdm
import torch
from datasets import Dataset
from sklearn.metrics import accuracy_score, f1_score
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    Trainer,
    TrainingArguments,
    DataCollatorWithPadding
)
import os
import sys

# ================== 配置区域 ==================
MODEL_NAME = "hfl/chinese-macbert-large"

# 文件路径
ALL_SENTENCES_WITH_DICT = "all_sentences_with_dict_scores.csv"
ALL_SENTENCES_RAW = "all_sentences.csv"
TRAIN_CSV = "macbert_train_clean.csv"
MODEL_DIR = "macbert_pbc_sentiment_v2"
SCORED_CSV = "all_sentences_with_roberta_score.csv"

# M1 Max 专属超参
MAX_LEN = 128
# M1 Max 统一内存很大(32G/64G)，Batch 可以给大一点，如果崩了就改回 16
BATCH_SIZE = 32          
GRAD_ACCUMULATION = 2    # 等效 Batch = 64
LEARNING_RATE = 2e-5
EPOCHS = 3
CONFIDENCE_MARGIN = 0.0 

# 并行设置
NUM_PROC = 8             # Tokenize 时的 CPU 核心数
NUM_WORKERS = 4          # DataLoader 的子进程数
# ============================================

def get_device():
    if torch.backends.mps.is_available():
        return "mps"
    return "cuda" if torch.cuda.is_available() else "cpu"

def prepare_training_data():
    print(f"[Step 2-A] 准备训练数据...")
    if not os.path.exists(ALL_SENTENCES_WITH_DICT):
        print(f"❌ 错误：找不到文件 {ALL_SENTENCES_WITH_DICT}")
        sys.exit(1)

    df = pd.read_csv(ALL_SENTENCES_WITH_DICT)
    
    # 过滤与清洗
    if 'is_valid_unit' in df.columns:
        clean_df = df[df['is_valid_unit'] == 1].copy()
    else:
        clean_df = df[df['is_numeric'] == 0].copy()
            
    clean_df = clean_df[clean_df['text'].str.len() > 4]
    high_conf_df = clean_df[abs(clean_df['dict_tone']) > CONFIDENCE_MARGIN].copy()
    
    # 标签生成
    high_conf_df['label'] = high_conf_df['dict_tone'].apply(lambda x: 0 if x > 0 else 1)
    
    # 均衡采样
    pos_df = high_conf_df[high_conf_df['label'] == 0]
    neg_df = high_conf_df[high_conf_df['label'] == 1]
    
    min_len = min(len(pos_df), len(neg_df))
    if min_len < 10:
        print("❌ Error: 样本太少。")
        sys.exit(1)

    print(f"   - 均衡采样: 各 {min_len} 条")
    balanced_df = pd.concat([
        pos_df.sample(n=min_len, random_state=42),
        neg_df.sample(n=min_len, random_state=42)
    ]).sample(frac=1, random_state=42)
    
    balanced_df.to_csv(TRAIN_CSV, index=False, encoding="utf-8-sig")
    print(f"[OK] 训练集准备完毕。")

def compute_metrics(pred):
    labels = pred.label_ids
    preds = pred.predictions.argmax(-1)
    acc = accuracy_score(labels, preds)
    f1 = f1_score(labels, preds, average="binary")
    return {"accuracy": acc, "f1": f1}

def train_model():
    print(f"[Step 2-B] 开始微调 (M1 Max Mode)...")
    if not os.path.exists(TRAIN_CSV):
        prepare_training_data()
        
    df = pd.read_csv(TRAIN_CSV)
    train_size = int(0.9 * len(df))
    train_df = df.iloc[:train_size]
    eval_df = df.iloc[train_size:]
    
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    
    def tokenize_func(examples):
        return tokenizer(examples["text"], padding="max_length", truncation=True, max_length=MAX_LEN)
    
    # 🔥 优化1: 多核并行 Tokenize
    print(f"   - Tokenizing with {NUM_PROC} cores...")
    train_ds = Dataset.from_pandas(train_df).map(tokenize_func, batched=True, num_proc=NUM_PROC)
    eval_ds = Dataset.from_pandas(eval_df).map(tokenize_func, batched=True, num_proc=NUM_PROC)
    
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME, num_labels=2)
    
    # 🔥 优化2: DataLoader 并行
    args = TrainingArguments(
        output_dir=MODEL_DIR,
        eval_strategy="epoch",
        save_strategy="epoch",
        learning_rate=LEARNING_RATE,
        per_device_train_batch_size=BATCH_SIZE,
        per_device_eval_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=GRAD_ACCUMULATION,
        num_train_epochs=EPOCHS,
        weight_decay=0.01,
        load_best_model_at_end=True,
        metric_for_best_model="f1",
        use_mps_device=(get_device() == "mps"),
        logging_steps=20,
        save_total_limit=2,
        # 关键并行参数
        dataloader_num_workers=NUM_WORKERS, 
        dataloader_pin_memory=True
    )
    
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        tokenizer=tokenizer,
        data_collator=DataCollatorWithPadding(tokenizer),
        compute_metrics=compute_metrics
    )
    
    trainer.train()
    trainer.save_model(MODEL_DIR)
    tokenizer.save_pretrained(MODEL_DIR)
    print(f"[OK] 模型微调完成。")

def score_all_sentences():
    print(f"[Step 2-C] 全量预测 (High Performance)...")
    
    if not os.path.exists(ALL_SENTENCES_RAW):
        sys.exit(1)
        
    df = pd.read_csv(ALL_SENTENCES_RAW).dropna(subset=["text"])
    texts = df["text"].astype(str).tolist()
    
    tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_DIR)
    
    device = torch.device(get_device())
    print(f"   - Device: {device}")
    model.to(device)
    model.eval()
    
    # 🔥 优化3: 手动构建简单的 DataLoader 来利用多进程加载
    # 虽然这里数据量不大，但为了规范，我们可以简单地做批量处理
    
    probs = []
    # 推理 Batch 增大
    infer_batch = 64 
    
    for i in tqdm(range(0, len(texts), infer_batch), desc="Inference"):
        batch_text = texts[i : i+infer_batch]
        inputs = tokenizer(batch_text, padding=True, truncation=True, max_length=MAX_LEN, return_tensors="pt")
        inputs = {k: v.to(device) for k, v in inputs.items()}
        
        with torch.no_grad():
            outputs = model(**inputs)
            scores = torch.softmax(outputs.logits, dim=1)
            neg_probs = scores[:, 1].cpu().numpy()
            probs.extend(neg_probs)
            
    df["roberta_neg_prob"] = probs
    df.to_csv(SCORED_CSV, index=False, encoding="utf-8-sig")
    print(f"[Success] 结果已保存: {SCORED_CSV}")

if __name__ == "__main__":
    # Mac 上多进程需要设置 start_method
    try:
        import torch.multiprocessing as mp
        mp.set_start_method('spawn', force=True)
    except RuntimeError:
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", default="all", choices=["prepare", "train", "score", "all"])
    args = parser.parse_args()
    
    if args.stage in ["prepare", "all"]:
        prepare_training_data()
    if args.stage in ["train", "all"]:
        train_model()
    if args.stage in ["score", "all"]:
        score_all_sentences()