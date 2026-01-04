# diagnose_return_lag_effect.r - Compare results WITH vs WITHOUT return lag
# Goal: Quantify if return lag (r_{t-1}) fixes Ljung-Box autocorrelation

suppressPackageStartupMessages({
  library(readr)
  library(dplyr)
})

# File pairs to compare:
# WITHOUT lag: egarch_result_*_roberta_r.txt (original ARMA(2,1))
# WITH lag:    egarch_result_*_roberta_r_v2_toneatl.txt (ARMA(2,1) + r_lag1)

files_without_lag <- c(
  SH = "egarch_result_SH_roberta_r.txt",
  SZ = "egarch_result_SZ_roberta_r.txt",
  HS300 = "egarch_result_HS300_roberta_r.txt",
  CSI500 = "egarch_result_CSI500_roberta_r.txt"
)

files_with_lag <- c(
  SH = "egarch_result_SH_roberta_r_v2_toneatl.txt",
  SZ = "egarch_result_SZ_roberta_r_v2_toneatl.txt",
  HS300 = "egarch_result_HS300_roberta_r_v2_toneatl.txt",
  CSI500 = "egarch_result_CSI500_roberta_r_v2_toneatl.txt"
)

# Helper: extract Ljung-Box p-value from output file
extract_ljung_box <- function(filepath) {
  tryCatch({
    lines <- readLines(filepath)
    idx <- grep("Weighted Ljung-Box Test on Standardized Residuals", lines, fixed = TRUE)
    if (length(idx) == 0) return(NA)
    # The p-value is typically on the 4th line after the header
    test_lines <- lines[(idx[1]+3):(idx[1]+6)]
    # Extract p-value from Lag[1] line
    lag1_line <- grep("Lag\\[1\\]", test_lines)
    if (length(lag1_line) > 0) {
      parts <- strsplit(test_lines[lag1_line], "\\s+")[[1]]
      pval <- as.numeric(parts[length(parts)])
      return(pval)
    }
    return(NA)
  }, error = function(e) NA)
}

# Helper: extract tone coefficient and p-value from robust SE section
extract_tone_coef <- function(filepath) {
  tryCatch({
    lines <- readLines(filepath)
    robust_idx <- grep("Robust Standard Errors:", lines, fixed = TRUE)
    if (length(robust_idx) == 0) return(list(coef = NA, pval = NA))
    
    # Look for mxreg3 line (tone_p90_all_z) in robust SE section
    robust_section <- lines[(robust_idx[1]+1):(robust_idx[1]+20)]
    tone_line <- grep("mxreg3", robust_section)
    
    if (length(tone_line) > 0) {
      parts <- strsplit(robust_section[tone_line], "\\s+")[[1]]
      parts <- parts[parts != ""]
      coef <- as.numeric(parts[2])
      pval <- as.numeric(parts[4])
      return(list(coef = coef, pval = pval))
    }
    return(list(coef = NA, pval = NA))
  }, error = function(e) list(coef = NA, pval = NA))
}

# Main comparison
cat("\n")
cat("═══════════════════════════════════════════════════════════════════════\n")
cat("RETURN LAG IMPACT ANALYSIS: ARMA(2,1) WITH vs WITHOUT r_{t-1}\n")
cat("═══════════════════════════════════════════════════════════════════════\n\n")

results <- data.frame(
  Index = names(files_without_lag),
  LB_NoLag = NA_real_,
  LB_WithLag = NA_real_,
  LB_Improvement = NA_character_,
  Tone_NoLag_pval = NA_real_,
  Tone_WithLag_pval = NA_real_,
  stringsAsFactors = FALSE
)

for (i in seq_along(files_without_lag)) {
  idx_name <- names(files_without_lag)[i]
  
  # Extract without lag
  lb_no <- extract_ljung_box(files_without_lag[i])
  tone_no <- extract_tone_coef(files_without_lag[i])
  
  # Extract with lag
  lb_yes <- extract_ljung_box(files_with_lag[i])
  tone_yes <- extract_tone_coef(files_with_lag[i])
  
  results[i, "LB_NoLag"] <- lb_no
  results[i, "LB_WithLag"] <- lb_yes
  results[i, "Tone_NoLag_pval"] <- tone_no$pval
  results[i, "Tone_WithLag_pval"] <- tone_yes$pval
  
  # Determine improvement
  if (!is.na(lb_no) && !is.na(lb_yes)) {
    if (lb_yes > lb_no) {
      improvement <- sprintf("✓ Improved (%.4f → %.4f)", lb_no, lb_yes)
    } else {
      improvement <- sprintf("✗ Worsened (%.4f → %.4f)", lb_no, lb_yes)
    }
    if (lb_yes > 0.05) {
      improvement <- paste0(improvement, " [PASS]")
    }
  } else {
    improvement <- "? (missing data)"
  }
  
  results[i, "LB_Improvement"] <- improvement
}

cat("LJUNG-BOX P-VALUES (Autocorrelation Test)\n")
cat("─────────────────────────────────────────────────────────────────────────\n")
for (i in 1:nrow(results)) {
  cat(sprintf("%8s: No Lag: %8.4f | With Lag: %8.4f | %s\n",
              results[i, "Index"],
              results[i, "LB_NoLag"],
              results[i, "LB_WithLag"],
              results[i, "LB_Improvement"]))
}

cat("\n")
cat("TONE COEFFICIENT P-VALUES (Policy Effect)\n")
cat("─────────────────────────────────────────────────────────────────────────\n")
for (i in 1:nrow(results)) {
  cat(sprintf("%8s: No Lag: %8.4f | With Lag: %8.4f",
              results[i, "Index"],
              results[i, "Tone_NoLag_pval"],
              results[i, "Tone_WithLag_pval"]))
  if (!is.na(results[i, "Tone_WithLag_pval"])) {
    if (results[i, "Tone_WithLag_pval"] < 0.05) {
      cat(" [✓ SIGNIFICANT]")
    }
  }
  cat("\n")
}

cat("\n")
cat("═══════════════════════════════════════════════════════════════════════\n")
cat("INTERPRETATION\n")
cat("═══════════════════════════════════════════════════════════════════════\n\n")

pass_count <- sum(results$LB_WithLag > 0.05, na.rm = TRUE)
cat(sprintf("✓ Indices with Ljung-Box p > 0.05 (no autocorrelation): %d/4\n", pass_count))

if (pass_count == 4) {
  cat("\n✅ RETURN LAG SOLVES THE PROBLEM!\n")
  cat("   → All indices pass Ljung-Box test\n")
  cat("   → Model specification is now adequate\n")
  cat("   → Proceed with return lag version for final analysis\n")
} else if (pass_count >= 2) {
  cat("\n⚠️  PARTIAL SUCCESS\n")
  cat("   → Some indices improve but not all pass Ljung-Box\n")
  cat("   → Consider higher ARMA orders or regime-switching next\n")
} else {
  cat("\n❌ RETURN LAG DOESN'T SOLVE THE PROBLEM\n")
  cat("   → Autocorrelation persists across all indices\n")
  cat("   → Need higher ARMA order or fundamental model change\n")
  cat("   → Priority: Rolling window + regime-switching models\n")
}

cat("\n")
cat("═══════════════════════════════════════════════════════════════════════\n")
