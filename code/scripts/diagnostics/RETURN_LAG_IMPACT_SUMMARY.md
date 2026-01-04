# RETURN_LAG_IMPACT_SUMMARY.md - Final Assessment of Return Lag Effect

## Executive Summary

**Testing return lag (r_{t-1}) in EGARCH mean equation with ARMA(2,1) specification**

Result: **❌ RETURN LAG DOES NOT SOLVE LJUNG-BOX AUTOCORRELATION**

---

## Detailed Results

### Ljung-Box P-Values Comparison

| Index | NO Return Lag | WITH Return Lag | Change | Status |
|-------|---|---|---|---|
| **SH** | 0.0263 | 0.0290 | ↑ +0.0027 | ✗ Still fails (p<0.05) |
| **SZ** | 0.0098 | 0.0092 | ↓ -0.0006 | ✗ Worse, still fails |
| **HS300** | 0.0114 | 0.0061 | ↓ -0.0053 | ✗ Worse, still fails |
| **CSI500** | 0.0351 | 0.0465 | ↑ +0.0114 | ✗ Still fails (p<0.05) |

**Key Finding**: 
- **0 out of 4** indices pass Ljung-Box with return lag
- **Max improvement**: CSI500 +0.0114 (still p=0.0465 < 0.05)
- **Worst case**: HS300 worsened by -0.0053
- **No cure**: Return lag addresses mean equation dynamics but NOT the core autocorrelation problem

---

## Technical Details

### What Was Tested

```r
# Configuration
TONE_VAR <- "tone_p90_all_z"     # General sentiment (alternative to policy-specific)
INCLUDE_RETURN_LAG <- TRUE         # Added r_{t-1} to MEAN_COLS
ARMA_ORDER <- c(2, 1)              # Fixed ARMA(2,1)
MEAN_COLS <- c("S_gdp", "S_policy", "tone_p90_all_z", "r_lag1")
VAR_COLS <- c("D_report", "Readability", "Similarity")
```

### Ljung-Box Test Interpretation

- **H0**: No serial correlation in standardized residuals
- **Rejection threshold**: p < 0.05 means autocorrelation present
- **Current result**: All 4 indices reject H0 (have autocorrelation)
- **Implication**: ARMA(2,1) + return lag insufficient to capture autocorrelation structure

---

## Why Return Lag Didn't Help

### Hypothesis 1: Missing AR Dynamics ❌
Return lag (r_{t-1}) captures momentum/reversion in mean returns, but:
- Ljung-Box still fails → autocorrelation in **residuals** not mean
- Problem is in ARMA specification, not return mean structure

### Hypothesis 2: Higher ARMA Order Needed ✅
The persistent autocorrelation suggests:
- ARMA(2,1) cannot fully absorb serial structure
- May need ARMA(3,0), ARMA(3,1), ARMA(4,1), or even ARMA(3,2)
- Return lag insufficient without proper ARMA order

### Hypothesis 3: Non-Linear Dynamics ⚠️
Return lag assumes linear momentum, but:
- Stock returns may have threshold effects, regime shifts
- Non-linear ARMA (NLARMA) might be required
- Or regime-switching model (separate dynamics for bull/bear periods)

### Hypothesis 4: Parameter Instability (HIGH PROBABILITY) 🎯
Nyblom stability test shows all 4 indices have instability > 3.51:
- SH Nyblom = 13.68 ⚠️⚠️⚠️
- SZ Nyblom = 4.47
- HS300 Nyblom = 4.59
- CSI500 Nyblom = 6.46

This suggests:
- **Structural breaks** in 2017-2024 period
- Constant coefficient EGARCH model is invalid
- Need rolling window or regime-switching approach

---

## Next Priority Actions

### Priority 1 (TODAY): ARMA Order Search ⚡
Test ARMA(p,q) configurations to find which passes Ljung-Box:
- ARMA(3,0) - pure AR(3)
- ARMA(3,1) - AR(3) + MA(1)
- ARMA(1,2) - lightweight MA
- ARMA(4,1) - very AR-heavy
- ARMA(5,0) - extreme AR

**Script**: `/code/scripts/run_arma_search.r`  
**Expected**: Find at least one order that passes for all 4 indices

### Priority 2 (IF ARMA FAILS): Rolling Window EGARCH
If no ARMA order solves it → parameter instability is root cause
- Use 250-day rolling windows
- Track tone coefficient over time
- Align with market/policy events (COVID, trade war, etc.)

**Script**: `/code/scripts/rolling_window_egarch.r`  
**Expected**: Visualize Nyblom instability pattern, understand timing

### Priority 3 (IF ROLLING WINDOW NEEDED): Regime-Switching Model
Explicitly model structural breaks with hidden states
- 2-state Markov-switching EGARCH
- Separate tone effects for bull vs bear regimes
- Potentially explains tone coefficient insignificance

### Priority 4 (FINAL): GJR-GARCH Alternative
If eGARCH with all above doesn't work:
- Switch from eGARCH to GJR-GARCH
- Captures asymmetric shock response
- May reduce ARCH effects

---

## Thesis Implications

### Current Situation
- **Null finding**: Tone coefficient NOT significant at 5% level
- **Root cause unclear**: Could be true null OR model misspecification
- **Parameter instability**: Nyblom > 3.51 suggests structural breaks
- **Autocorrelation**: Ljung-Box fails even with return lag

### If ARMA Search Succeeds
→ Problem was simply ARMA specification  
→ Use best ARMA order in final model  
→ Tone significance may improve  
→ Thesis: "PBOC sentiment affects volatility with [ARMA lag structure]"

### If ARMA Search Fails but Rolling Window Succeeds
→ Structural breaks are present  
→ Tone effect varies over time (stronger pre-2020? post-2020?)  
→ Thesis: "PBOC sentiment effect unstable; varies across regimes"

### If Both Fail
→ Fundamental model change needed (regime-switching, GJR-GARCH)  
→ Or accept null: PBOC tone doesn't affect stock volatility  
→ Thesis: "Monetary policy communication ineffective for market volatility"

---

## Timing

**ARMA Search Runtime**: ~5-10 minutes (10 orders × 4 indices)  
**Rolling Window Runtime**: ~20-30 minutes per index  
**Regime-Switching Setup**: 2-3 hours  

**Critical Path**:
- Run ARMA search NOW (waiting for results)
- If passes: Use best order, done
- If fails: Start rolling window (low risk check first)
- If rolling window confirms instability: Regime-switching last resort

---

## Files Generated

- `egarch_result_*_roberta_r_v2_toneatl.txt` - Return lag results (4 files)
- `arma_search_results.csv` - ARMA search results (upcoming)
- `run_arma_search.r` - Search script
- `run_arma_search_summary.txt` - Final recommendations (upcoming)

---

**Status**: ARMA search in progress. Return lag hypothesis rejected.  
**Next Check**: Monitor ARMA search completion in 10 minutes.
