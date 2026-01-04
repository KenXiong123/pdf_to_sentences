# EGARCH Analysis - Complete Results Index & Guide

**Analysis Date**: January 4, 2025  
**Status**: ✅ COMPLETED (Options A+D)  
**Data Period**: January 4, 2017 - October 31, 2024 (n=4,680 trading days)

---

## 📁 OUTPUT FILES SUMMARY

### 🎯 Primary Results (For Thesis)

#### **1. egarch_diagnostics_comprehensive_final.csv** ⭐
**Purpose**: Main results table with all diagnostics  
**Rows**: 4 (one per index: SH, SZ, HS300, CSI500)  
**Columns**: 11 (tone effect, p-values, residual tests, stability tests)

**Quick interpretation**:
- Tone_Significant_5pct: TRUE = significant effect
- LB_Autocorr_Alert: TRUE = residual autocorrelation problem  
- Nyblom_Unstable_1pct: TRUE = parameter instability problem
- ARCH_test_p: < 0.05 = unexplained variance clustering

**Key findings**:
```
SH:      Tone SIGNIFICANT (p=0.028, negative) but parameters unstable (Nyblom=19.2)
SZ:      Tone NOT significant (p=0.632), residual autocorrelation (LB p=0.009), unstable params
HS300:   Tone NOT significant (p=0.632), residual autocorrelation (LB p=0.005), severe instability
CSI500:  Tone NOT significant (p=0.637), residual autocorrelation (LB p=0.037), unstable params
```

#### **2. EGARCH_RESULTS_SUMMARY_A_D.md** ⭐
**Purpose**: Comprehensive analysis report (1,400+ words)  
**Sections**:
- Executive Summary
- Key Findings (significance table + diagnostics)
- Root Cause Analysis (why tone not significant)
- Recommendations (5 short-term + 5 long-term)
- Final Assessment with confidence ratings
- Files Generated

**Best for**: Thesis discussion section, identifying next steps

#### **3. QUICK_REFERENCE_GUIDE.md** ⭐
**Purpose**: One-page interpretation guide  
**Sections**:
- Quick interpretation for each index
- Diagnostic checklist (5 key questions)
- What next? (4 actionable improvements)
- Expected vs observed results table

**Best for**: Quick lookup, understanding individual index results

---

### 📊 Detailed EGARCH Output Files

#### **4-7. egarch_result_[INDEX]_roberta_r.txt**
Four files (one per index):
- `egarch_result_SH_roberta_r.txt` (4.0 KB)
- `egarch_result_SZ_roberta_r.txt` (4.1 KB)
- `egarch_result_HS300_roberta_r.txt` (4.1 KB)
- `egarch_result_CSI500_roberta_r.txt` (4.2 KB)

**Contents of each file**:
1. **ARMA Selection Table**: Which ARMA order was chosen (BIC criterion)
2. **Model Specification**: EGARCH(1,1), distribution (Student-t)
3. **Optimal Parameters** (ML estimates): All 12 coefficients
4. **Robust Standard Errors**: HC-adjusted SE for all parameters
5. **Ljung-Box Test**: Residual autocorrelation (should be p > 0.05)
6. **ARCH LM Tests**: Heteroskedasticity in variance (should be p > 0.05)
7. **Nyblom Stability Test**: Parameter stability (should be stat < 3.51)
8. **Sign Bias Test**: Asymmetric GARCH response
9. **Adjusted Pearson Goodness-of-Fit**: Model fit quality

**How to read**:
- Look for `mxreg3` coefficient (policy tone effect)
- Check p-value in Robust Standard Errors section
- Scan Ljung-Box p-value (want p > 0.05)
- Find Nyblom Joint Statistic (want < 3.51)

**Example (from SH)**:
```
mxreg3 -0.010775    0.004908 -2.19540 0.028135    ← Tone coef = -0.0108, p = 0.0281 ✓ SIG
Ljung-Box: Lag[1] stat=0.0003, p-value=0.9870    ← No autocorr ✓ GOOD
Nyblom:    Joint Statistic: 19.2376               ← Unstable (>3.51) ⚠ PROBLEM
```

---

### 📈 Input Data & Scripts

