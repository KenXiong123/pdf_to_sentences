# egarch_extract_results_final_v2.r
# Purpose: Extract coefficient estimates & diagnostics from EGARCH output files

suppressPackageStartupMessages({
  library(readr); library(dplyr)
})

INDICES <- c("SH","SZ","HS300","CSI500")

cat("\n========== EXTRACTING COMPREHENSIVE RESULTS FROM EGARCH OUTPUTS ==========\n\n")

# Function to extract robust coefficient and p-value
extract_robust_coef <- function(result_file, param_name){
  if (!file.exists(result_file)) return(list(coef = NA, pval = NA))
  
  lines <- readLines(result_file)
  
  # Find "Robust Standard Errors:" section
  robust_idx <- grep("Robust Standard Errors:", lines)
  if (length(robust_idx) == 0) return(list(coef = NA, pval = NA))
  
  start <- robust_idx[1] + 2
  end <- min(start + 20, length(lines))
  
  for (i in start:end){
    line <- lines[i]
    if (grepl(param_name, line)){
      parts <- strsplit(line, "\\s+")[[1]]
      parts <- parts[parts != ""]
      # Format: name estimate se t-value p-value
      if (length(parts) >= 5){
        coef_val <- suppressWarnings(as.numeric(parts[2]))
        pval <- suppressWarnings(as.numeric(parts[5]))
        return(list(coef = coef_val, pval = pval))
      }
    }
  }
  return(list(coef = NA, pval = NA))
}

# Function to extract test p-values
extract_test_pval <- function(result_file, test_pattern, line_offset = 2){
  if (!file.exists(result_file)) return(NA)
  
  lines <- readLines(result_file)
  test_idx <- grep(test_pattern, lines)
  
  if (length(test_idx) == 0) return(NA)
  
  # Usually first result line is line_offset lines after header
  start <- test_idx[1] + line_offset
  if (start > length(lines)) return(NA)
  
  # Extract p-value from first result line
  for (i in start:(min(start + 3, length(lines)))){
    parts <- strsplit(lines[i], "\\s+")[[1]]
    parts <- parts[parts != ""]
    
    # Last field should be p-value
    if (length(parts) >= 2){
      pval_cand <- suppressWarnings(as.numeric(parts[length(parts)]))
      if (!is.na(pval_cand) && pval_cand >= 0 && pval_cand <= 1){
        return(pval_cand)
      }
    }
  }
  return(NA)
}

# Function to extract Nyblom joint statistic and critical value
extract_nyblom <- function(result_file){
  if (!file.exists(result_file)) return(list(stat = NA, cv_1pct = NA, unstable = NA))
  
  lines <- readLines(result_file)
  
  # Find "Joint Statistic:" line
  joint_idx <- grep("^Joint Statistic:", lines)
  if (length(joint_idx) == 0) return(list(stat = NA, cv_1pct = NA, unstable = NA))
  
  stat_line <- lines[joint_idx[1]]
  stat_parts <- strsplit(stat_line, ":")[[1]]
  if (length(stat_parts) < 2) return(list(stat = NA, cv_1pct = NA, unstable = NA))
  
  stat_val <- suppressWarnings(as.numeric(strsplit(stat_parts[2], "\\s+")[[1]][1]))
  
  # Find critical values (1%, 5%, 10%)
  cv_idx <- grep("Joint Statistic:.*\\(10% 5% 1%\\)", lines)
  if (length(cv_idx) == 0){
    # Try to find line with pattern like "2.69 2.96 3.51"
    cv_idx <- grep("\\s+2\\.6\\d+\\s+2\\.9\\d+\\s+3\\.5\\d+", lines)
  }
  
  cv_1pct <- NA
  if (length(cv_idx) > 0){
    cv_line <- lines[cv_idx[1]]
    cv_parts <- strsplit(cv_line, "\\s+")[[1]]
    cv_parts <- cv_parts[cv_parts != ""]
    if (length(cv_parts) >= 3){
      cv_1pct <- suppressWarnings(as.numeric(cv_parts[length(cv_parts)]))  # Last = 1%
    }
  }
  
  # Determine if unstable (stat > 1% critical value)
  unstable <- if (!is.na(stat_val) && !is.na(cv_1pct)) stat_val > cv_1pct else NA
  
  return(list(stat = stat_val, cv_1pct = cv_1pct, unstable = unstable))
}

# Main loop
results_list <- list()

