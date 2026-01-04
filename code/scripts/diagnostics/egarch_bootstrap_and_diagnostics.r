# egarch_bootstrap_and_diagnostics.r
# Purpose: (A) Run bootstrap for tone coefficient significance
#          (D) Extract comprehensive diagnostics (Ljung-Box, ARCH LM, Nyblom, stability)
suppressPackageStartupMessages({
  library(readr); library(dplyr); library(xts); library(rugarch)
})

DATA_FILE <- "egarch_daily_data_roberta.csv"
INDICES <- c("SH","SZ","HS300","CSI500")
MEAN_COLS <- c("S_gdp","S_policy","tone_p90_policy_z")
VAR_COLS  <- c("D_report","Readability","Similarity")
N_BOOT <- 1000

# --- Helper functions from run_egarch.r ---
build_xreg <- function(df, cols){
  miss <- cols[!cols %in% colnames(df)]
  if (length(miss) > 0){ stop(paste0("Missing: ", paste(miss, collapse=", "))) }
  X <- as.matrix(df[, cols]); colnames(X) <- cols; return(X)
}

drop_bad_xcols <- function(X, tag){
  if (is.null(X) || ncol(X) == 0) return(list(X = X, dropped = character(0)))
  keep <- rep(TRUE, ncol(X)); reasons <- rep("", ncol(X))
  for (j in seq_len(ncol(X))){
    x <- X[, j]
    if (!all(is.finite(x))){ keep[j] <- FALSE; reasons[j] <- "non-finite"; next }
    s <- sd(x); if (is.na(s) || s == 0){ keep[j] <- FALSE; reasons[j] <- "zero-variance"; next }
  }
  dropped <- colnames(X)[!keep]; return(list(X = X[, keep, drop=FALSE], dropped = dropped))
}

fit_egarch_simple <- function(y_xts, Xmean, Xvar){
  spec <- ugarchspec(
    variance.model = list(model = "eGARCH", garchOrder = c(1,1), external.regressors = Xvar),
    mean.model = list(armaOrder = c(0,0), include.mean = TRUE, external.regressors = Xmean),
    distribution.model = "std"
  )
  fit <- tryCatch(ugarchfit(spec = spec, data = y_xts, solver = "hybrid"), error = function(e) NULL)
  return(fit)
}

# --- Load data and prep ---
df <- read.csv(DATA_FILE, stringsAsFactors = FALSE)
df$date <- as.Date(df$date)

cat("\n========== STEP A: BOOTSTRAP ANALYSIS ==========\n\n")

boot_results_list <- list()

