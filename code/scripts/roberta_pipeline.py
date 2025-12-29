import argparse
import pandas as pd
import numpy as np
from tqdm import tqdm

import torch
from datasets import load_dataset
from sklearn.metrics import accuracy_score, f1_score
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    Trainer,
    TrainingArguments,
)

# ================== 配置区域 ==================
# 1. 预训练 RoBERTa 模型名
MODEL_NAME = "hfl/chinese-roberta-wwm-ext"

# 2. 文件路径（按你的实际文件名改）
ALL_SENTENCES_WITH_DICT = "all_sentences_with_dict_scores.csv"  # 有 Neg_net 的句子文件
ALL_SENTENCES_RAW = "all_sentences.csv"                         # 如果你只想基于原句子打分，也可以换成上一个
TRAIN_CSV = "roberta_train_sentences.csv"                       # 中间产物：弱标签训练集
MODEL_DIR = "roberta_pbc_sentiment"                             # 微调后的模型保存目录
SCORED_CSV = "all_sentences_with_roberta_score.csv"             # 输出：带 roberta_neg_prob 的文件

MAX_LEN = 128
BATCH_SIZE = 64
# ============================================================


# ========= 阶段 1：用 Neg_net 生成弱标签训练集 =========
def is_training_worthy(text: str) -> bool:
    """
    过滤掉那种纯数据罗列、报账型句子，避免当成强烈情绪样本。
    策略：数字字符占比 > 15% 的句子，直接踢出训练集。
    你以后觉得太宽/太窄，可以把 0.15 调一下。
    """
    if not isinstance(text, str) or not text:
        return False
    num_count = sum(c.isdigit() for c in text)
    if num_count / len(text) > 0.15:
        return False
    return True


def prepare_dataset():
    df = pd.read_csv(ALL_SENTENCES_WITH_DICT)

    # 1. 文本列名（根据实际改）
    text_col = "text"
    if text_col not in df.columns:
        raise ValueError(f"找不到 {text_col} 列，请检查 {ALL_SENTENCES_WITH_DICT} 的列名。")

    df[text_col] = df[text_col].astype(str).str.strip()
    df = df[df[text_col].str.len() >= 5].copy()  # 去掉太短的句子

    if "Neg_net" not in df.columns:
        raise ValueError("找不到 Neg_net 列，请确认前面词典打分结果里有该列。")

    # 2. 先过滤掉纯数字/报账型句子，减少噪音
    df = df[df[text_col].apply(is_training_worthy)].copy()

    score = df["Neg_net"].astype(float)

    # 3. 用更收紧的分位数阈值选出“非常极端”的正负句子（10%/90%）
    q_low, q_high = score.quantile([0.1, 0.9])
    print(f"[INFO] Neg_net 10% 分位: {q_low:.4f}, 90% 分位: {q_high:.4f}")

    # Neg_net 低 = 负面程度低（更正向），打 label=0
    df_pos = df[score <= q_low].copy()
    df_pos["label"] = 0  # 0 = 正向（负面词少）

    # Neg_net 高 = 负面程度高，打 label=1
    df_neg = df[score >= q_high].copy()
    df_neg["label"] = 1  # 1 = 负向（负面词多）

    # 4. 正负样本数量平衡
    min_len = min(len(df_pos), len(df_neg))
    df_pos = df_pos.sample(n=min_len, random_state=42)
    df_neg = df_neg.sample(n=min_len, random_state=42)

    data = pd.concat([df_pos, df_neg], ignore_index=True)
    data = data.sample(frac=1.0, random_state=42).reset_index(drop=True)

    print("[INFO] 正样本数量( label=0 ):", (data["label"] == 0).sum())
    print("[INFO] 负样本数量( label=1 ):", (data["label"] == 1).sum())

    data[[text_col, "label"]].to_csv(TRAIN_CSV, index=False, encoding="utf-8-sig")
    print(f"[OK] 训练集已保存到 {TRAIN_CSV}")


