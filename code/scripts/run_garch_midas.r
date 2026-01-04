# run_garch_midas.r
# GARCH-MIDAS (季度语气 tone_p90_policy_z) 示例
# 方差方程: h_t = omega + alpha * eps_{t-1}^2 + beta * h_{t-1} + theta * MIDAS(tone)

library(readr)
library(dplyr)
library(lubridate)
library(xts)
library(rugarch)

DAILY_FILE <- "egarch_daily_data_roberta.csv"
QUARTER_FILE <- "tone_by_quarter_roberta.csv"

OUT_SH    <- "garch_midas_SH_roberta_r.txt"
OUT_SZ    <- "garch_midas_SZ_roberta_r.txt"
OUT_HS300 <- "garch_midas_HS300_roberta_r.txt"
OUT_CSI500<- "garch_midas_CSI500_roberta_r.txt"

# MIDAS 配置
K_LAGS <- 8  # 使用过去 8 个季度
INIT_MIDAS_PAR <- c(0.0, 0.0) # nealmon 权重初始值

# 其他配置
ARMA_ORDER <- c(1, 0)
DIST_MODEL <- "std"

midas_weights <- function(k, par){
  j <- 0:(k - 1)
  w <- exp(par[1] * j + par[2] * j^2)
  w / sum(w)
}

build_midas_term <- function(q_index_daily, tone_q, weights){
  k <- length(weights)
  n <- length(q_index_daily)
  midas <- rep(NA_real_, n)

  for (i in seq_len(n)){
    q_idx <- q_index_daily[i]
    if (is.na(q_idx)) {
      next
    }
    lag_idx <- q_idx - 0:(k - 1)
    valid <- lag_idx >= 1
    if (!any(valid)) {
      next
    }
    tone_lags <- tone_q[lag_idx[valid]]
    w <- weights[valid]
    w <- w / sum(w)
    midas[i] <- sum(w * tone_lags)
  }
  midas
}

estimate_midas_params <- function(y, q_index_daily, tone_q, k){
  obj <- function(par){
    weights <- midas_weights(k, par)
    midas <- build_midas_term(q_index_daily, tone_q, weights)
    ok <- is.finite(y) & is.finite(midas)
    if (sum(ok) < 20) {
      return(Inf)
    }
    fit <- lm(y[ok] ~ midas[ok])
    sum(resid(fit)^2)
  }
  optim(par = INIT_MIDAS_PAR, fn = obj, method = "BFGS")
}

prepare_quarter_index <- function(quarter_df){
  quarter_df <- quarter_df %>%
    mutate(
      quarter_id = paste0(year, "Q", quarter)
    ) %>%
    arrange(year, quarter)

  quarter_df$q_index <- seq_len(nrow(quarter_df))
  quarter_df
}

prepare_daily_index <- function(daily_df){
  daily_df %>%
    mutate(
      quarter_id = paste0(year(date), "Q", quarter(date))
    )
}

run_one_index <- function(daily_df, quarter_df, ycol, out_file){
  cat("============================================================\n")
  cat("Index:", ycol, "\n")

  if (!all(c("date", ycol) %in% colnames(daily_df))){
    stop(paste0("Daily data missing required columns: date, ", ycol))
  }
  if (!("tone_p90_policy_z" %in% colnames(quarter_df))){
    stop("Quarter data missing tone_p90_policy_z")
  }

  daily_df <- daily_df %>%
    select(date, all_of(ycol)) %>%
    mutate(
      date = as.Date(date),
      ret = as.numeric(.data[[ycol]]),
      rv = ret^2
    ) %>%
    filter(!is.na(ret))

  quarter_df <- quarter_df %>%
    select(quarter_id, q_index, tone_p90_policy_z)

  daily_df <- prepare_daily_index(daily_df) %>%
    left_join(quarter_df, by = "quarter_id")

  tone_q <- quarter_df %>%
    arrange(q_index) %>%
    pull(tone_p90_policy_z) %>%
    as.numeric()

  q_index_daily <- daily_df$q_index

  opt <- estimate_midas_params(daily_df$rv, q_index_daily, tone_q, K_LAGS)
  midas_par <- opt$par
  midas_term <- build_midas_term(q_index_daily, tone_q, midas_weights(K_LAGS, midas_par))

  Xvar <- matrix(midas_term, ncol = 1)
  colnames(Xvar) <- "midas_tone"

  y_xts <- xts(daily_df$ret, order.by = daily_df$date)

  spec <- ugarchspec(
    variance.model = list(
      model = "sGARCH",
      garchOrder = c(1, 1),
      external.regressors = Xvar
    ),
    mean.model = list(
      armaOrder = ARMA_ORDER,
      include.mean = TRUE
    ),
    distribution.model = DIST_MODEL
  )

  fit <- tryCatch(
    ugarchfit(spec = spec, data = y_xts, solver = "hybrid"),
    error = function(e) NULL
  )

  sink(out_file)
  cat("============================================================\n")
  cat("GARCH-MIDAS results\n")
  cat("Index:", ycol, "\n")
  cat("Quarter tone: tone_p90_policy_z\n")
  cat("MIDAS lags:", K_LAGS, "\n")
  cat("MIDAS params (nealmon):", paste(round(midas_par, 6), collapse = ", "), "\n")
  cat("Variance regressor: midas_tone\n")
  cat("ARMA order:", ARMA_ORDER[1], ",", ARMA_ORDER[2], "\n")
  cat("============================================================\n\n")

  if (is.null(fit)){
    cat("[ERROR] GARCH-MIDAS failed to fit.\n")
    sink()
    return(NULL)
  }

  show(fit)
  sink()
  cat("✅ Saved:", out_file, "\n")
  return(fit)
}

quarter_df <- read_csv(QUARTER_FILE, show_col_types = FALSE) %>% as.data.frame()
quarter_df <- prepare_quarter_index(quarter_df)

daily_df <- read_csv(DAILY_FILE, show_col_types = FALSE) %>% as.data.frame()
if (!("date" %in% colnames(daily_df))) stop("dataset missing 'date' column")

daily_df$date <- as.Date(daily_df$date)

invisible(run_one_index(daily_df, quarter_df, "SH", OUT_SH))
invisible(run_one_index(daily_df, quarter_df, "SZ", OUT_SZ))
invisible(run_one_index(daily_df, quarter_df, "HS300", OUT_HS300))
invisible(run_one_index(daily_df, quarter_df, "CSI500", OUT_CSI500))
