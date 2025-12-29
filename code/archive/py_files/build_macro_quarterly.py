# build_macro_quarterly.py
# 把「宏观经济数据.csv」(Wind 导出) 和 macro_controls_daily.csv
# 处理成 2001Q1-2024Q4 的季度宏观数据，用于和 ToneReal / ToneGuid 做回归。

import pandas as pd
from pathlib import Path


def build_quarterly_macro(
    macro_csv_path: str = "宏观经济数据.csv",
    daily_rate_csv_path: str = "macro_controls_daily.csv",
    out_path: str = "macro_quarterly_for_text.csv",
) -> pd.DataFrame:
    """
    读取：
        - 宏观经济数据.csv (CPI, GDP, M2, 工业增加值, 进出口)
        - macro_controls_daily.csv (short_rate 日度)
    输出：
        - 2001Q1-2024Q4 的季度数据 DataFrame，并保存为 CSV
    """

    # -------------------------
    # 1. 读取宏观数据（Wind 导出）
    # -------------------------
    macro = pd.read_csv(macro_csv_path, encoding="gbk")

    # 去掉第一行“单位”和最后的“数据来源：Wind”行
    macro = macro[~macro["指标名称"].isin(["单位"])]
    macro = macro[~macro["指标名称"].astype(str).str.contains("数据来源", na=False)]

    # 解析日期
    macro["date"] = pd.to_datetime(macro["指标名称"])

    # 需要用到的列名（和 Wind 导出的字段保持一致）
    COL_CPI = "中国:CPI:当月同比"
    COL_GDP_Q = "中国:GDP:不变价:当季同比"
    COL_M2 = "中国:M2:同比"
    COL_IP = "中国:工业增加值:规模以上工业企业:当月同比(1-2月拆分)"
    COL_EXPORT = "中国:进出口金额:当月同比"

    # 相关列全部转成数值型，无法转换的设为 NaN
    for col in [COL_CPI, COL_GDP_Q, COL_M2, COL_IP, COL_EXPORT]:
        macro[col] = pd.to_numeric(macro[col], errors="coerce")

    # 按季度聚合
    macro["period"] = macro["date"].dt.to_period("Q")
    macro_q = (
        macro.groupby("period")
        .agg(
            {
                COL_GDP_Q: "max",      # GDP: 季度本身只有季末有值，max/last 都可以
                COL_CPI: "mean",       # CPI: 季度平均
                COL_M2: "last",        # M2: 季末值
                COL_IP: "mean",        # 工业增加值: 季度平均
                COL_EXPORT: "mean",    # 进出口: 季度平均
            }
        )
        .sort_index()
    )

    # 只保留 2001Q1 - 2024Q4，这和你的文本样本一致
    macro_q = macro_q.loc["2001Q1":"2024Q4"].copy()

    # -------------------------
    # 2. 读取日度短端利率并聚合成季度
    # -------------------------
    daily = pd.read_csv(daily_rate_csv_path, parse_dates=["date"])
    daily = daily.sort_values("date")
    daily = daily[(daily["date"] >= "2001-01-01") & (daily["date"] <= "2024-12-31")]

    # 这里用的是你已经构造好的 short_rate（缺 Shibor 的早期用 7 天回购补）
    daily["period"] = daily["date"].dt.to_period("Q")
    rate_q = (
        daily.groupby("period")["short_rate"]
        .mean()
        .to_frame("short_rate_level")
        .sort_index()
    )

    # -------------------------
    # 3. 合并 & 重命名变量
    # -------------------------
    macro_q = macro_q.join(rate_q, how="inner").reset_index()

    macro_q["year"] = macro_q["period"].dt.year
    macro_q["quarter"] = macro_q["period"].dt.quarter

    # 季度短端利率变动（可以在回归里用或当额外解释变量）
    macro_q["short_rate_chg_q"] = macro_q["short_rate_level"].diff()

    # 英文变量名，方便后续回归书写
    macro_q = macro_q.rename(
        columns={
            COL_GDP_Q: "gdp_yoy",
            COL_CPI: "cpi_yoy",
            COL_M2: "m2_yoy",
            COL_IP: "ip_yoy",
            COL_EXPORT: "export_yoy",
        }
    )

    # 列的顺序整理一下
    cols_order = [
        "period",
        "year",
        "quarter",
        "gdp_yoy",
        "cpi_yoy",
        "m2_yoy",
        "ip_yoy",
        "export_yoy",
        "short_rate_level",
        "short_rate_chg_q",
    ]
    macro_q = macro_q[cols_order]

    # -------------------------
    # 4. 导出结果
    # -------------------------
    out_path = Path(out_path)
    macro_q.to_csv(out_path, index=False)
    print(f"[OK] 季度宏观数据已保存至: {out_path.resolve()}")
    print(macro_q.head())

    return macro_q


if __name__ == "__main__":
    build_quarterly_macro()
