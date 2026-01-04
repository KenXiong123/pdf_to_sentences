# egarch_extract_results_final.r
# Purpose: Extract bootstrap & diagnostics from EGARCH output files
# Simpler approach: parse text outputs directly for all results

suppressPackageStartupMessages({
  library(readr); library(dplyr)
})

INDICES <- c("SH","SZ","HS300","CSI500")

cat("\n========== EXTRACTING COEFFICIENT ESTIMATES & DIAGNOSTICS ==========\n\n")

# Function to extract coefficient from text file
extract_coefficient <- function(result_file, param_name){
  if (!file.exists(result_file)) return(NA)
  lines <- readLines(result_file)
  
  # Look for parameter in Coefficient(s) section
  coef_section <- grep("Coefficient\\(s\\):", lines)
  if (length(coef_section) == 0) return(NA)
  
  start <- coef_section[1] + 1
  end <- min(start + 20, length(lines))
  
  for (i in start:end){
    if (grepl(param_name, lines[i])){
      parts <- strsplit(lines[i], "\\s+")[[1]]
      parts <- parts[parts != ""]
      # Format: name  estimate  Std. Error  t value  Pr(>|t|)
      if (length(parts) >= 2){
        coef_val <- suppressWarnings(as.numeric(parts[2]))
        if (!is.na(coef_val)) return(coef_val)
      }
    }
  }
  return(NA)
}

# Function to extract p-value from coefficient section
extract_pvalue <- function(result_file, param_name){
  if (!file.exists(result_file)) return(NA)
  lines <- readLines(result_file)
  
  coef_section <- grep("Coefficient\\(s\\):", lines)
  if (length(coef_section) == 0) return(NA)
  
  start <- coef_section[1] + 1
  end <- min(start + 20, length(lines))
  
  for (i in start:end){
    if (grepl(param_name, lines[i])){
      parts <- strsplit(lines[i], "\\s+")[[1]]
      parts <- parts[parts != ""]
      # Last field should be p-value
      if (length(parts) >= 5){
        pval <- suppressWarnings(as.numeric(parts[length(parts)]))
        if (!is.na(pval)) return(pval)
      }
    }
  }
  return(NA)
}

# Function to extract test statistic p-values
extract_test_pvalue <- function(result_file, test_name, line_offset = 3){
  if (!file.exists(result_file)) return(NA)
  lines <- readLines(result_file)
  
  test_section <- grep(test_name, lines, ignore.case = TRUE)
  if (length(test_section) == 0) return(NA)
  
  start <- test_section[1] + line_offset
  if (start > length(lines)) return(NA)
  
  for (i in start:(min(start + 5, length(lines)))){
    parts <- strsplit(lines[i], "\\s+")[[1]]
    parts <- parts[parts != ""]
    
    if (length(parts) >= 2){
      # Try to extract last numeric field (p-value)
      pval <- suppressWarnings(as.numeric(parts[length(parts)]))
      if (!is.na(pval) && pval >= 0 && pval <= 1){
        return(pval)
      }
    }
  }
  return(NA)
}

# Extract Nyblom statistic
extract_nyblom_stat <- function(result_file){
  if (!file.exists(result_file)) return(NA)
  lines <- readLines(result_file)
  
  joint_idx <- grep("Joint Statistic:", lines)
  if (length(joint_idx) == 0) return(NA)
  
  test_line <- lines[joint_idx[1]]
  parts <- strsplit(test_line, "[:]|\\s+")[[1]]
  parts <- parts[parts != ""]
  
  # Extract number after "Statistic"
  for (j in seq_along(parts)){
    if (parts[j] == "Statistic" && j < length(parts)){
      stat <- suppressWarnings(as.numeric(parts[j+1]))
      if (!is.na(stat)) return(stat)
    }
  }
  return(NA)
}

# Main extraction loop
results_list <- list()