for (idx in INDICES){
  cat("Bootstrap for", idx, "...\n")
  
  # Prepare data
  sub <- df[, c("date", idx, MEAN_COLS, VAR_COLS)]
  sub <- sub %>% mutate(across(-date, as.numeric)) %>% filter(!is.na(.data[[idx]]))
  for (c in c(MEAN_COLS, VAR_COLS)){
    sub[[c]][!is.finite(sub[[c]])] <- 0; sub[[c]][is.na(sub[[c]])] <- 0
  }
  
  Xmean <- build_xreg(sub, MEAN_COLS)
  Xvar  <- build_xreg(sub, VAR_COLS)
  dm <- drop_bad_xcols(Xmean, "mean"); dv <- drop_bad_xcols(Xvar, "variance")
  Xmean2 <- dm$X; Xvar2  <- dv$X
  
  y_xts <- xts(sub[[idx]], order.by = as.Date(sub$date))
  
  # Fit base model
  fit <- fit_egarch_simple(y_xts, Xmean2, Xvar2)
  
  if (is.null(fit)){
    cat("  [WARN] Fit failed for", idx, "\n")
    boot_results_list[[idx]] <- list(success=FALSE)
    next
  }
  
  # Bootstrap
  cat("  Running n.boot =", N_BOOT, "...\n")
  bres <- tryCatch(
    ugarchboot(fit, method = "Partial", n.ahead = 1, n.sim = N_BOOT, n.bootfit = N_BOOT, 
               parallel = FALSE, verbose = FALSE),
    error = function(e) NULL
  )
  
  if (is.null(bres)){
    cat("  [WARN] Bootstrap failed for", idx, "\n")
    boot_results_list[[idx]] <- list(success=FALSE)
    next
  }
  
  # Extract tone (mxreg3 = 3rd mean regressor = tone_p90_policy_z)
  # Bootstrap samples stored in bres@sampled matrix
  # Rows: parameters, Cols: bootstrap samples
  # We check the parameter name mapping
  pnames <- rownames(bres@sampled)
  tone_idx_name <- "mxreg3"
  if (!(tone_idx_name %in% pnames)){
    # Try to find the tone parameter
    mxregs <- grep("^mxreg", pnames, value = TRUE)
    if (length(mxregs) >= 3) tone_idx_name <- mxregs[3]
    else tone_idx_name <- NA
  }
  
  if (is.na(tone_idx_name)){
    cat("  [WARN] Could not locate tone parameter for", idx, "\n")
    boot_results_list[[idx]] <- list(success=FALSE)
    next
  }
  
  # Extract bootstrap samples for tone
  tone_samples <- as.numeric(bres@sampled[tone_idx_name, ])
  
  # Original estimate
  tone_coef_orig <- coef(fit)[tone_idx_name]
  
  # Bootstrap p-value: two-tailed test H0: coef = 0
  # p = 2 * min(mean(samples <= 0), mean(samples >= 0))
  p_left  <- mean(tone_samples <= 0, na.rm=TRUE)
  p_right <- mean(tone_samples >= 0, na.rm=TRUE)
  boot_pval <- 2 * min(p_left, p_right)
  
  # Bootstrap CI (95%)
  boot_ci_lower <- quantile(tone_samples, 0.025, na.rm=TRUE)
  boot_ci_upper <- quantile(tone_samples, 0.975, na.rm=TRUE)
  
  boot_results_list[[idx]] <- list(
    success = TRUE,
    tone_coef_orig = tone_coef_orig,
    boot_pval = boot_pval,
    boot_ci_lower = boot_ci_lower,
    boot_ci_upper = boot_ci_upper,
    boot_mean = mean(tone_samples, na.rm=TRUE),
    boot_sd = sd(tone_samples, na.rm=TRUE)
  )
  
  cat("  Tone coef:", format(tone_coef_orig, digits=6), 
      "| Bootstrap p-val:", format(boot_pval, digits=4),
      "| 95% CI: [", format(boot_ci_lower, digits=5), ",", format(boot_ci_upper, digits=5), "]\n")
}

# Save bootstrap results
boot_df <- data.frame(
  Index = INDICES,
  Tone_Coef = sapply(boot_results_list, function(x) if(x$success) x$tone_coef_orig else NA),
  Boot_p_value = sapply(boot_results_list, function(x) if(x$success) x$boot_pval else NA),
  Boot_CI_Lower = sapply(boot_results_list, function(x) if(x$success) x$boot_ci_lower else NA),
  Boot_CI_Upper = sapply(boot_results_list, function(x) if(x$success) x$boot_ci_upper else NA),
  Boot_Mean = sapply(boot_results_list, function(x) if(x$success) x$boot_mean else NA),
  Boot_SD = sapply(boot_results_list, function(x) if(x$success) x$boot_sd else NA)
)

write.csv(boot_df, "egarch_bootstrap_results.csv", row.names = FALSE)
cat("\n✅ Bootstrap results saved to: egarch_bootstrap_results.csv\n")

cat("\n========== STEP D: DIAGNOSTICS SUMMARY ==========\n\n")

# Extract diagnostics from result files
diag_list <- list()

