# EGARCH diagnostics and standardization checks
suppressPackageStartupMessages({
  library(readr); library(dplyr); library(xts); library(rugarch); library(tseries)
})

DATA_FILE <- "egarch_daily_data_roberta.csv"
INDICES <- c("SH","SZ","HS300","CSI500")
MEAN_COLS <- c("S_gdp","S_policy","tone_p90_policy_z")
VAR_COLS  <- c("D_report","Readability","Similarity")

# helper from run_egarch.r
build_xreg <- function(df, cols){
  miss <- cols[!cols %in% colnames(df)]
  if (length(miss) > 0){ stop(paste0("Missing required columns in dataset: ", paste(miss, collapse=", "))) }
  X <- as.matrix(df[, cols]); colnames(X) <- cols; return(X)
}

drop_bad_xcols <- function(X, tag){
  if (is.null(X) || ncol(X) == 0) return(list(X = X, dropped = character(0)))
  keep <- rep(TRUE, ncol(X)); reasons <- rep("", ncol(X))
  for (j in seq_len(ncol(X))){ x <- X[,j]; if (!all(is.finite(x))){ keep[j] <- FALSE; reasons[j] <- "non-finite"; next } ; s <- sd(x); if (is.na(s) || s==0){ keep[j] <- FALSE; reasons[j] <- "zero-variance"; next }}
  dropped <- colnames(X)[!keep]
  return(list(X = X[, keep, drop=FALSE], dropped = dropped))
}

fit_and_diagnose <- function(sub, ycol, label){
  Xmean <- build_xreg(sub, MEAN_COLS)
  Xvar  <- build_xreg(sub, VAR_COLS)
  dm <- drop_bad_xcols(Xmean, "mean"); dv <- drop_bad_xcols(Xvar, "variance")
  Xmean2 <- dm$X; Xvar2 <- dv$X
  y_xts <- xts(sub[[ycol]], order.by = as.Date(sub$date))

  spec <- ugarchspec(variance.model=list(model="eGARCH", garchOrder=c(1,1), external.regressors = Xvar2),
                     mean.model=list(armaOrder=c(0,0), include.mean=TRUE, external.regressors = Xmean2),
                     distribution.model = "std")
  fit <- tryCatch(ugarchfit(spec=spec, data=y_xts, solver='hybrid'), error=function(e) NULL)
  out <- list(fit=fit)
  if (!is.null(fit)){
    res_std <- residuals(fit, standardize=TRUE)
    # Ljung-Box on standardized residuals
    lb <- tryCatch(Box.test(res_std, lag=10, type='Ljung-Box'), error=function(e) NULL)
    arch <- tryCatch(ArchTest(res_std, lags=5), error=function(e) NULL)
    showout <- capture.output(show(fit))
    out$lb <- lb; out$arch <- arch; out$show <- showout
    # extract coef table (robust if available)
    mat <- tryCatch(fit@fit$robust.matcoef, error=function(e) NULL)
    if (is.null(mat)) mat <- tryCatch(fit@fit$matcoef, error=function(e) NULL)
    out$matcoef <- mat
  }
  return(out)
}

# load data
df <- read.csv(DATA_FILE, stringsAsFactors = FALSE)
df$date <- as.Date(df$date)

results <- list()
for (idx in INDICES){
  cat('Running diagnostics for', idx, '\n')
  sub <- df[, c('date', idx, MEAN_COLS, VAR_COLS)]
  sub <- sub %>% mutate(across(-date, as.numeric)) %>% filter(!is.na(.data[[idx]]))
  # replace non-finite xregs with 0
  for (c in c(MEAN_COLS, VAR_COLS)){
    sub[[c]][!is.finite(sub[[c]])] <- 0
    sub[[c]][is.na(sub[[c]])] <- 0
  }
  results[[idx]] <- fit_and_diagnose(sub, idx, idx)
}

# Now refit with standardized mean regressors (z-score) to check significance
results_z <- list()
for (idx in INDICES){
  cat('Refitting with standardized regressors for', idx, '\n')
  sub <- df[, c('date', idx, MEAN_COLS, VAR_COLS)]
  sub <- sub %>% mutate(across(-date, as.numeric)) %>% filter(!is.na(.data[[idx]]))
  for (c in c(MEAN_COLS, VAR_COLS)){
    sub[[c]][!is.finite(sub[[c]])] <- 0
    sub[[c]][is.na(sub[[c]])] <- 0
  }
  # standardize mean regressors only
  for (c in MEAN_COLS){ sub[[c]] <- scale(sub[[c]]) }
  # leave variance regressors as-is (but could standardize if desired)
  results_z[[idx]] <- fit_and_diagnose(sub, idx, paste0(idx,'_z'))
}

saveRDS(results, file='egarch_diagnostics_results.rds')
saveRDS(results_z, file='egarch_diagnostics_results_z.rds')

# Summarize key p-values and flags
summary_df <- data.frame(Index=character(), LB_p=numeric(), ARCH_p=numeric(), Tone_coef=numeric(), Tone_p=numeric(), Tone_coef_z=numeric(), Tone_p_z=numeric(), stringsAsFactors=FALSE)
for (idx in INDICES){
  r <- results[[idx]]
  r2 <- results_z[[idx]]
  lbp <- if(!is.null(r$lb)) round(r$lb$p.value,4) else NA
  archp <- if(!is.null(r$arch)) round(r$arch$p.value,4) else NA
  tone_coef <- NA; tone_p <- NA; tone_coef_z <- NA; tone_p_z <- NA
  # safe extraction helper
  safe_extract <- function(mat){
    if (is.null(mat)) return(list(coef=NA, p=NA))
    res <- list(coef=NA, p=NA)
    try({
      rown <- rownames(mat)
      if ('mxreg3' %in% rown){
        res$coef <- as.numeric(mat['mxreg3','Estimate']); res$p <- as.numeric(mat['mxreg3','Pr(>|t|)'])
      } else {
        mxrows <- grep('^mxreg', rown, value=TRUE)
        if (length(mxrows) >= 3){
          rn <- mxrows[3]
          res$coef <- as.numeric(mat[rn,'Estimate']); res$p <- as.numeric(mat[rn,'Pr(>|t|)'])
        }
      }
    }, silent=TRUE)
    return(res)
  }
  e1 <- safe_extract(r$matcoef)
  tone_coef <- e1$coef; tone_p <- e1$p
  e2 <- safe_extract(r2$matcoef)
  tone_coef_z <- e2$coef; tone_p_z <- e2$p
  summary_df <- rbind(summary_df, data.frame(Index=idx, LB_p=lbp, ARCH_p=archp, Tone_coef=tone_coef, Tone_p=tone_p, Tone_coef_z=tone_coef_z, Tone_p_z=tone_p_z, stringsAsFactors=FALSE))
}
write.csv(summary_df, 'egarch_diagnostics_summary.csv', row.names=FALSE)
cat('\nDiagnostics summary saved to egarch_diagnostics_summary.csv\n')

EOF