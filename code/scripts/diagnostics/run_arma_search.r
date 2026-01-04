# run_arma_search.r - Systematic ARMA order search to fix Ljung-Box autocorrelation
# Strategy: Test multiple ARMA orders and find which one minimizes LB p-value violation
# Focus: Ljung-Box test on standardized residuals (currently failing 4/4 at ARMA(2,1))

suppressPackageStartupMessages({
  library(readr)
  library(dplyr)
  library(xts)
  library(rugarch)
})

DATA_FILE <- "egarch_daily_data_roberta.csv"

# Test configurations: (p, q) pairs to try
# Current (failing): ARMA(2,1) - all 4 indices Ljung-Box p < 0.05
# Strategy: Try higher orders that capture more AR/MA dynamics
ARMA_CONFIGS <- list(
  c(1, 1),   # Current base - often good compromise
  c(2, 1),   # Current - failing Ljung-Box
  c(2, 2),   # Higher MA order
  c(3, 0),   # Pure AR(3) - sometimes better than ARMA
  c(3, 1),   # AR(3) + MA(1)
  c(3, 2),   # Higher order
  c(1, 2),   # Alternative: MA-heavy
  c(1, 3),   # Very MA-heavy
  c(4, 1),   # Very AR-heavy
  c(5, 0)    # AR(5) pure
)

TONE_VAR <- "tone_p90_policy_z"
VAR_COLS <- c("D_report", "Readability", "Similarity")
DIST_MODEL <- "std"

# Indices to process
INDICES <- c("SH", "SZ", "HS300", "CSI500")

cat("\n")
cat("╔════════════════════════════════════════════════════════════════════════╗\n")
cat("║           ARMA ORDER SEARCH: Systematic Optimization                  ║\n")
cat("║  Goal: Find ARMA(p,q) that passes Ljung-Box test (p > 0.05)          ║\n")
cat("║  Current: ARMA(2,1) failing 4/4 indices at Ljung-Box                  ║\n")
cat("╚════════════════════════════════════════════════════════════════════════╝\n\n")

