# run_macro_text_regressions.py
#
# 功能：
#   1. 读取季度文本情绪 + 季度宏观数据
#   2. 构造 ToneReal / ToneGuid 的滞后项
#   3. 分别回归：
#        ToneReal_t  ~ ToneReal_{t-1}  + gdp_yoy + cpi_yoy + m2_yoy + short_rate_level
#        ToneGuid_t  ~ ToneGuid_{t-1}  + gdp_yoy + cpi_yoy + m2_yoy + short_rate_level
#   4. 自己实现 Newey–West(HAC) 标准误，不依赖 statsmodels

import pandas as pd
import numpy as np
from pathlib import Path
from scipy.stats import t as t_dist   # 只用到 t 分布求 p 值


TONE_FILE = "tone_by_quarter_roberta.csv"
MACRO_FILE = "macro_quarterly_for_text.csv"
OUT_DIR = "macro_reg_results"


def load_and_merge_data(tone_path=TONE_FILE, macro_path=MACRO_FILE):
    """读取文本情绪 + 宏观季度数据，并按 year, quarter 合并"""

    # 1. 文本情绪
    tone = pd.read_csv(tone_path)

    # 兼容大小写 Year/Quarter
    if "Year" in tone.columns:
        tone = tone.rename(columns={"Year": "year"})
    if "Quarter" in tone.columns:
        tone = tone.rename(columns={"Quarter": "quarter"})

    required = ["year", "quarter", "tone_real_z", "tone_guid_z"]
    missing = [c for c in required if c not in tone.columns]
    if missing:
        raise ValueError(f"tone 文件缺少这些列: {missing}")

    tone = tone[required].sort_values(["year", "quarter"]).reset_index(drop=True)

    # 构造滞后项
    tone["tone_real_lag"] = tone["tone_real_z"].shift(1)
    tone["tone_guid_lag"] = tone["tone_guid_z"].shift(1)

    # 2. 宏观季度数据
    macro = pd.read_csv(macro_path)

    if "year" not in macro.columns or "quarter" not in macro.columns:
        if "period" in macro.columns:
            p = macro["period"].astype(str)
            macro["year"] = p.str.slice(0, 4).astype(int)
            macro["quarter"] = p.str.extract(r"Q([1-4])").astype(int)
        else:
            raise ValueError("宏观数据中缺少 year/quarter 信息。")

    needed_macro_cols = [
        "year",
        "quarter",
        "gdp_yoy",
        "cpi_yoy",
        "m2_yoy",
        "short_rate_level",
    ]
    missing2 = [c for c in needed_macro_cols if c not in macro.columns]
    if missing2:
        raise ValueError(f"宏观数据缺少这些列: {missing2}")

    macro = macro[needed_macro_cols]

    # 3. 合并
    df = pd.merge(
        tone,
        macro,
        on=["year", "quarter"],
        how="inner",
        validate="one_to_one",
    ).sort_values(["year", "quarter"])

    # 删掉第一期（滞后项是 NaN）
    df = df.dropna(subset=["tone_real_lag", "tone_guid_lag"]).reset_index(drop=True)

    return df


