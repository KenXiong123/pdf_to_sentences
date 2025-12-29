import pandas as pd
from snownlp import SnowNLP
from tqdm import tqdm

# 让 pandas 的 apply 带进度条
tqdm.pandas()


def get_sentiment_score(text):
    """
    用 SnowNLP 计算情感得分，直接用原始 text，不做额外 clean。
    """
    if text is None:
        return None
    text = str(text)
    if text.strip() == "":
        return None
    try:
        return SnowNLP(text).sentiments  # 0~1
    except Exception:
        # 文本有问题时返回 None，后面会丢弃
        return None


def main():
    input_path = "/Users/kenxiong/Desktop/硕士毕业论文/code/all_sentences.csv"

    # --- 1. 读取数据 ---
    try:
        df = pd.read_csv(input_path)
    except FileNotFoundError:
        print(f"Error: '{input_path}' not found. Please make sure the file is in the correct directory.")
        return

    # 检查必要列是否存在（按你的 csv 列名来，这里默认：year / quarter / text）
    required_cols = ["year", "quarter", "text"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(
            f"Input CSV is missing columns: {missing}. "
            f"Please make sure it has at least: {required_cols}"
        )

    print(f"Loaded {len(df)} sentences from {input_path}")

    # 去掉 text 为 NaN 的行，其他不做清洗
    df = df.dropna(subset=["text"])
    print(f"Remaining {len(df)} sentences after dropping NA text.")

    # --- 2. 情感分析（带进度条）---
    print("Running SnowNLP sentiment analysis with progress bar ...")
    df["sentiment_score"] = df["text"].progress_apply(get_sentiment_score)

    # 丢掉计算失败的
    before_drop = len(df)
    df = df.dropna(subset=["sentiment_score"])
    print(
        f"Dropped {before_drop - len(df)} sentences with invalid sentiment. "
        f"Valid sentences: {len(df)}"
    )

    # --- 3. 构造 tone_sentence 指标 ---
    # score - 0.5，>0 偏乐观，<0 偏悲观
    df["tone_sentence"] = df["sentiment_score"] - 0.5

    # --- 4. 聚合到季度层面 ---
    print("Aggregating to quarterly tone index ...")
    tone_q = (
        df.groupby(["year", "quarter"])["tone_sentence"]
          .agg(["mean", "median", "count"])
          .reset_index()
          .rename(columns={
              "mean": "tone_mean",
              "median": "tone_median",
              "count": "n_sentences"
          })
    )

    tone_q = tone_q.sort_values(["year", "quarter"])

    # --- 5. 保存结果 ---
    df.to_csv("/Users/kenxiong/Desktop/硕士毕业论文/code/all_sentences_with_tone.csv", index=False, encoding="utf-8-sig")
    tone_q.to_csv("/Users/kenxiong/Desktop/硕士毕业论文/code/tone_by_quarter.csv", index=False, encoding="utf-8-sig")

    print("\nSentiment analysis complete.")
    print("Sentence-level results saved to: all_sentences_with_tone.csv")
    print("Quarter-level tone index saved to: tone_by_quarter.csv\n")
    print("Preview of quarterly tone index:")
    print(tone_q.head())


if __name__ == "__main__":
    main()