#### **8. egarch_daily_data_roberta.csv**
**Purpose**: Panel dataset used for all regressions  
**Rows**: 4,680 (daily observations)  
**Columns**: 23 (date, 4 index returns, sentiment, shocks, controls)

**Key variables**:
- `date`: Trading date
- `SH`, `SZ`, `HS300`, `CSI500`: Log returns (%)
- `tone_p90_policy_z`: Policy sentiment (z-scored, quarterly)
- `tone_p90_macro_z`, `tone_p90_all_z`: Macro & overall sentiment
- `S_gdp`, `S_policy`: GDP and policy shocks (0/1 or value)
- `D_report`: Policy report dummy
- `Readability`, `Similarity`: Text complexity metrics
- Macro controls: SHIBOR, CNY/USD, repo rates, etc.

#### **9. run_egarch.r**
**Purpose**: Master EGARCH fitting script  
**Key Parameters**:
- `INDICES <- c("SH","SZ","HS300","CSI500")`
- `MEAN_COLS <- c("S_gdp","S_policy","tone_p90_policy_z")`
- `VAR_COLS <- c("D_report","Readability","Similarity")`
- `STANDARDIZE_MEAN <- FALSE` (set TRUE to z-score mean regressors)

**To modify**:
- Add lags: Extend `MEAN_COLS` with lagged variables
- Change ARMA: Modify `spec.mean.list$armaOrder` grid
- Add variance regressors: Update `VAR_COLS`
- Turn on standardization: Set `STANDARDIZE_MEAN <- TRUE`

**Run command**:
```bash
cd /Users/kenxiong/Desktop/硕士毕业论文/code/scripts
Rscript run_egarch.r
```

#### **10. egarch_final_diagnostics.r**
**Purpose**: Extract all results + generate diagnostic summary  
**Generates**: `egarch_diagnostics_comprehensive_final.csv` + console output

**Run command**:
```bash
Rscript egarch_final_diagnostics.r
```

#### **11. local_projection.r**
**Purpose**: Impulse response analysis (tone → returns over 12-day horizon)  
**Generates**: `LP_Robust_Results_Final.png` (2×2 grid of IRF plots)

**Status**: ✅ Working correctly (previous session)

---

### 🔧 Diagnostic & Analysis Scripts

#### **12. egarch_extract_results_final_v2.r**
**Purpose**: Alternative extraction script with fallback logic  
**Outputs**: Same as egarch_final_diagnostics.r

#### **13. egarch_bootstrap_and_diagnostics_v2.r**
**Purpose**: Attempted bootstrap analysis (v2, with fallback to text parsing)  
**Status**: ⚠️ ugarchboot parameter mismatch prevented bootstrap
**Fallback**: Used robust SE from ML estimation instead

---

## 🎯 HOW TO USE THESE FILES

### For Thesis Writing

**Step 1**: Read QUICK_REFERENCE_GUIDE.md (5 min)  
→ Understand what each diagnostic means

**Step 2**: Review egarch_diagnostics_comprehensive_final.csv (2 min)  
→ See all 4 indices' results at a glance

**Step 3**: Read EGARCH_RESULTS_SUMMARY_A_D.md (15 min)  
→ Deep dive into findings, root causes, recommendations

**Step 4** (if needed): Inspect egarch_result_[INDEX]_roberta_r.txt (10 min each)  
→ Check individual coefficient tables and test statistics

---

### For Improving the Model

**Problem**: 3/4 indices show tone not significant  
**Solution Path**:

1. **Check current model specification**:
   ```bash
   grep "ARMA used:" egarch_result_*.txt
   # Current: ARMA(0,0) for all indices
   ```

2. **Edit run_egarch.r to use ARMA(1,1)**:
   - Find line: `arma.grid <- expand.grid(p = 0:2, q = 0:1)`
   - Add: `arma.grid <- arma.grid %>% filter(!(p==0 & q==0))`
   - Or: Manually set `c(1,1)` in the spec

3. **Rerun EGARCH**:
   ```bash
   Rscript run_egarch.r
   Rscript egarch_final_diagnostics.r
   ```

