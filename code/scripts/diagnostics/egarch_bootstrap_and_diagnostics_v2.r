# egarch_bootstrap_and_diagnostics_v2.r
# Purpose: (A) Run bootstrap for tone coefficient significance
#          (D) Extract comprehensive diagnostics from text outputs
suppressPackageStartupMessages({
  library(readr); library(dplyr); library(xts); library(rugarch)
})

DATA_FILE <- "egarch_daily_data_roberta.csv"
INDICES <- c("SH","SZ","HS300","CSI500")
MEAN_COLS <- c("S_gdp","S_policy","tone_p90_policy_z")
VAR_COLS  <- c("D_report","Readability","Similarity")
N_BOOT <- 500  # Reduced for stability

# --- Helper functions ---
build_xreg <- function(df, cols){
  miss <- cols[!cols %in% colnames(df)]
  if (length(miss) > 0){ stop(paste0("Missing: ", paste(miss, collapse=", "))) }
  X <- as.matrix(df[, cols]); colnames(X) <- cols; return(X)
}

drop_bad_xcols <- function(X, tag){
  if (is.null(X) || ncol(X) == 0) return(list(X = X, dropped = character(0)))
  keep <- rep(TRUE, ncol(X))
  for (j in seq_len(ncol(X))){
    x <- X[, j]
    if (!all(is.finite(x))){ keep[j] <- FALSE; next }
    s <- sd(x); if (is.na(s) || s == 0){ keep[j] <- FALSE; next }
  }
  dropped <- colnames(X)[!keep]; return(list(X = X[, keep, drop=FALSE], dropped = dropped))
}

fit_egarch <- function(y_xts, Xmean, Xvar){
  spec <- ugarchspec(
    variance.model = list(model = "eGARCH", garchOrder = c(1,1), external.regressors = Xvar),
    mean.model = list(armaOrder = c(0,0), include.mean = TRUE, external.regressors = Xmean),
    distribution.model = "std"
  )
  fit <- tryCatch(ugarchfit(spec = spec, data = y_xts, solver = "hybrid"), error = function(e) NULL)
  return(fit)
}

cat("\n========== STEP A: BOOTSTRAP ANALYSIS (V2) ==========\n\n")

boot_results_list <- list()

