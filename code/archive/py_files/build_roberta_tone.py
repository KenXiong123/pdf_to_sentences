import os
import pandas as pd


# ========= 配置区域 =========
SENT_FILE = "all_sentences_with_roberta_score.csv"  # 已经有 roberta_neg_prob 的句子文件
OUT_FILE = "tone_by_quarter_roberta.csv"            # 输出的季度语气指标
REPORT_DATES_FILE = "report_dates.csv"              # 可选：year, quarter, report_date
# ===========================


def zscore(s: pd.Series) -> pd.Series:
    """简单 z-score 标准化，返回 (s - mean) / std。"""
    m = s.mean()
    std = s.std()
    if std == 0 or pd.isna(std):
        return pd.Series([0.0] * len(s), index=s.index)
    return (s - m) / std


def _is_real_part(year, quarter, section: str) -> bool:
    """
    基本面部分（Real / Fundamentals）：
    - 正常年份：S1-S4
    - 2002Q3：只有 S1-S3 视为基本面
    """
    sec = str(section).strip()
    try:
        y = int(year)
        q = int(quarter)
    except Exception:
        return False

    if y == 2002 and q == 3:
        return sec in ["S1", "S2", "S3"]
    else:
        return sec in ["S1", "S2", "S3", "S4"]


def _is_guidance_part(year, quarter, section: str) -> bool:
    """
    政策前瞻部分（Guidance / Policy）：
    - 正常年份：S5
    - 2002Q3：S4 就是“下一阶段政策”部分
    """
    sec = str(section).strip()
    try:
        y = int(year)
        q = int(quarter)
    except Exception:
        return False

    if y == 2002 and q == 3:
        return sec == "S4"
    else:
        return sec == "S5"


def main():
    if not os.path.exists(SENT_FILE):
        raise FileNotFoundError(f"找不到句子文件：{SENT_FILE}")

    df = pd.read_csv(SENT_FILE)
    required_cols = {"year", "quarter", "section", "roberta_neg_prob"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"{SENT_FILE} 缺少必要列：{missing}")

    # 确保 year / quarter 为数值型，避免后面比较出错
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["quarter"] = pd.to_numeric(df["quarter"], errors="coerce").astype("Int64")

    # 1. 定义“正向语气”得分：越大越乐观
    df["tone_sent"] = 1.0 - df["roberta_neg_prob"]

    # 2. 标记 Real / Guidance 区域
    df["is_real"] = df.apply(
        lambda r: _is_real_part(r["year"], r["quarter"], r["section"]), axis=1
    )
    df["is_guid"] = df.apply(
        lambda r: _is_guidance_part(r["year"], r["quarter"], r["section"]), axis=1
    )

    # 3. 整体语气（不分部分）
    grp_cols = ["year", "quarter"]
    tone_all = (
        df.groupby(grp_cols)["tone_sent"]
        .mean()
        .reset_index()
        .rename(columns={"tone_sent": "tone_all"})
    )

    # 4. 基本面部分：Real（根据 is_real）
    tone_real = (
        df[df["is_real"]]
        .groupby(grp_cols)["tone_sent"]
        .mean()
        .reset_index()
        .rename(columns={"tone_sent": "tone_real"})
    )

    # 5. 政策前瞻部分：Guidance（根据 is_guid）
    tone_guid = (
        df[df["is_guid"]]
        .groupby(grp_cols)["tone_sent"]
        .mean()
        .reset_index()
        .rename(columns={"tone_sent": "tone_guid"})
    )

    # 6. 合并三个指标
    tone_q = (
        tone_all
        .merge(tone_real, on=grp_cols, how="left")
        .merge(tone_guid, on=grp_cols, how="left")
    )

    # 7. 对三者分别做 z-score
    for col in ["tone_all", "tone_real", "tone_guid"]:
        if col in tone_q.columns:
            tone_q[col + "_z"] = zscore(tone_q[col])

    # 8. 如果有 report_dates.csv，则合并上去（方便对照）
    if os.path.exists(REPORT_DATES_FILE):
        rep = pd.read_csv(REPORT_DATES_FILE)
        rep_cols = {"year", "quarter", "report_date"} & set(rep.columns)
        if {"year", "quarter"}.issubset(rep_cols):
            rep_subset = rep[list(rep_cols)]
            tone_q = tone_q.merge(rep_subset, on=grp_cols, how="left")
            print("[INFO] 已合并报告发布日期。")
        else:
            print(
                f"[WARN] {REPORT_DATES_FILE} 不含 year/quarter 列，"
                "跳过合并报告日期。"
            )
    else:
        print(f"[WARN] 未找到 {REPORT_DATES_FILE}，跳过合并报告日期。")

    # 9. 保存结果
    tone_q.to_csv(OUT_FILE, index=False, encoding="utf-8-sig")
    print(f"[OK] RoBERTa 季度语气指标已保存到：{OUT_FILE}")
    print(tone_q.head())


if __name__ == "__main__":
    main()
