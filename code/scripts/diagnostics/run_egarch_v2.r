# run_egarch_v2.r - EGARCH with alternative specifications
# Tests: (1) tone_p90_all_z instead of tone_p90_policy_z
#        (2) Lagged returns r_{t-1} in mean equation
#        (3) ARMA(2,1) for additional autocorrelation control

suppressPackageStartupMessages({
  library(readr)
  library(dplyr)
  library(xts)
  library(rugarch)
})

DATA_FILE <- "egarch_daily_data_roberta.csv"

OUT_SH     <- "egarch_result_SH_roberta_r_v2_toneatl.txt"
OUT_SZ     <- "egarch_result_SZ_roberta_r_v2_toneatl.txt"
OUT_HS300  <- "egarch_result_HS300_roberta_r_v2_toneatl.txt"
OUT_CSI500 <- "egarch_result_CSI500_roberta_r_v2_toneatl.txt"

# ================== CONFIG ==================
ARMA_MODE   <- "fixed"
FIXED_ARMA  <- c(2, 1)     # ARMA(2,1)
DIST_MODEL  <- "std"

# SPECIFICATION OPTIONS:
# Option 1: tone_p90_policy_z (policy-specific) - original
# Option 2: tone_p90_all_z (general sentiment) - testing here
# Option 3: Both (for comparison) - would need separate run
TONE_VAR <- "tone_p90_all_z"  # CHANGE TO TEST: "tone_p90_policy_z" or "tone_p90_all_z"

# Include lagged returns in mean equation? (tests momentum/reversion)
INCLUDE_RETURN_LAG <- TRUE  # Set to TRUE to test r_{t-1}

STANDARDIZE_MEAN <- FALSE
# ===========================================

# Build MEAN_COLS dynamically based on config
MEAN_COLS_BASE <- c("S_gdp", "S_policy", TONE_VAR)
MEAN_COLS <- if (INCLUDE_RETURN_LAG) c(MEAN_COLS_BASE, "r_lag1") else MEAN_COLS_BASE

VAR_COLS  <- c("D_report", "Readability", "Similarity")

cat("\n")
cat("════════════════════════════════════════════════════════════════\n")
cat("EGARCH-X V2: Alternative Specifications\n")
cat("════════════════════════════════════════════════════════════════\n")
cat("Tone variable:", TONE_VAR, "\n")
cat("Include return lag:", INCLUDE_RETURN_LAG, "\n")
cat("ARMA order:", FIXED_ARMA[1], ",", FIXED_ARMA[2], "\n")
cat("════════════════════════════════════════════════════════════════\n\n")

# --- helpers (same as original) ---
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

# --- main ---
df <- read.csv(DATA_FILE, stringsAsFactors = FALSE)
df$date <- as.Date(df$date)

# Create return lag if needed
if (INCLUDE_RETURN_LAG){
  for (idx in c("SH", "SZ", "HS300", "CSI500")){
    df[[paste0(idx, "_lag1")]] <- c(NA, df[[idx]][-nrow(df)])
  }
}

run_one_index <- function(df, ycol, tone_col, out_file){
  cat("Processing", ycol, "with", tone_col, "...\n")
  
  # Dynamic mean cols with correct tone variable
  if (INCLUDE_RETURN_LAG){
    mc <- c("S_gdp", "S_policy", tone_col, paste0(ycol, "_lag1"))
  } else {
    mc <- c("S_gdp", "S_policy", tone_col)
  }
  
  required_cols <- c("date", ycol, mc, VAR_COLS)
  missing <- setdiff(required_cols, colnames(df))
  if (length(missing) > 0){
    cat("[SKIP]", ycol, "- Missing:", paste(missing, collapse=", "), "\n")
    return(NULL)
  }

  sub <- df[, c("date", ycol, mc, VAR_COLS)]
  sub <- sub %>% mutate(across(-date, as.numeric)) %>% filter(!is.na(.data[[ycol]]))
  
  if (INCLUDE_RETURN_LAG){
    sub <- sub %>% filter(!is.na(.data[[paste0(ycol, "_lag1")]]))
  }

  # Standardize if requested
  if (STANDARDIZE_MEAN){
    sub <- sub %>% mutate(across(all_of(mc), ~ as.numeric(scale(.))))
  }

  # Fill NA/Inf -> 0
  for (c in c(mc, VAR_COLS)){
    if (c %in% colnames(sub)){
      sub[[c]] <- ifelse(is.finite(sub[[c]]), sub[[c]], 0)
      sub[[c]][is.na(sub[[c]])] <- 0
    }
  }

  Xmean <- build_xreg(sub, mc)
  Xvar  <- build_xreg(sub, VAR_COLS)

  dm <- drop_bad_xcols(Xmean, "mean")
  dv <- drop_bad_xcols(Xvar, "variance")
  Xmean2 <- dm$X
  Xvar2  <- dv$X

  y_xts <- xts(sub[[ycol]], order.by = as.Date(sub$date))
  
  fit <- fit_egarch(y_xts, Xmean2, Xvar2, FIXED_ARMA)
  
  if (is.null(fit)){
    cat("[FAIL] Could not fit", ycol, "\n")
    return(NULL)
  }
  
  # Save output
  sink(out_file)
  cat("============================================================\n")
  cat("EGARCH-X V2 Results\n")
  cat("Index:", ycol, "\n")
  cat("Tone variable:", tone_col, "\n")
  cat("Include return lag:", INCLUDE_RETURN_LAG, "\n")
  cat("ARMA order:", FIXED_ARMA[1], ",", FIXED_ARMA[2], "\n")
  cat("============================================================\n\n")
  print(fit)
  cat("\n============================================================\n")
  cat("END\n")
  sink()
  
  cat("  ✓ Saved:", out_file, "\n")
  return(fit)
}

# Run all four indices
run_one_index(df, "SH", TONE_VAR, OUT_SH)
run_one_index(df, "SZ", TONE_VAR, OUT_SZ)
run_one_index(df, "HS300", TONE_VAR, OUT_HS300)
run_one_index(df, "CSI500", TONE_VAR, OUT_CSI500)

cat("\n✅ V2 EGARCH run complete.\n")
cat("   Set TONE_VAR and INCLUDE_RETURN_LAG to test different specs.\n\n")
