# run_egarch_arma_search.r - Systematic search for ARMA order that passes Ljung-Box
# Priority 1: Find ARMA specification eliminating residual autocorrelation
# Tests: ARMA(3,0), ARMA(1,2), ARMA(3,1) with return lag included

suppressPackageStartupMessages({
  library(readr)
  library(dplyr)
  library(xts)
  library(rugarch)
})

DATA_FILE <- "egarch_daily_data_roberta.csv"

# ================== CONFIG ==================
ARMA_ORDERS_TO_TEST <- list(
  c(3, 0),  # Pure AR(3)
  c(1, 2),  # MA(2) with AR(1)
  c(3, 1)   # AR(3) with MA(1)
)

TONE_VAR <- "tone_p90_policy_z"
INCLUDE_RETURN_LAG <- TRUE  # Keep return lag (economically significant)
DIST_MODEL <- "std"
STANDARDIZE_MEAN <- FALSE

MEAN_COLS_BASE <- c("S_gdp", "S_policy", TONE_VAR)
MEAN_COLS <- c(MEAN_COLS_BASE, "r_lag1")
VAR_COLS <- c("D_report", "Readability", "Similarity")

cat("\n")
cat("════════════════════════════════════════════════════════════════════════════\n")
cat("ARMA ORDER SEARCH: Testing ARMA(3,0), ARMA(1,2), ARMA(3,1)\n")
cat("════════════════════════════════════════════════════════════════════════════\n")
cat("Specification:\n")
cat("  Tone variable: tone_p90_policy_z (original)\n")
cat("  Return lag: TRUE (r_{t-1} included)\n")
cat("  Variance model: eGARCH(1,1) with Readability + Similarity + D_report\n")
cat("════════════════════════════════════════════════════════════════════════════\n\n")

# --- helpers (same as before) ---
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
    cat("[WARN] Dropping", tag, "external regressors:\n")
    for (j in which(!keep)){
      cat(" -", colnames(X)[j], "(", reasons[j], ")\n")
    }
  }
  return(list(X = X[, keep, drop=FALSE], dropped = dropped))
}

build_xreg <- function(df, cols){
  miss <- cols[!cols %in% colnames(df)]
  if (length(miss) > 0){
    stop(paste0("Missing columns: ", paste(miss, collapse=", ")))
  }
  X <- as.matrix(df[, cols])
  colnames(X) <- cols
  return(X)
}

fit_egarch <- function(y_xts, Xmean, Xvar, arma_order){
  spec <- ugarchspec(
    variance.model = list(model = "eGARCH", garchOrder = c(1,1), external.regressors = Xvar),
    mean.model = list(armaOrder = arma_order, include.mean = TRUE, external.regressors = Xmean),
    distribution.model = DIST_MODEL
  )
  fit <- tryCatch(
    ugarchfit(spec = spec, data = y_xts, solver = "hybrid", verbose = FALSE),
    error = function(e){
      cat("[FAIL]", e$message, "\n")
      return(NULL)
    }
  )
  return(fit)
}

extract_ljung_box_stat <- function(fit){
  tryCatch({
    test_stat <- as.numeric(fit@fit$fit$test.stat[1])
    test_pval <- as.numeric(fit@fit$fit$test.pval[1])
    return(list(stat = test_stat, pval = test_pval))
  }, error = function(e) list(stat = NA, pval = NA))
}

# --- main ---
df <- read.csv(DATA_FILE, stringsAsFactors = FALSE)
df$date <- as.Date(df$date)

# Create return lag
for (idx in c("SH", "SZ", "HS300", "CSI500")){
  df[[paste0(idx, "_lag1")]] <- c(NA, df[[idx]][-nrow(df)])
}

results_summary <- data.frame(
  Index = rep(c("SH", "SZ", "HS300", "CSI500"), length(ARMA_ORDERS_TO_TEST)),
  ARMA_p = rep(sapply(ARMA_ORDERS_TO_TEST, `[`, 1), each = 4),
  ARMA_q = rep(sapply(ARMA_ORDERS_TO_TEST, `[`, 2), each = 4),
  Ljung_Box_pval = NA_real_,
  Tone_pval = NA_real_,
  Converged = NA,
  stringsAsFactors = FALSE
)

result_idx <- 1