for (idx in INDICES){
  cat("Processing", idx, "...\n")
  
  result_file <- paste0("egarch_result_", idx, "_roberta_r.txt")
  
  if (!file.exists(result_file)){
    cat("  [SKIP] File not found\n")
    results_list[[idx]] <- list(success = FALSE)
    next
  }
  
  # Extract tone coefficient and p-value (from robust standard errors)
  tone_robust <- extract_robust_coef(result_file, "mxreg3")
  tone_coef <- tone_robust$coef
  tone_pval <- tone_robust$pval
  
  # Extract diagnostic p-values
  lb_pval <- extract_test_pval(result_file, "Weighted Ljung-Box Test on Standardized Residuals", line_offset = 3)
  arch_pval <- extract_test_pval(result_file, "Weighted ARCH LM Tests", line_offset = 3)
  
  # Extract Nyblom stability test
  nyblom_info <- extract_nyblom(result_file)
  nyblom_stat <- nyblom_info$stat
  nyblom_unstable <- nyblom_info$unstable
  
  # Extract Sign Bias test (Joint Effect p-value)
  sign_bias_pval <- NA
  lines <- readLines(result_file)
  joint_effect_idx <- grep("Joint Effect", lines)
  if (length(joint_effect_idx) > 0){
    je_line <- lines[joint_effect_idx[1]]
    parts <- strsplit(je_line, "\\s+")[[1]]
    parts <- parts[parts != ""]
    if (length(parts) >= 2){
      sign_bias_pval <- suppressWarnings(as.numeric(parts[length(parts)]))
    }
  }
  
  # Extract Adjusted Pearson goodness-of-fit (group 20)
  apgf_pval <- NA
  apgf_idx <- grep("Adjusted Pearson Goodness-of-Fit Test", lines)
  if (length(apgf_idx) > 0){
    start <- apgf_idx[1] + 3  # Skip header lines
    if (start < length(lines)){
      parts <- strsplit(lines[start], "\\s+")[[1]]
      parts <- parts[parts != ""]
      if (length(parts) >= 3){
        apgf_pval <- suppressWarnings(as.numeric(parts[length(parts)]))
      }
    }
  }
  
  results_list[[idx]] <- list(
    success = TRUE,
    tone_coef = tone_coef,
    tone_pval = tone_pval,
    lb_pval = lb_pval,
    arch_pval = arch_pval,
    nyblom_stat = nyblom_stat,
    nyblom_unstable = nyblom_unstable,
    sign_bias_pval = sign_bias_pval,
    apgf_pval = apgf_pval
  )
  
  cat("  Tone (robust): coef =", format(tone_coef, digits=6),
      "| p-val =", format(tone_pval, digits=5),
      "| Ljung-Box p =", format(lb_pval, digits=5), "\n")
}

# Create results dataframe
results_df <- data.frame(
  Index = INDICES,
  Tone_Coef_Robust = sapply(results_list, function(x) if(x$success) x$tone_coef else NA),
  Tone_p_value = sapply(results_list, function(x) if(x$success) x$tone_pval else NA),
  Tone_Significant_5pct = sapply(results_list, function(x) if(x$success && !is.na(x$tone_pval)) x$tone_pval < 0.05 else NA),
  LB_test_p = sapply(results_list, function(x) if(x$success) x$lb_pval else NA),
  ARCH_test_p = sapply(results_list, function(x) if(x$success) x$arch_pval else NA),
  Nyblom_Stat = sapply(results_list, function(x) if(x$success) x$nyblom_stat else NA),
  Nyblom_Unstable_1pct = sapply(results_list, function(x) if(x$success) x$nyblom_unstable else NA),
  Sign_Bias_p = sapply(results_list, function(x) if(x$success) x$sign_bias_pval else NA),
  APGF_p = sapply(results_list, function(x) if(x$success) x$apgf_pval else NA)
)

write.csv(results_df, "egarch_results_comprehensive.csv", row.names = FALSE)

cat("\n\n========== FINAL COMPREHENSIVE RESULTS TABLE ==========\n\n")
print(results_df, digits = 5)

cat("\n\n========== INTERPRETATION NOTES ==========\n")
cat("Tone_Coef_Robust   : Robust coefficient estimate (using Sandwich SE)\n")
cat("Tone_p_value       : Robust p-value for H0: coef = 0 [*** p<0.001, **<0.01, *<0.05]\n")
cat("LB_test_p          : Ljung-Box residual autocorrelation [⚠ alert if < 0.05]\n")
cat("ARCH_test_p        : ARCH-LM heteroskedasticity test\n")
cat("Nyblom_Stat        : Stability test (critical value 1%=3.51, 5%=2.96, 10%=2.69)\n")
cat("Sign_Bias_p        : Asymmetric GARCH response test (joint effect)\n")
cat("APGF_p             : Goodness-of-fit test (group=20)\n\n")

cat("KEY FINDINGS:\n")
cat("────────────────────────────────────────────────────────────────\n")

# Count significant
n_sig <- sum(results_df$Tone_p_value < 0.05, na.rm = TRUE)
cat("(1) Tone Significance: ", n_sig, "/4 indices have tone_p90_policy_z significant at 5%\n")

# Ljung-Box assessment
lb_problems <- sum(results_df$LB_test_p < 0.05, na.rm = TRUE)
cat("(2) Residual Autocorrelation: ", lb_problems, "/4 indices show significant autocorr (LB p<0.05)\n")

# Nyblom assessment
nyblom_problems <- sum(results_df$Nyblom_Unstable_1pct, na.rm = TRUE)
cat("(3) Parameter Stability: ", nyblom_problems, "/4 indices unstable (Nyblom stat > 3.51)\n\n")

cat("RECOMMENDATIONS:\n")
cat("────────────────────────────────────────────────────────────────\n")
if (n_sig == 0){
  cat("✗ Policy tone has NO statistical significance across any index.\n")
  cat("  → Consider: (a) higher ARMA order to capture dynamics,\n")
  cat("             (b) lag structure (tone[t-1], tone[t-2]),\n")
  cat("             (c) alternative sentiment measure (tone_p90_all_z),\n")
  cat("             (d) event window definition, or\n")
  cat("             (e) market regime identification (bull/bear/sideways).\n\n")
}

if (lb_problems > 0){
  cat("⚠ Residual autocorrelation persists in ", lb_problems, " index(es).\n")
  cat("  → Ljung-Box suggests ARMA(0,0) may be too simple.\n")
  cat("    Try ARMA(1,1) or add lags of returns/shocks to mean equation.\n\n")
}

if (nyblom_problems > 0){
  cat("⚠ Parameter paths unstable in ", nyblom_problems, " index(es).\n")
  cat("  → Consider rolling-window or structural break testing.\n\n")
}

cat("────────────────────────────────────────────────────────────────\n")
cat("✅ Results saved to: egarch_results_comprehensive.csv\n\n")