for (idx in INDICES){
  cat("Bootstrap for", idx, "...\n")
  
  # Prepare data
  sub <- df <- read.csv(DATA_FILE, stringsAsFactors=FALSE)
  sub <- sub[, c("date", idx, MEAN_COLS, VAR_COLS)]
  sub <- sub %>% mutate(across(-date, as.numeric)) %>% filter(!is.na(.data[[idx]]))
  
  # Clean missing/infinite
  for (c in c(MEAN_COLS, VAR_COLS)){
    sub[[c]][!is.finite(sub[[c]])] <- 0; sub[[c]][is.na(sub[[c]])] <- 0
  }
  
  Xmean <- build_xreg(sub, MEAN_COLS)
  Xvar  <- build_xreg(sub, VAR_COLS)
  dm <- drop_bad_xcols(Xmean, "mean"); dv <- drop_bad_xcols(Xvar, "variance")
  Xmean2 <- dm$X; Xvar2  <- dv$X
  
  y_xts <- xts(sub[[idx]], order.by = as.Date(sub$date))
  
  # Fit base model
  fit <- fit_egarch(y_xts, Xmean2, Xvar2)
  
  if (is.null(fit)){
    cat("  [FAIL] Primary fit failed; trying simpler spec...\n")
    # Try without variance regressors
    spec_simple <- ugarchspec(
      variance.model = list(model = "eGARCH", garchOrder = c(1,1)),
      mean.model = list(armaOrder = c(0,0), include.mean = TRUE, external.regressors = Xmean2),
      distribution.model = "std"
    )
    fit <- tryCatch(ugarchfit(spec = spec_simple, data = y_xts, solver = "hybrid"), 
                    error = function(e) NULL)
    use_var_regs <- FALSE
  } else {
    use_var_regs <- TRUE
  }
  
  if (is.null(fit)){
    cat("  [FAIL] Even simple fit failed for", idx, "\n")
    boot_results_list[[idx]] <- list(success=FALSE, note="Fit failed")
    next
  }
  
  cat("  Fit OK. Attempting ugarchboot...\n")
  
  # Attempt bootstrap
  bres <- tryCatch({
    ugarchboot(fit, method = "Partial", n.ahead = 1, n.sim = N_BOOT, 
               n.bootfit = N_BOOT, parallel = FALSE, verbose = FALSE)
  }, error = function(e){
    cat("    Bootstrap error:", e$message, "\n")
    return(NULL)
  })
  
  if (is.null(bres)){
    cat("  [WARN] ugarchboot failed; extracting from text output instead...\n")
    
    # Parse result file for tone coefficient
    result_file <- paste0("egarch_result_", idx, "_roberta_r.txt")
    if (!file.exists(result_file)){
      boot_results_list[[idx]] <- list(success=FALSE, note="No result file")
      next
    }
    
    lines <- readLines(result_file)
    # Look for "mxreg3" coefficient line in Coefficient matrix
    coef_section <- grep("Coefficient\\(s\\):", lines)
    tone_coef <- NA
    if (length(coef_section) > 0){
      start <- coef_section[1]
      for (i in (start+1):(start+20)){
        if (i > length(lines)) break
        if (grepl("mxreg", lines[i]) && grepl("3", lines[i])){
          parts <- strsplit(lines[i], "\\s+")[[1]]
          parts <- parts[parts != ""]
          if (length(parts) >= 2) tone_coef <- as.numeric(parts[2])
          break
        }
      }
    }
    
    boot_results_list[[idx]] <- list(
      success = TRUE,
      note = "Extracted from text (no bootstrap)",
      tone_coef_orig = tone_coef,
      boot_pval = NA,
      boot_ci_lower = NA,
      boot_ci_upper = NA
    )
    cat("  Tone coef:", format(tone_coef, digits=6), "(from text output)\n")
    next
  }
  
  # Bootstrap succeeded; extract tone parameter
  pnames <- rownames(bres@sampled)
  tone_idx_name <- if ("mxreg3" %in% pnames) "mxreg3" else {
    mxregs <- grep("^mxreg", pnames, value = TRUE)
    if (length(mxregs) >= 3) mxregs[3] else NA
  }
  
  if (is.na(tone_idx_name)){
    cat("  [WARN] Could not locate tone parameter; fallback to text parsing\n")
    boot_results_list[[idx]] <- list(success=FALSE, note="Tone param not found in bootstrap")
    next
  }
  
  tone_samples <- as.numeric(bres@sampled[tone_idx_name, ])
  tone_samples <- tone_samples[!is.na(tone_samples)]
  
  if (length(tone_samples) == 0){
    cat("  [WARN] No valid tone bootstrap samples\n")
    boot_results_list[[idx]] <- list(success=FALSE, note="Empty tone samples")
    next
  }
  
  tone_coef_orig <- coef(fit)[tone_idx_name]
  
  # Two-tailed bootstrap p-value
  p_left  <- mean(tone_samples <= 0, na.rm=TRUE)
  p_right <- mean(tone_samples >= 0, na.rm=TRUE)
  boot_pval <- 2 * min(p_left, p_right)
  
  boot_ci_lower <- quantile(tone_samples, 0.025, na.rm=TRUE)
  boot_ci_upper <- quantile(tone_samples, 0.975, na.rm=TRUE)
  
  boot_results_list[[idx]] <- list(
    success = TRUE,
    note = "Bootstrap succeeded",
    tone_coef_orig = tone_coef_orig,
    boot_pval = boot_pval,
    boot_ci_lower = boot_ci_lower,
    boot_ci_upper = boot_ci_upper,
    boot_mean = mean(tone_samples, na.rm=TRUE),
    boot_sd = sd(tone_samples, na.rm=TRUE),
    n_boot_samples = length(tone_samples)
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
  Boot_SD = sapply(boot_results_list, function(x) if(x$success) x$boot_sd else NA),
  N_Boot_Samples = sapply(boot_results_list, function(x) if(x$success) x$n_boot_samples else NA),
  Note = sapply(boot_results_list, function(x) x$note)
)

write.csv(boot_df, "egarch_bootstrap_results.csv", row.names = FALSE)
cat("\n✅ Bootstrap results saved to: egarch_bootstrap_results.csv\n\n")

# ========== STEP D: EXTRACT DIAGNOSTICS FROM TEXT FILES ==========
cat("\n========== STEP D: DIAGNOSTICS SUMMARY FROM TEXT FILES ==========\n\n")

diag_list <- list()

for (idx in INDICES){
  cat("Extracting diagnostics for", idx, "...\n")
  
  result_file <- paste0("egarch_result_", idx, "_roberta_r.txt")
  if (!file.exists(result_file)){
    cat("  [WARN] Result file not found\n")
    diag_list[[idx]] <- list(success = FALSE)
    next
  }
  
  lines <- readLines(result_file)
  
  # 1. Ljung-Box test on standardized residuals
  lb_pval <- NA
  lb_section <- grep("Weighted Ljung-Box Test on Standardized Residuals", lines)
  if (length(lb_section) > 0){
    # Find the line with Lag[2] or first numeric result
    search_start <- lb_section[1] + 2
    for (i in search_start:(search_start + 5)){
      if (i > length(lines)) break
      if (grepl("Lag\\[", lines[i]) || (grepl("^\\s+[0-9]+\\s", lines[i]))){
        parts <- strsplit(lines[i], "\\s+")[[1]]
        parts <- parts[parts != ""]
        if (length(parts) >= 2){
          pval_idx <- length(parts)
          pval_candidate <- as.numeric(parts[pval_idx])
          if (!is.na(pval_candidate)){ lb_pval <- pval_candidate; break }
        }
      }
    }
  }
  
  # 2. ARCH LM test
  arch_pval <- NA
  arch_section <- grep("Weighted ARCH LM Tests", lines)
  if (length(arch_section) > 0){
    search_start <- arch_section[1] + 2
    for (i in search_start:(search_start + 5)){
      if (i > length(lines)) break
      if (grepl("^\\s+[0-9]+\\s", lines[i]) || grepl("Lag\\[", lines[i])){
        parts <- strsplit(lines[i], "\\s+")[[1]]
        parts <- parts[parts != ""]
        if (length(parts) >= 2){
          pval_candidate <- as.numeric(parts[length(parts)])
          if (!is.na(pval_candidate)){ arch_pval <- pval_candidate; break }
        }
      }
    }
  }
  
  # 3. Nyblom stability test
  nyblom_stat <- NA
  nyblom_joint_idx <- grep("Joint Statistic:", lines)
  if (length(nyblom_joint_idx) > 0){
    test_line <- lines[nyblom_joint_idx[1]]
    parts <- strsplit(test_line, ":")[[1]]
    if (length(parts) > 1){
      stat_part <- strsplit(parts[2], "\\s+")[[1]]
      stat_part <- stat_part[stat_part != ""]
      if (length(stat_part) > 0) nyblom_stat <- as.numeric(stat_part[1])
    }
  }
  
  # 4. Sign Bias test (summary)
  sign_bias_pval <- NA
  sign_idx <- grep("Sign Bias Test", lines)
  if (length(sign_idx) > 0){
    # Find "Joint Effect" line
    joint_effect_idx <- grep("Joint Effect", lines)
    if (length(joint_effect_idx) > 0 && joint_effect_idx[1] > sign_idx[1]){
      je_line <- lines[joint_effect_idx[1]]
      parts <- strsplit(je_line, "\\s+")[[1]]
      parts <- parts[parts != ""]
      if (length(parts) >= 2) sign_bias_pval <- as.numeric(parts[length(parts)])
    }
  }
  
  # 5. Adjusted Pearson Goodness-of-Fit
  apgf_pval <- NA
  apgf_idx <- grep("Adjusted Pearson Goodness-of-Fit Test", lines)
  if (length(apgf_idx) > 0){
    # Find the test statistic line (usually 2-3 lines down)
    search_start <- apgf_idx[1] + 2
    for (i in search_start:(search_start + 5)){
      if (i > length(lines)) break
      parts <- strsplit(lines[i], "\\s+")[[1]]
      parts <- parts[parts != ""]
      if (length(parts) >= 4 && !is.na(as.numeric(parts[length(parts)]))){
        apgf_pval <- as.numeric(parts[length(parts)])
        break
      }
    }
  }
  
  diag_list[[idx]] <- list(
    success = TRUE,
    lb_pval = lb_pval,
    arch_pval = arch_pval,
    nyblom_stat = nyblom_stat,
    sign_bias_pval = sign_bias_pval,
    apgf_pval = apgf_pval
  )
  
  cat("  LB p-val:", format(lb_pval, digits=4),
      "| ARCH p-val:", format(arch_pval, digits=4),
      "| Nyblom:", format(nyblom_stat, digits=5), "\n")
}

# Save diagnostics
diag_df <- data.frame(
  Index = INDICES,
  LB_p_value = sapply(diag_list, function(x) if(x$success) x$lb_pval else NA),
  ARCH_p_value = sapply(diag_list, function(x) if(x$success) x$arch_pval else NA),
  Nyblom_Statistic = sapply(diag_list, function(x) if(x$success) x$nyblom_stat else NA),
  Sign_Bias_p_value = sapply(diag_list, function(x) if(x$success) x$sign_bias_pval else NA),
  APGF_p_value = sapply(diag_list, function(x) if(x$success) x$apgf_pval else NA)
)

write.csv(diag_df, "egarch_diagnostics_final.csv", row.names = FALSE)
cat("\n✅ Diagnostics summary saved to: egarch_diagnostics_final.csv\n\n")

# --- Print final summary ---
cat("\n========== FINAL RESULTS SUMMARY ==========\n\n")
cat("Bootstrap Results (Tone Coefficient Significance):\n")
print(boot_df)

cat("\n\nDiagnostics Summary (Model Quality Indicators):\n")
print(diag_df)

cat("\n\n✅ Completed. Output files:\n")
cat("  [A] egarch_bootstrap_results.csv (tone bootstrap p-vals, 95% CIs)\n")
cat("  [D] egarch_diagnostics_final.csv (Ljung-Box, ARCH LM, Nyblom, Sign Bias, APGF)\n\n")