# Helper functions (same as original)
drop_bad_xcols <- function(X, tag){
  if (is.null(X) || ncol(X) == 0) {
    return(list(X = X, dropped = character(0)))
  }
  keep <- rep(TRUE, ncol(X))
  
  for (j in seq_len(ncol(X))){
    x <- X[, j]
    if (!all(is.finite(x))) {
      keep[j] <- FALSE
      next
    }
    s <- sd(x)
    if (is.na(s) || s == 0) {
      keep[j] <- FALSE
      next
    }
  }
  
  dropped <- colnames(X)[!keep]
  if (length(dropped) > 0){
    cat("[DROP]", tag, ":", paste(dropped, collapse=", "), "\n")
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

# Extract Ljung-Box p-value from fitted model
extract_ljung_box <- function(fit) {
  tryCatch({
    if (is.null(fit)) return(NA)
    # Get the model summary output as a string
    fit_output <- utils::capture.output(show(fit))
    # Find Ljung-Box test section
    lb_idx <- grep("Weighted Ljung-Box Test on Standardized Residuals", fit_output, fixed = TRUE)
    if (length(lb_idx) == 0) return(NA)
    # The p-value for Lag[1] is typically 4 lines after the header
    lag1_line <- fit_output[lb_idx[1] + 4]
    # Extract p-value (last number on line)
    parts <- as.numeric(strsplit(lag1_line, "\\s+")[[1]][c(2,3)])
    if (length(parts) >= 2 && !is.na(parts[2])) {
      return(parts[2])  # Return p-value (second number)
    }
    return(NA)
  }, error = function(e) NA)
}

fit_egarch <- function(y_xts, Xmean, Xvar, arma_order){
  spec <- ugarchspec(
    variance.model = list(model = "eGARCH", garchOrder = c(1,1), external.regressors = Xvar),
    mean.model = list(armaOrder = arma_order, include.mean = TRUE, external.regressors = Xmean),
    distribution.model = DIST_MODEL
  )
  fit <- tryCatch(
    ugarchfit(spec = spec, data = y_xts, solver = "hybrid", verbose = FALSE),
    error = function(e) NULL
  )
  return(fit)
}

# ═══ MAIN LOOP ═══
df <- read.csv(DATA_FILE, stringsAsFactors = FALSE)
df$date <- as.Date(df$date)

# Results storage
search_results <- data.frame()

for (idx_name in INDICES) {
  cat(sprintf("\n\n▶ Processing INDEX: %s\n", idx_name))
  cat(sprintf("  Testing %d ARMA configurations...\n\n", length(ARMA_CONFIGS)))
  
  y_col <- idx_name
  y_xts <- xts(df[[y_col]], order.by = df$date)
  
  # Prepare external regressors
  Xmean_base <- build_xreg(df, c(TONE_VAR, "S_gdp", "S_policy"))
  Xvar <- build_xreg(df, VAR_COLS)
  
  res_drop_mean <- drop_bad_xcols(Xmean_base, paste0("MEAN[", idx_name, "]"))
  Xmean <- res_drop_mean$X
  
  res_drop_var <- drop_bad_xcols(Xvar, paste0("VAR[", idx_name, "]"))
  Xvar <- res_drop_var$X
  
  idx_results <- data.frame()
  
  for (k in seq_along(ARMA_CONFIGS)) {
    arma_order <- ARMA_CONFIGS[[k]]
    arma_str <- sprintf("ARMA(%d,%d)", arma_order[1], arma_order[2])
    
    fit <- fit_egarch(y_xts, Xmean, Xvar, arma_order)
    
    if (is.null(fit)) {
      cat(sprintf("  %2d. %s ... ✗ FAILED TO CONVERGE\n", k, arma_str))
      idx_results <- rbind(idx_results, data.frame(
        Index = idx_name,
        ARMA_p = arma_order[1],
        ARMA_q = arma_order[2],
        ARMA_Order = arma_str,
        LB_pval = NA,
        Converged = FALSE,
        Pass_LB = FALSE,
        stringsAsFactors = FALSE
      ))
    } else {
      lb_p <- extract_ljung_box(fit)
      pass_lb <- if (is.na(lb_p)) FALSE else lb_p > 0.05
      
      status_icon <- if (pass_lb) "✓" else "✗"
      lb_str <- if (is.na(lb_p)) "NA" else sprintf("%.4f", lb_p)
      
      cat(sprintf("  %2d. %s ... LB p = %s %s\n", k, arma_str, lb_str, status_icon))
      
      idx_results <- rbind(idx_results, data.frame(
        Index = idx_name,
        ARMA_p = arma_order[1],
        ARMA_q = arma_order[2],
        ARMA_Order = arma_str,
        LB_pval = lb_p,
        Converged = TRUE,
        Pass_LB = pass_lb,
        stringsAsFactors = FALSE
      ))
    }
  }
  
  search_results <- rbind(search_results, idx_results)
}

# ═══ SUMMARY & RECOMMENDATION ═══
cat("\n\n")
cat("╔════════════════════════════════════════════════════════════════════════╗\n")
cat("║                        SEARCH RESULTS SUMMARY                         ║\n")
cat("╚════════════════════════════════════════════════════════════════════════╝\n\n")

# Group by index and show best performers
for (idx in INDICES) {
  idx_data <- filter(search_results, Index == idx)
  pass_count <- sum(idx_data$Pass_LB, na.rm = TRUE)
  
  cat(sprintf("%-8s: %d/%d configurations pass Ljung-Box (p > 0.05)\n", 
              idx, pass_count, nrow(idx_data)))
  
  if (pass_count > 0) {
    passing <- filter(idx_data, Pass_LB) %>% 
      arrange(LB_pval) %>% 
      slice(1:min(3, n()))
    
    cat("         Top performers:\n")
    for (i in 1:nrow(passing)) {
      cat(sprintf("           - %s: p = %.4f\n", passing$ARMA_Order[i], passing$LB_pval[i]))
    }
  }
  cat("\n")
}

cat("\n")
cat("╔════════════════════════════════════════════════════════════════════════╗\n")
cat("║                         RECOMMENDATION                                ║\n")
cat("╚════════════════════════════════════════════════════════════════════════╝\n\n")

# Count indices with at least one passing config
indices_with_solution <- search_results %>%
  filter(Pass_LB) %>%
  distinct(Index) %>%
  nrow()

if (indices_with_solution == 4) {
  cat("✅ SOLUTION FOUND: All 4 indices have passing ARMA orders!\n\n")
  
  # Find most common successful order
  best_overall <- search_results %>%
    filter(Pass_LB) %>%
    group_by(ARMA_Order) %>%
    summarise(n = n(), .groups = "drop") %>%
    arrange(desc(n)) %>%
    slice(1)
  
  cat(sprintf("   Recommended unified ARMA order: %s (works for %d indices)\n\n",
              best_overall$ARMA_Order[1], best_overall$n[1]))
  
  cat("   ➜ Next: Run final EGARCH with recommended ARMA order\n")
  cat("   ➜ Update run_egarch.r with FIXED_ARMA <- c(...)\n")
  
} else if (indices_with_solution > 0) {
  cat("⚠️  PARTIAL SUCCESS: Some indices have solutions, others don't\n\n")
  cat("   Indices without solution need different approach:\n")
  
  no_solution <- search_results %>%
    filter(!Pass_LB) %>%
    distinct(Index) %>%
    pull(Index)
  
  for (idx in no_solution) {
    cat(sprintf("     - %s: Try rolling window or regime-switching\n", idx))
  }
  
} else {
  cat("❌ NO SOLUTION FOUND: No ARMA order passes Ljung-Box for any index\n\n")
  cat("   This indicates fundamental model misspecification:\n")
  cat("   ➜ Parameter instability (Nyblom > 3.51) requires structural changes\n")
  cat("   ➜ Next Priority: Rolling window EGARCH (250-day windows)\n")
  cat("   ➜ Alternative: Regime-switching EGARCH model\n")
}

cat("\n")
cat("═══════════════════════════════════════════════════════════════════════════\n\n")

# Save full results to CSV for reference
write.csv(search_results, "arma_search_results.csv", row.names = FALSE)
cat("✓ Full results saved to: arma_search_results.csv\n")
