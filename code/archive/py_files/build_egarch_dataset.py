import pandas as pd


def build_tone_event_daily(
    daily_returns_path: str,
    tone_by_quarter_path: str,
    report_dates_path: str,
    macro_controls_path: str | None = None,
    out_path: str = "egarch_daily_data_roberta.csv",
) -> pd.DataFrame:
    """
    构建 EGARCH 用的日度数据（含文本情绪 + “惊吓/可读性”指标）.

    输入
    ----
    daily_returns_path : str
        四指数日收益 csv，至少包含 [date, SH, SZ, HS300, CSI500]
    tone_by_quarter_path : str
        tone_by_quarter_roberta.csv
        需要包含：
          - year, quarter
          - tone_real_z  : S1–S4（基本面）情绪
          - tone_guid_z  : S5（政策指引）情绪
          - similarity_prev, surprise_prev, avg_sent_len
            （由 build_variance_indicators.py 生成）
    report_dates_path : str
        report_dates.csv，包含 year, quarter, report_date
    macro_controls_path : str | None
        （可选）日度宏观控制变量 csv，至少包含 [date, ...各种宏观变量...]
    out_path : str
        输出 csv 路径

    输出
    ----
    DataFrame，并保存为 out_path：
        date, SH, SZ, HS300, CSI500,
        ToneRealEvent, ToneGuidEvent,
        PolicySurpriseEvent, ReadabilityEvent, SimilarityEvent,
        以及（如果有的话）宏观控制变量列
    """

    # 1. 日度收益
    daily = pd.read_csv(daily_returns_path)
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.sort_values("date").reset_index(drop=True)

    # 1.1 （可选）日度宏观控制变量，按 date 左连接到日收益上
    if macro_controls_path is not None:
        macro = pd.read_csv(macro_controls_path)
        macro["date"] = pd.to_datetime(macro["date"])
        macro = macro.sort_values("date").reset_index(drop=True)
        # 保留所有交易日，有宏观数据的就填上，没有的为 NaN
        daily = daily.merge(macro, on="date", how="left")

    first_trading = daily["date"].min()

    # 2. 读取季度文本指标
    tone = pd.read_csv(tone_by_quarter_path)
    tone = tone.rename(columns={"Year": "year", "Quarter": "quarter"})

    # 2.1 兼容不同情绪列的情况：
    #     基本面 & 政策情绪（如果不存在，就先放成 NaN，后面会 fillna(0)）
    if "tone_real_z" not in tone.columns:
        tone["tone_real_z"] = pd.NA
    if "tone_guid_z" not in tone.columns:
        tone["tone_guid_z"] = pd.NA

    # 原有单一情绪列，用于 ToneEvent（baseline）
    tone_col = None
    if "tone_all_z" in tone.columns:
        tone_col = "tone_all_z"
        print("[INFO] ToneEvent 使用 RoBERTa tone_all_z（整体文本情绪）")
    elif "tone_guid_z" in tone.columns:
        tone_col = "tone_guid_z"
        print("[INFO] ToneEvent 使用 RoBERTa tone_guid_z（S5 指引情绪）")
    elif "Neg_net_z" in tone.columns:
        tone_col = "Neg_net_z"
        print("[INFO] ToneEvent 使用词典版 Neg_net_z")
    else:
        # 如果完全没有，就直接用 tone_real_z 做兜底（有可能你只算了 S1–S4）
        tone_col = "tone_real_z"
        print("[WARN] 未找到 tone_all_z / tone_guid_z / Neg_net_z，ToneEvent 使用 tone_real_z")

    tone["tone_z"] = tone[tone_col]

    # 如果 build_variance_indicators.py 已经生成了以下列，就一并保留：
    extra_cols = []
    for c in ["similarity_prev", "surprise_prev", "avg_sent_len"]:
        if c in tone.columns:
            extra_cols.append(c)

    keep_cols = ["year", "quarter", "tone_z", "tone_real_z", "tone_guid_z"] + extra_cols
    tone = tone[keep_cols]

    # 3. 报告发布日期
    report = pd.read_csv(report_dates_path)
    report["report_date"] = pd.to_datetime(report["report_date"])

    # 只保留“有价格数据”的报告：报告日 >= 第一笔交易日
    report = report[report["report_date"] >= first_trading].copy()

    # 4. 合并 tone + 报告日期
    rep_tone = pd.merge(tone, report, on=["year", "quarter"], how="inner")
    rep_tone = rep_tone.sort_values("report_date").reset_index(drop=True)

    # 5. 映射到之后第一个交易日 trade_date （事件日）
    trading_dates = daily["date"].sort_values().values
    trade_dates = []

    for _, row in rep_tone.iterrows():
        rd = row["report_date"]
        mask = trading_dates > rd
        if mask.sum() == 0:
            trade_dates.append(pd.NaT)
        else:
            trade_dates.append(trading_dates[mask.argmax()])

    rep_tone["trade_date"] = pd.to_datetime(trade_dates)
    rep_tone = rep_tone.dropna(subset=["trade_date"])

    # 6. 以 trade_date 为 key，把所有文本指标聚合到日度层面
    group_cols = ["tone_z", "tone_real_z", "tone_guid_z"] + extra_cols
    tone_by_trade_date = (
        rep_tone.groupby("trade_date")[group_cols]
                .mean()
                .reset_index()
    )

    # 为每个指标建立映射 dict
    tone_maps = {
        col: dict(zip(tone_by_trade_date["trade_date"], tone_by_trade_date[col]))
        for col in group_cols
    }

    # 7. 在日度数据中生成事件变量
    #   - ToneEvent: 旧版单一情绪（兼容）
    #   - ToneRealEvent: S1–S4（基本面）情绪事件
    #   - ToneGuidEvent: S5（政策指引）情绪事件
    #   - PolicySurpriseEvent: 本期“惊吓程度”（1-Similarity）
    #   - ReadabilityEvent: 本期报告的平均句长（越大越难读）
    #   - SimilarityEvent: 如果你想直接在模型里用相似度（预期系数为负）

    def map_or_zero(col_name: str, new_name: str):
        if col_name in tone_maps:
            daily[new_name] = daily["date"].map(tone_maps[col_name]).fillna(0.0)
        else:
            daily[new_name] = 0.0

    map_or_zero("tone_z", "ToneEvent")
    map_or_zero("tone_real_z", "ToneRealEvent")
    map_or_zero("tone_guid_z", "ToneGuidEvent")
    map_or_zero("surprise_prev", "PolicySurpriseEvent")
    map_or_zero("avg_sent_len", "ReadabilityEvent")
    map_or_zero("similarity_prev", "SimilarityEvent")

    # 8. 保存结果
    daily.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"[OK] EGARCH 日度数据已保存到: {out_path}")
    return daily


def main():
    daily_returns_path = "daily_returns_4idx.csv"
    tone_by_quarter_path = "tone_by_quarter_roberta.csv"
    report_dates_path = "report_dates.csv"
    macro_controls_path = "macro_controls_daily.csv"

    build_tone_event_daily(
        daily_returns_path=daily_returns_path,
        tone_by_quarter_path=tone_by_quarter_path,
        report_dates_path=report_dates_path,
        macro_controls_path=macro_controls_path,
        out_path="egarch_daily_data_roberta.csv",
    )


if __name__ == "__main__":
    main()
