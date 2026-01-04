# EGARCH Results: Quick Reference Guide

## 📊 Main Result Table

**File**: `egarch_diagnostics_comprehensive_final.csv`

### What Each Column Means:

| Column | Definition | Interpretation |
|--------|-----------|-----------------|
| **Tone_Coef_Robust** | Policy tone coefficient (robust SE) | How much return changes per 1 std dev increase in tone |
| **Tone_p_value** | Robust p-value for H0: coef=0 | **< 0.05** = significant effect; **> 0.05** = no effect |
| **Tone_Significant_5pct** | TRUE if p < 0.05 | Quick significance flag |
| **LB_test_p** | Ljung-Box residual autocorr test | **> 0.05** = good (no autocorr); **< 0.05** = bad (autocorr present) |
| **LB_Autocorr_Alert** | TRUE if LB_test_p < 0.05 | Quick alert flag (TRUE = problem) |
| **ARCH_test_p** | ARCH LM heteroskedasticity test | **> 0.05** = good; **< 0.05** = variance clustering |
| **Nyblom_Statistic** | Parameter stability test | **< 3.51** = stable; **> 3.51** = unstable (1% level) |
| **Nyblom_Unstable_1pct** | TRUE if Nyblom > 3.51 | TRUE = parameters shift over time |

---

## 🎯 Quick Interpretation

### ✓ SH Index (Shanghai)
```
Tone_Coef_Robust:  -0.0108
Tone_p_value:       0.0281  ✓ SIGNIFICANT
LB_test_p:          0.987   ✓ GOOD (no autocorrelation)
Nyblom_Statistic:  19.2376  ⚠ UNSTABLE (coefficients shift)
ARCH_test_p:        0.913   ✓ GOOD (no heteroskedasticity)
```
**Interpretation**: 
- Policy tone **DOES** affect SH returns (p=0.028)
- **BUT** effect is **negative** (weird: higher tone → lower returns)
- Residuals are white noise (good)
- Model coefficients vary over 2017-2024 period (bad: regime change?)
- 1 std-dev ↑ in policy tone → 1.08% ↓ in returns

### ✗ SZ Index (Shenzhen)
```
Tone_Coef_Robust:   0.0130
Tone_p_value:       0.6322  ✗ NOT SIGNIFICANT
LB_test_p:          0.0085  ⚠ AUTOCORRELATION ALERT
Nyblom_Statistic:   3.9143  ⚠ UNSTABLE
ARCH_test_p:        0.0196  ⚠ ARCH EFFECTS PRESENT
```
**Interpretation**:
- Policy tone has **NO** effect on SZ returns (p=0.63 >> 0.05)
- **BUT** model has multiple problems:
  - Residuals are autocorrelated → ARMA(0,0) too simple
  - Unexplained variance clustering (ARCH effects)
  - Model coefficients unstable over time
- **Verdict**: Cannot trust tone p-value due to model misspecification

### ✗ HS300 Index (CSI 300)
```
Tone_Coef_Robust:   0.0109
Tone_p_value:       0.6321  ✗ NOT SIGNIFICANT
LB_test_p:          0.0050  ⚠ AUTOCORRELATION ALERT (severe)
Nyblom_Statistic:  17.1389  ⚠ SEVERE INSTABILITY
```
**Interpretation**:
- Policy tone: **NO** significant effect (p=0.632)
- Model fit: **POOR**
  - Strong residual autocorrelation (p=0.005)
  - Severe parameter instability (Nyblom=17.1)
- **Action needed**: Respecify with ARMA(1,1) or regime-switching

### ✗ CSI500 Index (CSI 500)
```
Tone_Coef_Robust:   0.0199
Tone_p_value:       0.6367  ✗ NOT SIGNIFICANT
LB_test_p:          0.0373  ⚠ AUTOCORRELATION ALERT
Nyblom_Statistic:   6.0380  ⚠ UNSTABLE
ARCH_test_p:        0.0170  ⚠ ARCH EFFECTS
```
**Interpretation**: Similar to SZ/HS300 - tone not significant, model problems with autocorrelation and instability.

---

## 🔍 Diagnostic Checklist

### For Each Index, Answer:

**Q1: Is tone significant?**  
→ Look at `Tone_p_value`. If **< 0.05**, YES. Otherwise NO.  
**Finding**: Only SH is significant (p=0.028).