# Test each ARMA order
for (arma_idx in seq_along(ARMA_ORDERS_TO_TEST)){
  arma_order <- ARMA_ORDERS_TO_TEST[[arma_idx]]
  
  cat(sprintf("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"))
  cat(sprintf("TESTING ARMA(%d,%d)\n", arma_order[1], arma_order[2]))
  cat("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
  
  for (idx_name in c("SH", "SZ", "HS300", "CSI500")){
    start_time <- Sys.time()
    cat(sprintf("  Processing %s ...", idx_name))
    
    # Prepare data
    y <- df[[idx_name]]
    y_xts <- xts(y, order.by = df$date)
    
    # Build external regressors
    Xmean <- build_xreg(df, MEAN_COLS)
    Xvar <- build_xreg(df, VAR_COLS)
    Xvar_clean <- drop_bad_xcols(Xvar, "Variance")$X
    
    # Fit EGARCH
    fit <- fit_egarch(y_xts, Xmean, Xvar_clean, arma_order)
    
    if (!is.null(fit)){
      # Extract diagnostics
      lb_test <- extract_ljung_box_stat(fit)
      
      # Extract tone coefficient from robust SE
      tone_coef <- NA
      tone_pval <- NA
      tryCatch({
        coef_table <- fit@fit$robust.matcoef
        # mxreg3 is tone (S_gdp, S_policy, tone)
        if ("mxreg3" %in% rownames(coef_table)){
          tone_pval <- coef_table["mxreg3", "Pr(>|t|)"]
        }
      }, error = function(e) NULL)
      
      # Record results
      results_summary[result_idx, "Ljung_Box_pval"] <- lb_test$pval
      results_summary[result_idx, "Tone_pval"] <- tone_pval
      results_summary[result_idx, "Converged"] <- TRUE
      
      # Format output
      elapsed <- round(as.numeric(difftime(Sys.time(), start_time, units="secs")), 2)
      lb_status <- if (lb_test$pval > 0.05) "✓" else "✗"
      cat(sprintf(" %s LB p=%.4f Tone p=%.4f [%.1fs]\n", 
                  lb_status, lb_test$pval, tone_pval, elapsed))
    } else {
      cat(" ✗ FAILED TO CONVERGE\n")
      results_summary[result_idx, "Converged"] <- FALSE
    }
    
    result_idx <- result_idx + 1
  }
}

# Summary table
cat("\n")
cat("════════════════════════════════════════════════════════════════════════════\n")
cat("SUMMARY: LJUNG-BOX P-VALUES BY ARMA ORDER\n")
cat("════════════════════════════════════════════════════════════════════════════\n\n")

for (arma_idx in seq_along(ARMA_ORDERS_TO_TEST)){
  arma_order <- ARMA_ORDERS_TO_TEST[[arma_idx]]
  mask <- results_summary$ARMA_p == arma_order[1] & results_summary$ARMA_q == arma_order[2]
  subset <- results_summary[mask, ]
  
  cat(sprintf("ARMA(%d,%d):\n", arma_order[1], arma_order[2]))
  for (i in 1:nrow(subset)){
    idx <- subset[i, "Index"]
    pval <- subset[i, "Ljung_Box_pval"]
    status <- if (!is.na(pval) && pval > 0.05) "✓ PASS" else "✗ FAIL"
    cat(sprintf("  %8s: %.4f  %s\n", idx, pval, status))
  }
  cat("\n")
}

# Overall assessment
cat("════════════════════════════════════════════════════════════════════════════\n")
cat("ASSESSMENT\n")
cat("════════════════════════════════════════════════════════════════════════════\n\n")

for (arma_idx in seq_along(ARMA_ORDERS_TO_TEST)){
  arma_order <- ARMA_ORDERS_TO_TEST[[arma_idx]]
  mask <- results_summary$ARMA_p == arma_order[1] & results_summary$ARMA_q == arma_order[2]
  subset <- results_summary[mask, ]
  
  pass_count <- sum(subset$Ljung_Box_pval > 0.05, na.rm = TRUE)
  
  cat(sprintf("ARMA(%d,%d): %d/4 indices pass Ljung-Box (p > 0.05)\n", 
              arma_order[1], arma_order[2], pass_count))
  
  if (pass_count == 4){
    cat("  → ✅ CANDIDATE FOR FINAL MODEL\n")
  } else if (pass_count >= 2){
    cat("  → ⚠️  PARTIAL SUCCESS (some improvement)\n")
  } else {
    cat("  → ❌ NOT RECOMMENDED (all fail)\n")
  }
}

cat("\n")
cat("════════════════════════════════════════════════════════════════════════════\n")
cat("NEXT STEPS:\n")
cat("────────────────────────────────────────────────────────────────────────────\n")
cat("1. If one ARMA passes all 4 indices:\n")
cat("   → Use that as final specification\n")
cat("   → Run: modify run_egarch.r FIXED_ARMA, rerun EGARCH + LP analysis\n\n")
cat("2. If partial success (some indices pass):\n")
cat("   → Use index-specific ARMA in separate regressions\n")
cat("   → Document why different indices need different AR structure\n\n")
cat("3. If no ARMA order works:\n")
cat("   → Proceed to Priority 2: Rolling window EGARCH\n")
cat("   → Then Priority 3: Regime-switching EGARCH\n\n")
cat("════════════════════════════════════════════════════════════════════════════\n")
