# run_egarch_r.R
# 需要的包：
# install.packages(c("readr", "dplyr", "xts", "rugarch"))

library(readr)
library(dplyr)
library(xts)
library(rugarch)

DATA_FILE <- "egarch_daily_data_roberta.csv"

# 在这里指定“利率”变量在 CSV 里的列名 -------------------------------
RATE_COL <- "short_rate_chg"  # 利率：例如短端利率的日变动

# 1. 读入日度数据 ----------------------------------------------------------

df <- read_csv(
  DATA_FILE,
  col_types = cols(
    date = col_date()
  )
)

df <- df %>% arrange(date)

cat("[INFO] 读取数据成功:", DATA_FILE, "\n")
cat("[INFO] 列名:\n")
print(colnames(df))


# 2. 写一个函数：对单个指数做 EGARCH-X ----------------------------------

run_egarch_for_index <- function(df, ret_col) {
  cat("\n", strrep("=", 80), "\n", sep = "")
  cat("Estimating eGARCH(1,1) with exogenous vars for", ret_col, "...\n")
  cat(strrep("=", 80), "\n")
  
  # 2.1 检查该指数是否存在
  if (!ret_col %in% colnames(df)) {
    cat("[WARN]", ret_col, "不在数据中，跳过。\n")
    return(NULL)
  }
  
  # 2.2 检查利率列是否存在 -----------------------------------------------
  rate_in_data <- intersect(RATE_COL, colnames(df))
  if (length(rate_in_data) == 0) {
    cat("[WARN] 利率变量", RATE_COL, "在数据中不存在，均值方程只使用情绪变量。\n")
  } else {
    cat("[INFO] 均值方程中将纳入的利率变量:\n")
    print(rate_in_data)
  }
  
  # 2.3 取该指数的收益率 + 事件变量 + 利率，去掉 NA -----------------------
  tmp <- df %>%
    select(
      date,
      all_of(ret_col),
      ToneRealEvent, ToneGuidEvent,
      ReadabilityEvent,          # 波动方程外生变量（只保留可读性）
      any_of(rate_in_data)       # 利率控制变量（如果存在）
    ) %>%
    filter(complete.cases(.))
  
  # 如果删完 NA 太少数据，也给个提示
  cat("[INFO]", ret_col, "用于估计的样本量:", nrow(tmp), "\n")
  
  # 2.4 构建 y、均值方程外生变量、波动方程外生变量 ------------------------
  
  # 被解释变量：收益率 * 100（和 Python 保持一致）
  y <- 100 * tmp[[ret_col]]
  
  # 均值方程外生变量：情绪 + 利率
  mean_exo_cols <- c("ToneRealEvent", "ToneGuidEvent", rate_in_data)
  X_mean <- as.matrix(tmp[, mean_exo_cols, drop = FALSE])
  
  # 波动方程外生变量：只保留可读性（去掉 surprise）
  X_var  <- as.matrix(tmp[, c("ReadabilityEvent"), drop = FALSE])
  
  # 转成 xts 序列
  y_xts <- xts(y, order.by = tmp$date)
  
  # 2.5 指定 eGARCH(1,1) 模型 ---------------------------------------------
  spec <- ugarchspec(
    variance.model = list(
      model = "eGARCH",
      garchOrder = c(1, 1),
      # 外生变量进入波动方程：只有 ReadabilityEvent
      external.regressors = X_var
    ),
    mean.model = list(
      armaOrder = c(1, 0),      # AR(1)
      include.mean = TRUE,
      # 外生变量进入均值方程：ToneReal + ToneGuid + 利率（如果有）
      external.regressors = X_mean
    ),
    distribution.model = "std"  # 学生 t 分布
  )
  
  # 2.6 拟合 ---------------------------------------------------------------
  fit <- ugarchfit(spec = spec, data = y_xts, solver = "hybrid")
  
  # 2.7 把结果输出到 txt 里保存 -------------------------------------------
  out_file <- paste0("egarch_result_", ret_col, "_roberta_r.txt")
  sink(out_file)
  show(fit)
  sink()
  
  cat("[OK] 结果已保存到:", out_file, "\n")
  
  return(fit)
}


# 3. 对四个指数循环估计 ----------------------------------------------------

index_list <- c("SH", "SZ", "HS300", "CSI500")

fits <- list()

for (idx in index_list) {
  fits[[idx]] <- run_egarch_for_index(df, idx)
}

cat("\n[INFO] 所有指数的 eGARCH-X 模型估计完成。\n")
