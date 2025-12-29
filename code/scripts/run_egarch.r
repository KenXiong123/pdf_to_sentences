# run_egarch.r  (NO short-end rate control)
# install.packages(c("readr", "dplyr", "xts", "rugarch", "tidyr"))

library(readr)
library(dplyr)
library(xts)
library(rugarch)
library(tidyr)

DATA_FILE <- "egarch_daily_data_roberta.csv"

# ========= 开关 =========
USE_RAW_TONE <- FALSE            # TRUE: ToneAllEvent_raw; FALSE: ToneAllEvent_z
USE_POLICY_SURPRISE <- FALSE     # TRUE: 方差方程用 PolicySurpriseEvent; FALSE: 用 SimilarityEvent
FILTER_TO_FORECAST_PERIOD <- FALSE  # TRUE: 从 GDPForecastAvailEvent 首次=1 的日期起估计（可选）
# =======================

tone_col <- if (USE_RAW_TONE) "ToneAllEvent_raw" else "ToneAllEvent_z"
TONE_COLS <- c(tone_col, "TonePolicyEvent_z", "ToneMacroEvent_z", "ToneRiskEvent_z")
TONE_COLS <- unique(TONE_COLS)
TONE_COLS <- c(tone_col_local, "TonePolicyEvent_z", "ToneMacroEvent_z", "ToneRiskEvent_z")
TONE_COLS <- unique(TONE_COLS)
sim_col  <- if (USE_POLICY_SURPRISE) "PolicySurpriseEvent" else "SimilarityEvent"

# 1) 读数据 ------------------------------------------------------------------
df <- read_csv(DATA_FILE, col_types = cols(date = col_date())) %>%
  arrange(date)

cat("[INFO] Read:", DATA_FILE, "\n")
cat("[INFO] Using tone:", tone_col_local, "\n")
cat("[INFO] Using variance text var:", sim_col, "\n")
cat("[INFO] Columns:\n")
print(colnames(df))

# 2) 可选：按 GDP forecast 可用期截断样本 -----------------------------------
if (FILTER_TO_FORECAST_PERIOD && ("GDPForecastAvailEvent" %in% colnames(df))) {
  first_ok <- df %>%
    filter(GDPForecastAvailEvent == 1) %>%
    summarise(m = min(date, na.rm = TRUE)) %>%
    pull(m)

  if (!is.na(first_ok)) {
    cat("[INFO] FILTER_TO_FORECAST_PERIOD=TRUE, sample starts at:", as.character(first_ok), "\n")
    df <- df %>% filter(date >= first_ok)
  } else {
    cat("[WARN] No GDPForecastAvailEvent==1 found. Skip truncation.\n")
  }
} else if (FILTER_TO_FORECAST_PERIOD) {
  cat("[WARN] GDPForecastAvailEvent column not found. Skip truncation.\n")
}

# 3) 模型变量列表（严格不含 short_rate_chg）---------------------------------
MEAN_X <- c("S_gdp", "S_policy", tone_col_local)    # <-- 不含任何 short rate 控制
VAR_X  <- c("D_gdp", "D_policy", "D_report", "ReadabilityEvent", sim_col)

# 4) 单指数 eGARCH-X ---------------------------------------------------------
run_egarch_for_index <- function(df, ret_col, tone_col_local_override=NULL) {
  # allow overriding tone regressor
  tone_col_local <- if (!is.null(tone_col_local_override)) tone_col_local_override else tone_col_local


  cat("\n", strrep("=", 95), "\n", sep = "")
  cat("Estimating Jiang-style eGARCH(1,1)-X for", ret_col,
      "| tone:", tone_col_local,
      "| var text:", sim_col, "\n")
  cat(strrep("=", 95), "\n")

  if (!(ret_col %in% colnames(df))) {
    cat("[WARN] Return column missing:", ret_col, "\n")
    return(NULL)
  }

  needed <- unique(c("date", ret_col, MEAN_X, VAR_X))
  missing <- setdiff(needed, colnames(df))
  if (length(missing) > 0) {
    cat("[ERROR] Missing columns in data:\n")
    print(missing)
    return(NULL)
  }

  tmp <- df %>%
    select(all_of(needed)) %>%
    # 事件变量 NA -> 0
    mutate(across(all_of(setdiff(c(MEAN_X, VAR_X), ret_col)), ~replace_na(., 0))) %>%
    filter(!is.na(.data[[ret_col]])) %>%
    filter(complete.cases(.))

  cat("[INFO] Sample size:", nrow(tmp), "\n")
  cat("[INFO] Counts: D_report=", sum(tmp$D_report),
      " D_gdp=", sum(tmp$D_gdp),
      " D_policy=", sum(tmp$D_policy), "\n")

  y <- 100 * tmp[[ret_col]]                 # 与姜富伟一致：把收益率放大 100
  y_xts <- xts(y, order.by = tmp$date)

  X_mean <- as.matrix(tmp[, MEAN_X, drop = FALSE])
  X_var  <- as.matrix(tmp[, VAR_X,  drop = FALSE])

  spec <- ugarchspec(
    variance.model = list(
      model = "eGARCH",
      garchOrder = c(1, 1),
      external.regressors = X_var
    ),
    mean.model = list(
      armaOrder = c(1, 0),       # AR(1)
      include.mean = TRUE,
      external.regressors = X_mean
    ),
    distribution.model = "std"
  )

  fit <- ugarchfit(spec = spec, data = y_xts, solver = "hybrid")

  tone_tag <- tone_col_local
  tone_tag <- gsub("^Tone", "", tone_tag)
  tone_tag <- gsub("Event_raw$|Event_z$|_raw$|_z$", "", tone_tag)
  tone_tag <- gsub("[^A-Za-z0-9]+", "", tone_tag)

  out_file <- paste0("egarch_result_", ret_col, "_", tone_tag, "_jiang_roberta_all_",
                     if (USE_RAW_TONE) "raw" else "z",
                     "_", if (USE_POLICY_SURPRISE) "surprise" else "sim",
                     "_no_rate.txt")

  sink(out_file)
  cat("Jiang-style eGARCH(1,1)-X (NO short rate control)\n")
  cat("Index:", ret_col, "\n")
  cat("Tone:", tone_col_local, "\n")
  cat("Var text:", sim_col, "\n\n")
  cat("Mean regressors:\n"); print(MEAN_X)
  cat("\nVariance regressors:\n"); print(VAR_X)
  cat("\n\n--- Fit ---\n")
  show(fit)
  sink()

  cat("[OK] Saved:", out_file, "\n")
  return(fit)
}

# 5) 循环估计 ----------------------------------------------------------------
index_list <- c("SH", "SZ", "HS300", "CSI500")
fits <- list()

for (idx in index_list) {
  fits[[idx]] <- list()
  for (tc in TONE_COLS) {
    if (!(tc %in% colnames(df))) {
      cat("[WARN] tone col not found, skip:", tc, "
")
      next
    }
    fits[[idx]][[tc]] <- run_egarch_for_index(df, idx, tc)
  }
}

cat("\n[INFO] Done.\n")