def newey_west(y, X, lags=4):
    """
    纯 numpy 实现的 Newey–West 协方差矩阵估计：
        beta = (X'X)^(-1) X'y
        Var(beta) = (X'X)^(-1) S (X'X)^(-1)
    其中 S 是带 Bartlett 权重的自协方差和。
    """
    y = np.asarray(y, float).reshape(-1)
    X = np.asarray(X, float)
    T, k = X.shape

    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ (X.T @ y)
    u = y - X @ beta  # 残差

    # Gamma_0 部分
    S = np.zeros((k, k))
    for t in range(T):
        xt = X[t:t + 1, :]
        S += (u[t] ** 2) * (xt.T @ xt)

    # 其余滞后项
    for ell in range(1, lags + 1):
        w = 1 - ell / (lags + 1)  # Bartlett 权重
        Gamma = np.zeros((k, k))
        for t in range(ell, T):
            xt = X[t:t + 1, :]
            xt_lag = X[t - ell:t - ell + 1, :]
            Gamma += u[t] * u[t - ell] * (xt.T @ xt_lag)
        S += w * (Gamma + Gamma.T)

    var_beta = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.diag(var_beta))
    t_stat = beta / se
    dfree = T - k
    p_values = 2 * (1 - t_dist.cdf(np.abs(t_stat), dfree))

    # R^2
    y_hat = X @ beta
    rss = np.sum((y - y_hat) ** 2)
    tss = np.sum((y - y.mean()) ** 2)
    r2 = 1 - rss / tss

    return beta, se, t_stat, p_values, r2, dfree


def run_regression(df, dep_col, lag_col, macro_cols, lags=4):
    """
    跑一条：
        y_t = const + rho * y_{t-1} + beta' * macro_t + u_t
    用 NW-HAC 标准误。
    """
    X = df[[lag_col] + macro_cols].copy()
    X.insert(0, "const", 1.0)
    y = df[dep_col].values

    beta, se, t_stat, p_values, r2, dfree = newey_west(y, X.values, lags=lags)

    return {
        "X_cols": X.columns.tolist(),
        "beta": beta,
        "se": se,
        "t": t_stat,
        "p": p_values,
        "r2": r2,
        "df": dfree,
        "n": len(y),
    }


def format_result(res, title):
    lines = []
    lines.append("=" * 80)
    lines.append(title)
    lines.append("=" * 80)
    lines.append(
        f"样本期数 n = {res['n']}, 自由度 df = {res['df']}, R^2 = {res['r2']:.3f}"
    )
    lines.append("")
    lines.append(f"{'变量':<20}{'系数':>12}{'Std.Err':>12}{'t值':>12}{'p值':>12}")
    for name, b, s, t, p in zip(
        res["X_cols"], res["beta"], res["se"], res["t"], res["p"]
    ):
        lines.append(f"{name:<20}{b:>12.4f}{s:>12.4f}{t:>12.2f}{p:>12.4f}")
    return "\n".join(lines)


def main():
    df = load_and_merge_data()
    print("[INFO] 合并后的样本期数:", len(df))
    print(
        "[INFO] 时间范围: ",
        int(df["year"].iloc[0]),
        "Q",
        int(df["quarter"].iloc[0]),
        " ~ ",
        int(df["year"].iloc[-1]),
        "Q",
        int(df["quarter"].iloc[-1]),
    )

    macro_cols = ["gdp_yoy", "cpi_yoy", "m2_yoy", "short_rate_level"]

    # ToneReal 回归
    res_real = run_regression(
        df,
        dep_col="tone_real_z",
        lag_col="tone_real_lag",
        macro_cols=macro_cols,
        lags=4,
    )

    # ToneGuid 回归
    res_guid = run_regression(
        df,
        dep_col="tone_guid_z",
        lag_col="tone_guid_lag",
        macro_cols=macro_cols,
        lags=4,
    )

    out_dir = Path(OUT_DIR)
    out_dir.mkdir(exist_ok=True)

    txt_real = format_result(
        res_real, "回归一：ToneReal 对宏观基本面的反应（Newey-West 标准误）"
    )
    txt_guid = format_result(
        res_guid, "回归二：ToneGuid 对宏观基本面的反应（Newey-West 标准误）"
    )

    print(txt_real)
    print()
    print(txt_guid)

    (out_dir / "reg_ToneReal_vs_macro.txt").write_text(txt_real, encoding="utf-8")
    (out_dir / "reg_ToneGuid_vs_macro.txt").write_text(txt_guid, encoding="utf-8")

    print(f"\n[OK] 结果已保存到: {out_dir.resolve()}")


if __name__ == "__main__":
    main()