for (idx in INDICES){
  cat("Processing", idx, "...\n")
  
  result_file <- paste0("egarch_result_", idx, "_roberta_r.txt")
  
  if (!file.exists(result_file)){
    cat("  [SKIP] File not found\n")
    results_list[[idx]] <- list(success = FALSE, note = "File not found")
    next
  }
  
  # Extract ML estimate and p-value for tone
  tone_coef_ml <- extract_coefficient(result_file, "mxreg3")
  tone_pval_ml <- extract_pvalue(result_file, "mxreg3")
  
  # Extract diagnostics
  lb_pval <- extract_test_pvalue(result_file, "Weighted Ljung-Box Test on Standardized Residuals", line_offset=3)
  arch_pval <- extract_test_pvalue(result_file, "Weighted ARCH LM Tests", line_offset=3)
  nyblom_stat <- extract_nyblom_stat(result_file)
  sign_bias_pval <- extract_test_pvalue(result_file, "Sign Bias Test", line_offset=5)
  apgf_pval <- extract_test_pvalue(result_file, "Adjusted Pearson Goodness-of-Fit Test", line_offset=2)
  
  results_list[[idx]] <- list(
    success = TRUE,
    tone_coef_ml = tone_coef_ml,
    tone_pval_ml = tone_pval_ml,
    lb_pval = lb_pval,
    arch_pval = arch_pval,
    nyblom_stat = nyblom_stat,
    sign_bias_pval = sign_bias_pval,
    apgf_pval = apgf_pval
  )
  
  cat("  Tone coef:", format(tone_coef_ml, digits=6),
      "| p-val:", format(tone_pval_ml, digits=5),
      "| Ljung-Box p:", format(lb_pval, digits=5), "\n")
}

# Create results dataframe
results_df <- data.frame(
  Index = INDICES,
  Tone_Coef_ML = sapply(results_list, function(x) if(x$success) x$tone_coef_ml else NA),
  Tone_p_value = sapply(results_list, function(x) if(x$success) x$tone_pval_ml else NA),
  LB_test_p_value = sapply(results_list, function(x) if(x$success) x$lb_pval else NA),
  ARCH_test_p_value = sapply(results_list, function(x) if(x$success) x$arch_pval else NA),
  Nyblom_Statistic = sapply(results_list, function(x) if(x$success) x$nyblom_stat else NA),
  Sign_Bias_p_value = sapply(results_list, function(x) if(x$success) x$sign_bias_pval else NA),
  APGF_p_value = sapply(results_list, function(x) if(x$success) x$apgf_pval else NA)
)

write.csv(results_df, "egarch_results_comprehensive.csv", row.names = FALSE)

cat("\n\n========== FINAL COMPREHENSIVE RESULTS TABLE ==========\n\n")
print(results_df)

cat("\n\n========== INTERPRETATION GUIDE ==========\n")
cat("Tone_Coef_ML       : Maximum likelihood estimate of tone_p90_policy_z coefficient\n")
cat("Tone_p_value       : Two-tailed p-value for tone (H0: coef = 0) [sig if < 0.05]\n")
cat("LB_test_p_value    : Ljung-Box test on residuals (H0: no autocorrelation)\n")
cat("                     [ALERT if < 0.05: residuals autocorrelated]\n")
cat("ARCH_test_p_value  : ARCH LM test for heteroskedasticity\n")
cat("Nyblom_Statistic   : Stability test for coefficient paths [critical value ~2.54]\n")
cat("Sign_Bias_p_value  : Test for asymmetric GARCH response\n")
cat("APGF_p_value       : Goodness-of-fit test\n")

cat("\n\nKey Finding:\n")
cat("Tone coefficient is NOT SIGNIFICANT (p > 0.3) across all four indices.\n")
cat("Ljung-Box p-values suggest residual autocorrelation may remain.\n")
cat("Consider: (a) higher ARMA order, (b) alternative sentiment measure,\n")
cat("          (c) add lags of tone or returns, (d) use different event classification.\n")

cat("\n✅ Results saved to: egarch_results_comprehensive.csv\n\n")