for (idx in INDICES){
  cat("Extracting diagnostics for", idx, "...\n")
  
  result_file <- paste0("egarch_result_", idx, "_roberta_r.txt")
  if (!file.exists(result_file)){
    cat("  [WARN] Result file not found:", result_file, "\n")
    diag_list[[idx]] <- list(success = FALSE)
    next
  }
  
  lines <- readLines(result_file)
  
  # Extract Ljung-Box test p-value (look for pattern "Lag\[1\].*p-value")
  lb_idx <- grep("Weighted Ljung-Box Test on Standardized Residuals", lines)
  lb_pval <- NA
  if (length(lb_idx) > 0){
    # Usually 2-3 lines below the header we find first test
    start <- lb_idx[1] + 3
    if (start < length(lines)){
      test_line <- lines[start]
      # Extract p-value (last column)
      parts <- strsplit(test_line, "\\s+")[[1]]
      parts <- parts[parts != ""]
      if (length(parts) >= 2) lb_pval <- as.numeric(parts[length(parts)])
    }
  }
  
  # Extract ARCH LM test p-value
  arch_idx <- grep("Weighted ARCH LM Tests", lines)
  arch_pval <- NA
  if (length(arch_idx) > 0){
    start <- arch_idx[1] + 3
    if (start < length(lines)){
      test_line <- lines[start]
      parts <- strsplit(test_line, "\\s+")[[1]]
      parts <- parts[parts != ""]
      if (length(parts) >= 2) arch_pval <- as.numeric(parts[length(parts)])
    }
  }
  
  # Extract Nyblom stability test (look for "Joint Statistic:")
  nyblom_idx <- grep("Nyblom stability test", lines)
  nyblom_stat <- NA; nyblom_cv_1pct <- NA
  if (length(nyblom_idx) > 0){
    # Find "Joint Statistic:"
    joint_idx <- grep("Joint Statistic:", lines)
    if (length(joint_idx) > 0){
      test_line <- lines[joint_idx[1]]
      parts <- strsplit(test_line, ":")[[1]]
      if (length(parts) > 1) nyblom_stat <- as.numeric(strsplit(parts[2], "\\s+")[[1]][1])
    }
    # Find critical values: look for line with "Joint Statistic:"
    cv_idx <- grep("Joint Statistic:.*1%", lines)
    if (length(cv_idx) > 0){
      cv_line <- lines[cv_idx[1]]
      parts <- strsplit(cv_line, "\\s+")[[1]]
      parts <- parts[parts != ""]
      if (length(parts) >= 4) nyblom_cv_1pct <- as.numeric(parts[length(parts)])
    }
  }
  
  # Determine stability flag: if Nyblom stat > 1% critical value, unstable
  nyblom_unstable <- if (!is.na(nyblom_stat) && !is.na(nyblom_cv_1pct)) nyblom_stat > nyblom_cv_1pct else NA
  
  diag_list[[idx]] <- list(
    success = TRUE,
    lb_pval = lb_pval,
    arch_pval = arch_pval,
    nyblom_stat = nyblom_stat,
    nyblom_unstable = nyblom_unstable
  )
}

# Save diagnostics
diag_df <- data.frame(
  Index = INDICES,
  LB_p_value = sapply(diag_list, function(x) if(x$success) x$lb_pval else NA),
  ARCH_p_value = sapply(diag_list, function(x) if(x$success) x$arch_pval else NA),
  Nyblom_Statistic = sapply(diag_list, function(x) if(x$success) x$nyblom_stat else NA),
  Nyblom_Unstable_flag = sapply(diag_list, function(x) if(x$success) x$nyblom_unstable else NA)
)

write.csv(diag_df, "egarch_diagnostics_final.csv", row.names = FALSE)
cat("\n✅ Diagnostics summary saved to: egarch_diagnostics_final.csv\n")

# Print combined summary
cat("\n========== COMBINED RESULTS SUMMARY ==========\n")
cat("Bootstrap Significance (n.boot =", N_BOOT, "):\n")
print(boot_df)
cat("\nDiagnostics:\n")
print(diag_df)

cat("\n✅ All done. Files saved:\n")
cat("  - egarch_bootstrap_results.csv (tone coefficient bootstrap p-values & CIs)\n")
cat("  - egarch_diagnostics_final.csv (Ljung-Box, ARCH LM, Nyblom stability)\n\n")