**Q2: Are residuals white noise?**  
→ Look at `LB_Autocorr_Alert`. If **FALSE**, YES. If **TRUE**, NO (autocorrelation present).  
**Finding**: Only SH is clean. SZ/HS300/CSI500 have autocorrelation.

**Q3: Are model coefficients stable?**  
→ Look at `Nyblom_Unstable_1pct`. If **FALSE**, YES (stable). If **TRUE**, NO (unstable).  
**Finding**: ALL 4 indices unstable. Parameter paths shift over 2017-2024.

**Q4: Are there unexplained variance clusters?**  
→ Look at `ARCH_test_p`. If **> 0.05**, NO. If **< 0.05**, YES (variance clustering present).  
**Finding**: SH & HS300 OK. SZ & CSI500 show ARCH effects (variance clustering).

**Q5: Can we trust the results?**  
→ Need Q2=YES (white noise residuals), Q3=FALSE (stable params), Q4=NO (no ARCH).  
**Finding**: Only SH meets criteria (2/3). Others fail multiple tests → unreliable.

---

## ⚙️ What Next?

### If you want to improve the model:

1. **Increase ARMA order** (current = ARMA(0,0))
   - Try ARMA(1,1) to fix autocorrelation
   - Command: Edit `run_egarch.r`, change `c(0,0)` to `c(1,1)` in ARMA grid
   - Expected: Reduce Ljung-Box p for SZ/HS300/CSI500

2. **Add return lags** to mean equation
   - Include r_{t-1} as regressor
   - Or: Add lagged tone (tone_{t-1})
   - Expected: Capture momentum, reduce residual autocorr

3. **Use rolling-window estimates** 
   - Estimate separately for 2017-2019, 2020-2022, 2023-2024
   - Expected: Reveal if tone effect differs by market regime
   - Addresses Nyblom instability evidence

4. **Try regime-switching model**
   - Allows coefficients to change based on hidden state (e.g., bull/bear market)
   - Would directly handle Nyblom instability
   - More advanced: requires `MSwM` or `regswitch` packages in R

### If you want to publish as-is:

**Not recommended**, but if pressed, structure findings as:
- "Tone shows mixed significance: only SH index (p=0.028) with negative effect"
- "Model diagnostics (Ljung-Box, Nyblom) suggest ARMA(0,0) inadequate for SZ/HS300/CSI500"
- "Results tentative pending specification improvements"
- Emphasize: "Our analysis reveals that PBOC policy tone transmission is weaker than expected, possibly due to market regime shifts or other pricing mechanisms"

---

## 📈 Expected vs. Observed Results

| Scenario | Tone Coef | Ljung-Box | Nyblom | Outcome |
|----------|-----------|-----------|--------|---------|
| **Ideal** (strong policy effect) | < -0.05, p<0.001 | p > 0.05 | < 3.51 | ✓ Publish |
| **Good** (weak but real effect) | < -0.02, p<0.05 | p > 0.05 | < 3.51 | ✓ Publish (with caveats) |
| **Current** (SH only) | -0.0108, p=0.028 | p=0.987 | > 3.51 | ⚠ Revise |
| **Current** (SZ/HS300) | ≈0, p>0.6 | p<0.05 | > 3.51 | ✗ Requires new spec |

---

## 💡 Key Takeaway

**The tone coefficient is not significant in 3/4 indices, but this may not mean "tone has no effect."**

More likely: The EGARCH(0,0,1,1) model is misspecified and should be replaced with:
1. **ARMA dynamics** (1,1 or 2,1) to handle autocorrelation
2. **Rolling-window** estimates to address parameter instability
3. **Alternative sentiment measure** (tone_p90_all_z, lagged, or interaction terms)

**Bottom line for thesis**: 
- Current results → "PBOC policy tone effect not statistically significant in standard EGARCH framework, likely due to model misspecification"
- Revised results (after ARMA fix) → "Policy tone shows [effect/no effect] after controlling for dynamics"

---

**Last Updated**: 2024-12-19  
**File**: EGARCH_RESULTS_SUMMARY_A_D.md  
**Data Version**: egarch_daily_data_roberta.csv (n=4680, all 4 indices aligned)
