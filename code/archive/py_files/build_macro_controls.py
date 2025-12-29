# -*- coding: utf-8 -*-
"""
build_macro_controls.py  (robust version)

功能：
  从 Wind 导出的 “控制变量.csv” 构造日度宏观控制变量，用于后续 EGARCH 回归。

自动匹配列名（避免中文标点略有差异导致 KeyError）：
  - 含 "SHIBOR"           -> shibor_1w
  - 含 "美元兑人民币"       -> usdcny_mid
  - 含 "7天回购利率"        -> ib_7d
"""

import pandas as pd
import numpy as np

RAW_FILE = "控制变量.csv"
OUT_FILE = "macro_controls_daily.csv"


def find_col(cols, keywords):
    """
    在列名列表中查找第一个包含任一 keyword 的列名。
    keywords 可以是字符串或字符串列表。
    """
    if isinstance(keywords, str):
        keywords = [keywords]

    for c in cols:
        for kw in keywords:
            if kw in c:
                return c
    return None


def main():
    print(f"[INFO] 读取原始文件: {RAW_FILE}")
    # Wind 导出一般是 gbk / gb2312，两个都兼容
    df = pd.read_csv(RAW_FILE, encoding="gbk")

    # 1. 解析日期列：一般叫“指标名称”
    if "指标名称" not in df.columns:
        raise ValueError("找不到列 '指标名称'，请确认 CSV 表头。")

    df["date"] = pd.to_datetime(df["指标名称"], errors="coerce")
    df = df.dropna(subset=["date"]).copy()
    df = df.sort_values("date").reset_index(drop=True)

    # 2. 自动匹配需要的列
    cols = list(df.columns)
    shibor_col = find_col(cols, "SHIBOR")
    fx_col = find_col(cols, "美元兑人民币")
    ib_col = find_col(cols, "7天回购利率")

    print("[INFO] 自动匹配到的列：")
    print("  SHIBOR 列       :", shibor_col)
    print("  美元兑人民币列   :", fx_col)
    print("  7天回购利率列    :", ib_col)

    if fx_col is None:
        raise ValueError("未找到包含 '美元兑人民币' 的列，请检查 CSV。")

    # 3. 重命名为标准英文字段名（有则重命名，没有就跳过）
    rename_map = {}
    if shibor_col is not None:
        rename_map[shibor_col] = "shibor_1w"
    if fx_col is not None:
        rename_map[fx_col] = "usdcny_mid"
    if ib_col is not None:
        rename_map[ib_col] = "ib_7d"

    df = df.rename(columns=rename_map)

    # 4. 数值列转成 float，并做前值填充 ffill
    num_cols = [c for c in ["shibor_1w", "usdcny_mid", "ib_7d"] if c in df.columns]
    for col in num_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df[num_cols] = df[num_cols].ffill()

    # 5. 构造统一短端利率 short_rate（优先 SHIBOR，否则 ib_7d）
    if "shibor_1w" in df.columns and "ib_7d" in df.columns:
        df["short_rate"] = df["shibor_1w"].where(
            df["shibor_1w"].notna(), df["ib_7d"]
        )
    elif "shibor_1w" in df.columns:
        df["short_rate"] = df["shibor_1w"]
    elif "ib_7d" in df.columns:
        df["short_rate"] = df["ib_7d"]
    else:
        raise ValueError("既没有 SHIBOR 列，也没有 7天回购利率列，无法构造 short_rate。")

    df["short_rate_chg"] = df["short_rate"].diff()

    # 6. 汇率变化：简单差分 + 对数收益
    df["usdcny_chg"] = df["usdcny_mid"].diff()
    df["fx_ret"] = np.log(df["usdcny_mid"] / df["usdcny_mid"].shift(1))

    # 7. 可选利差：ib_7d - shibor_1w
    if "ib_7d" in df.columns and "shibor_1w" in df.columns:
        df["ib_minus_shibor"] = df["ib_7d"] - df["shibor_1w"]
    else:
        df["ib_minus_shibor"] = np.nan

    # 8. 整理输出
    out_cols = ["date",
                "usdcny_mid", "usdcny_chg", "fx_ret",
                "shibor_1w", "ib_7d",
                "short_rate", "short_rate_chg",
                "ib_minus_shibor"]
    out_cols = [c for c in out_cols if c in df.columns]

    df_out = df[out_cols].copy()
    df_out.to_csv(OUT_FILE, index=False, encoding="utf-8-sig")

    print(f"[OK] 已保存处理后的宏观控制变量到: {OUT_FILE}")
    print("[HEAD]")
    print(df_out.head())
    print("[TAIL]")
    print(df_out.tail())


if __name__ == "__main__":
    main()