4. **Check Ljung-Box results**:
   - If LB p-value > 0.05 for all indices → autocorrelation fixed ✓
   - Tone p-values may change → reinterpret

5. **Test alternative tone measures**:
   - Try `tone_p90_all_z` instead of `tone_p90_policy_z`
   - Or add `tone_p90_policy_z_lag1` (lagged tone)
   - Edit `MEAN_COLS` in run_egarch.r

---

## ⚠️ KEY FINDINGS SUMMARY

### Tone Coefficient Significance
| Index | Coef | p-value | Significant? |
|-------|------|---------|------------|
| SH | -0.0108 | 0.0281 | ✓ YES |
| SZ | +0.0130 | 0.6322 | ✗ NO |
| HS300 | +0.0109 | 0.6321 | ✗ NO |
| CSI500 | +0.0199 | 0.6367 | ✗ NO |

### Model Quality Issues
| Index | LB Autocorr | Nyblom Unstable | ARCH Effects |
|-------|-----------|-----------------|-------------|
| SH | ✓ OK | ⚠ YES | ✓ OK |
| SZ | ⚠ YES | ⚠ YES | ⚠ YES |
| HS300 | ⚠ YES | ⚠ YES | ✓ OK |
| CSI500 | ⚠ YES | ⚠ YES | ⚠ YES |

### Interpretation
- **Tone effect weak/inconsistent** across indices
- **Model misspecification** (ARMA(0,0) insufficient)
- **Parameter instability** (all indices show Nyblom > 3.51)
- **Residual autocorrelation** (3/4 indices affected)

### Recommendation
**DO NOT conclude "tone has no effect" yet.** Instead:
1. Fix ARMA specification (use ARMA(1,1))
2. Address parameter instability (rolling window or regime-switching)
3. Retest with corrected model

---

## 📞 Troubleshooting

### "Ljung-Box p-value is very small (< 0.05) for my index"
**Meaning**: Residuals are autocorrelated  
**Cause**: ARMA(0,0) too simple for daily stock returns  
**Solution**: Increase to ARMA(1,1) or ARMA(1,0), refit

### "All Nyblom statistics > 3.51 (parameter instability)"
**Meaning**: Model coefficients change over 2017-2024  
**Cause**: Possible structural breaks (COVID, policy changes)  
**Solution**: Use rolling 250-day window or Markov regime-switching

### "Tone coefficient p-value is not significant (p > 0.05)"
**Meaning**: Cannot reject H0 that tone has no effect  
**Not necessarily**: Tone truly has no effect  
**Alternatives**: 
- Model misspecification (fix ARMA first)
- Wrong sentiment measure (try other tone variables)
- Weak identification (tone correlated with other shocks)

### "How do I run the analysis again?"
```bash
cd /Users/kenxiong/Desktop/硕士毕业论文/code/scripts
Rscript run_egarch.r           # Generate new egarch_result_*.txt files
Rscript egarch_final_diagnostics.r  # Extract results to CSV
```

---

## 📋 Deliverables Checklist

- ✅ EGARCH regression (4 indices): egarch_result_[INDEX]_roberta_r.txt
- ✅ Comprehensive diagnostics table: egarch_diagnostics_comprehensive_final.csv
- ✅ Full analysis report: EGARCH_RESULTS_SUMMARY_A_D.md
- ✅ Quick reference guide: QUICK_REFERENCE_GUIDE.md
- ✅ Extraction script: egarch_final_diagnostics.r
- ✅ R EGARCH master script: run_egarch.r
- ✅ Input data: egarch_daily_data_roberta.csv

---

## 🔗 Related Files

- **Local Projections**: `local_projection.r` + `LP_Robust_Results_Final.png`
- **Previous iteration**: `egarch_result_[INDEX]_Final_Report.txt` (archival)
- **NLP processing**: `build_roberta_tone.py`, `build_variance_indicators.py`
- **Data orchestration**: `make_final_dataset.py`

---

**Last Updated**: 2025-01-04  
**Next Steps**: Implement ARMA(1,1) specification + rolling-window diagnostics  
**Contact**: For questions on model specification, see EGARCH_RESULTS_SUMMARY_A_D.md Recommendations section