# ========= 阶段 2：微调 RoBERTa 情绪模型 =========
def compute_metrics(eval_pred):
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=1)
    return {
        "accuracy": accuracy_score(labels, preds),
        "f1": f1_score(labels, preds),
    }


def train_model():
    # 1. 加载训练集
    raw_dset = load_dataset("csv", data_files={"train": TRAIN_CSV})
    dset = raw_dset["train"].train_test_split(test_size=0.1, seed=42)

    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)

    def tokenize(batch):
        return tokenizer(
            batch["text"],
            padding="max_length",
            truncation=True,
            max_length=MAX_LEN,
        )

    tokenized = dset.map(tokenize, batched=True)
    tokenized = tokenized.remove_columns(["text"])
    tokenized.set_format("torch")

    # 2. 加载预训练 RoBERTa
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_NAME,
        num_labels=2
    )

    # 3. 设置训练参数
    args = TrainingArguments(
        output_dir=MODEL_DIR,
        learning_rate=2e-5,
        per_device_train_batch_size=16,
        per_device_eval_batch_size=32,
        num_train_epochs=3,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="f1",
        logging_steps=50,
    )

    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=tokenized["train"],
        eval_dataset=tokenized["test"],
        compute_metrics=compute_metrics,
    )

    # 4. 训练
    trainer.train()

    # 5. 保存最优模型和 tokenizer
    trainer.save_model(MODEL_DIR)
    tokenizer.save_pretrained(MODEL_DIR)
    print(f"[OK] 模型已保存到 {MODEL_DIR}")


# ========= 阶段 3：用训练好的模型给所有句子打分 =========
def score_sentences():
    # 你可以用 all_sentences_with_dict_scores.csv 或 all_sentences.csv
    df = pd.read_csv(ALL_SENTENCES_WITH_DICT)

    text_col = "text"
    if text_col not in df.columns:
        raise ValueError(f"找不到 {text_col} 列，请检查 {ALL_SENTENCES_WITH_DICT} 的列名。")

    df[text_col] = df[text_col].astype(str).str.strip().fillna("")

    tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_DIR)
    model.eval()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    print(f"[INFO] 使用设备: {device}")

    probs = []
    texts = df[text_col].tolist()

    for i in tqdm(range(0, len(texts), BATCH_SIZE), desc="Scoring"):
        batch_texts = texts[i:i + BATCH_SIZE]
        enc = tokenizer(
            batch_texts,
            padding=True,
            truncation=True,
            max_length=MAX_LEN,
            return_tensors="pt",
        )
        enc = {k: v.to(device) for k, v in enc.items()}

        with torch.no_grad():
            logits = model(**enc).logits
            # label=1 代表负面，取负面概率
            batch_probs = torch.softmax(logits, dim=1)[:, 1]
            probs.extend(batch_probs.cpu().numpy().tolist())

    df["roberta_neg_prob"] = probs
    df.to_csv(SCORED_CSV, index=False, encoding="utf-8-sig")
    print(f"[OK] 已将 RoBERTa 情绪分数写入 {SCORED_CSV}")


# ========= 命令行入口 =========
def parse_args():
    parser = argparse.ArgumentParser(
        description="RoBERTa 情绪分析流水线：prepare/train/score/all"
    )
    parser.add_argument(
        "--stage",
        type=str,
        default="all",
        choices=["prepare", "train", "score", "all"],
        help="要执行的阶段：prepare(构建训练集)/train(训练模型)/score(打分)/all(全部顺序执行)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.stage in ("prepare", "all"):
        print("==== 阶段 1：准备弱监督训练集 ====")
        prepare_dataset()

    if args.stage in ("train", "all"):
        print("==== 阶段 2：微调 RoBERTa 模型 ====")
        train_model()

    if args.stage in ("score", "all"):
        print("==== 阶段 3：用模型为所有句子打分 ====")
        score_sentences()


if __name__ == "__main__":
    main()
