# run_egarch.r
# eGARCH-X（对齐姜富伟框架）+ 文本变量两种模式（all / split）
# 说明：
# - 本脚本只使用新列名：tone_p90_policy_z, tone_p90_macro_z, tone_p90_all_z, Similarity, Readability
# - ARMA 自动选阶：先用 ARMA(+X) 的 BIC 选 (p,q)，再固定阶数拟合 EGARCH-X（比“多次 EGARCH 拟合挑阶”稳定）

library(readr)
library(dplyr)
library(xts)
library(rugarch)

DATA_FILE <- "egarch_daily_data_roberta.csv"

OUT_SH    <- "egarch_result_SH_roberta_r.txt"
OUT_SZ    <- "egarch_result_SZ_roberta_r.txt"
OUT_HS300 <- "egarch_result_HS300_roberta_r.txt"
OUT_CSI500<- "egarch_result_CSI500_roberta_r.txt"

# ================== 配置区 ==================
# 文本变量模式：
# - "all"  : S_gdp + S_policy + tone_p90_all_z
# - "split": S_gdp + S_policy + tone_p90_policy_z + tone_p90_macro_z
TEXT_MODE <- "split"

# ARMA 阶数选择：
# - "fixed": 使用 FIXED_ARMA
# - "auto" : 用 ARMA(含xreg) 的 BIC 选阶
ARMA_MODE <- "auto"
FIXED_ARMA <- c(1, 0)

ARMA_CANDIDATES <- list(
  c(0,0), c(1,0), c(1,1), c(2,0), c(2,1), c(0,1)
)

# 分布：t
DIST_MODEL <- "std"
# ===========================================

drop_bad_xcols <- function(X, tag){
  if (is.null(X) || ncol(X) == 0) {
    return(list(X = X, dropped = character(0)))
  }
  keep <- rep(TRUE, ncol(X))
  reasons <- rep("", ncol(X))

  for (j in seq_len(ncol(X))){
    x <- X[, j]
    if (!all(is.finite(x))) {
      keep[j] <- FALSE
      reasons[j] <- "non-finite"
      next
    }
    s <- sd(x)
    if (is.na(s) || s == 0) {
      keep[j] <- FALSE
      reasons[j] <- "zero-variance"
      next
    }
  }

  dropped <- colnames(X)[!keep]
  if (length(dropped) > 0){
    cat("[WARN] Dropping", tag, "external regressors with zero-variance/non-finite:\n")
    for (j in which(!keep)){
      x <- X[, j]
      nnz <- sum(x != 0)
      nu  <- length(unique(x))
      s   <- sd(x)
      cat(" -", colnames(X)[j], "(", reasons[j], ", nonzero=", nnz, ", uniq=", nu, ", sd=", format(s, digits=6), ")\n")
    }
  }
  return(list(X = X[, keep, drop=FALSE], dropped = dropped))
}

build_xreg <- function(df, cols){
  miss <- cols[!cols %in% colnames(df)]
  if (length(miss) > 0){
    stop(paste0("Missing required columns in dataset: ", paste(miss, collapse=", ")))
  }
  X <- as.matrix(df[, cols])
  colnames(X) <- cols
  return(X)
}

fit_egarch <- function(y_xts, Xmean, Xvar, armaOrder){
  spec <- ugarchspec(
    variance.model = list(
      model = "eGARCH",
      garchOrder = c(1,1),
      external.regressors = Xvar
    ),
    mean.model = list(
      armaOrder = armaOrder,
      include.mean = TRUE,
      external.regressors = Xmean
    ),
    distribution.model = DIST_MODEL
  )
  fit <- tryCatch(
    ugarchfit(spec = spec, data = y_xts, solver = "hybrid"),
    error = function(e) NULL
  )
  return(fit)
}

select_arma_by_bic_arima <- function(y_vec, Xmean){
  n <- length(y_vec)
  res <- data.frame(p = integer(0), q = integer(0), bic = numeric(0), aic = numeric(0), ok = logical(0))
  best_bic <- Inf
  best_ord <- c(1,0)

  for (ord in ARMA_CANDIDATES){
    p <- ord[1]; q <- ord[2]
    fit <- tryCatch(
      stats::arima(y_vec, order = c(p,0,q), xreg = Xmean, include.mean = TRUE, method = "CSS-ML"),
      error = function(e) NULL
    )
    if (is.null(fit) || !is.finite(fit$loglik)){
      res <- rbind(res, data.frame(p=p, q=q, bic=NA, aic=NA, ok=FALSE))
      next
    }
    k <- length(fit$coef)
    aic <- -2*fit$loglik + 2*k
    bic <- -2*fit$loglik + log(n)*k
    ok <- is.finite(bic)
    res <- rbind(res, data.frame(p=p, q=q, bic=bic, aic=aic, ok=ok))
    if (ok && bic < best_bic){
      best_bic <- bic
      best_ord <- c(p,q)
    }
  }
  return(list(order = best_ord, table = res))
}

run_one_index <- function(df, ycol, out_file){
  cat("============================================================\n")
  cat("Index:", ycol, "\n")
  cat("TEXT_MODE:", TEXT_MODE, " | ARMA_MODE:", ARMA_MODE, "\n")

  if (TEXT_MODE == "all"){
    mean_cols <- c("S_gdp", "S_policy", "tone_p90_all_z")
  } else if (TEXT_MODE == "split"){
    mean_cols <- c("S_gdp", "S_policy", "tone_p90_policy_z", "tone_p90_macro_z")
  } else {
    stop("TEXT_MODE must be 'all' or 'split'")
  }
  var_cols <- c("D_gdp", "D_policy", "D_report", "Readability", "Similarity")

  required_cols <- c("date", ycol, mean_cols, var_cols)
  missing <- setdiff(required_cols, colnames(df))
  if (length(missing) > 0){
    stop(paste0("Dataset missing required columns: ", paste(missing, collapse=", ")))
  }

  sub <- df[, c("date", ycol, mean_cols, var_cols)]
  sub <- sub %>% mutate(across(-date, as.numeric))
  sub <- sub %>% filter(!is.na(.data[[ycol]]))

  # xreg 缺失 -> 0
  for (c in c(mean_cols, var_cols)){
    sub[[c]] <- ifelse(is.finite(sub[[c]]), sub[[c]], 0)
    sub[[c]][is.na(sub[[c]])] <- 0
  }

  Xmean <- build_xreg(sub, mean_cols)
  Xvar  <- build_xreg(sub, var_cols)
  dm <- drop_bad_xcols(Xmean, "mean")
  dv <- drop_bad_xcols(Xvar,  "variance")
  Xmean2 <- dm$X
  Xvar2  <- dv$X

  y_xts <- xts(sub[[ycol]], order.by = as.Date(sub$date))
  y_vec <- as.numeric(sub[[ycol]])

  arma_used <- FIXED_ARMA
  arma_table <- NULL
  if (ARMA_MODE == "fixed"){
    arma_used <- FIXED_ARMA
  } else if (ARMA_MODE == "auto"){
    sel <- select_arma_by_bic_arima(y_vec, Xmean2)
    arma_used <- sel$order
    arma_table <- sel$table
  } else {
    stop("ARMA_MODE must be 'fixed' or 'auto'")
  }

  fit <- fit_egarch(y_xts, Xmean2, Xvar2, arma_used)

  sink(out_file)
  cat("============================================================\n")
  cat("EGARCH-X results\n")
  cat("Index:", ycol, "\n")
  cat("TEXT_MODE:", TEXT_MODE, "\n")
  cat("ARMA_MODE:", ARMA_MODE, "\n")
  cat("ARMA used:", arma_used[1], ",", arma_used[2], "\n")
  cat("Mean regressors used:", paste(colnames(Xmean2), collapse=", "), "\n")
  cat("Variance regressors used:", paste(colnames(Xvar2), collapse=", "), "\n")
  cat("============================================================\n\n")

  if (!is.null(arma_table)){
    cat("[ARMA candidate table] (BIC lower is better; selected based on ARMA+X regression)\n")
    print(arma_table)
    cat("\n")
  }

  if (is.null(fit)){
    cat("[ERROR] EGARCH-X failed to fit.\n")
    sink()
    return(NULL)
  }

  show(fit)
  sink()
  cat("✅ Saved:", out_file, "\n")
  return(fit)
}

df <- read_csv(DATA_FILE, show_col_types = FALSE) %>% as.data.frame()
if (!("date" %in% colnames(df))) stop("dataset missing 'date' column")
df$date <- as.Date(df$date)

invisible(run_one_index(df, "SH", OUT_SH))
invisible(run_one_index(df, "SZ", OUT_SZ))
invisible(run_one_index(df, "HS300", OUT_HS300))
invisible(run_one_index(df, "CSI500", OUT_CSI500))
