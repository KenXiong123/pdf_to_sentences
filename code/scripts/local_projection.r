#!/usr/bin/env Rscript

# ============================================================
# Event-time (stacked) Local Projections for text-tone shocks
# ------------------------------------------------------------
# FIXED version (scoping-safe): avoids get(idx) outside data.table
#
# 方案一：只围绕报告事件做回归（事件时间 τ=0..H）
#
# Main spec (收益):
#   shock_i = dTonePolicy_i and dToneMacro_i (report-to-report Δ, z-scored on report days)
#   y_{i,h} = cumulative return from event day to event+h:  R_{i,h} = sum_{j=0}^h r_{t_i+j}
#   h = 0..10
#   controls: short_rate_chg (event day) + p=5 lags of returns at event day
#   inference: heteroskedasticity-robust (HC1) across events (cross-sectional)
#
# Input:  egarch_daily_data_roberta.csv
# Output:
#   - lp_irf_results_stacked.csv
#   - lp_irf_plot_stacked.pdf
#
# Notes:
# - No Cairo/X11 required; uses base pdf() device.
# ============================================================

suppressPackageStartupMessages({
  library(data.table)
  library(lubridate)
  library(sandwich)
  library(lmtest)
  library(ggplot2)
})

# ----------------------------
# USER CONFIG
# ----------------------------
DATA_PATH <- "egarch_daily_data_roberta.csv"

# Choose one:
#   "split": d_tone_policy + d_tone_macro
#   "all"  : d_tone_all
TONE_MODE <- "split"

INDICES <- c("SH","SZ","HS300","CSI500")
H_MAX   <- 10
P_LAGS  <- 5

# Event-day controls (add more if you want)
CONTROLS <- c("short_rate_chg")
# Optional:
# CONTROLS <- c("short_rate_chg","usdcny_chg","fx_ret")

STANDARDIZE_SHOCK <- TRUE
CI_LEVELS <- c(0.90, 0.95)

OUT_CSV   <- "lp_irf_results_stacked.csv"
PLOT_FILE <- "lp_irf_plot_stacked.pdf"

# ----------------------------
# Helpers
# ----------------------------
stop_if_missing_cols <- function(dt, cols) {
  missing <- setdiff(cols, names(dt))
  if (length(missing) > 0) stop(paste0("Missing columns in data: ", paste(missing, collapse=", ")))
}

choose_col <- function(dt, candidates, what) {
  hit <- candidates[candidates %in% names(dt)]
  if (length(hit) == 0) {
    stop(paste0("Cannot find column for ", what, ". Tried: ", paste(candidates, collapse=", ")))
  }
  hit[[1]]
}

zscore <- function(x) {
  s <- sd(x, na.rm=TRUE)
  if (is.na(s) || s == 0) return(rep(0, length(x)))
  (x - mean(x, na.rm=TRUE)) / s
}

pretty_shock <- function(x) {
  if (x == "d_tone_policy") return("dTonePolicy (z)")
  if (x == "d_tone_macro")  return("dToneMacro (z)")
  if (x == "d_tone_all")    return("dToneAll (z)")
  x
}

save_plot_pdf <- function(p, filename, width=12, height=8) {
  grDevices::pdf(file=filename, width=width, height=height, useDingbats=FALSE, onefile=TRUE)
  on.exit(grDevices::dev.off(), add=TRUE)
  print(p)
}

# ----------------------------
# Load & prep
# ----------------------------
dt <- fread(DATA_PATH)
dt[, date := as.Date(date)]
setorder(dt, date)
dt[, rid := .I]  # row id (trading-day index)

# tone level columns (z)
col_policy <- choose_col(dt, c("tone_p90_policy_z","TonePolicy_z"), "tone policy (level z)")
col_macro  <- choose_col(dt, c("tone_p90_macro_z","ToneMacro_z"),  "tone macro (level z)")
col_all    <- NULL
if (TONE_MODE == "all") col_all <- choose_col(dt, c("tone_p90_all_z","ToneAll_z"), "tone all (level z)")

need_cols <- unique(c("date", INDICES, CONTROLS, col_policy, col_macro, if (!is.null(col_all)) col_all))
stop_if_missing_cols(dt, need_cols)

# numeric cast
for (cname in c(INDICES, CONTROLS, col_policy, col_macro, if (!is.null(col_all)) col_all)) {
  dt[, (cname) := as.numeric(get(cname))]
}

# Identify report days
if ("D_report" %in% names(dt)) {
  dt[, is_report := as.integer(!is.na(D_report) & D_report != 0)]
} else {
  dt[, is_report := as.integer((abs(get(col_policy)) > 0) | (abs(get(col_macro)) > 0) | (!is.null(col_all) & abs(get(col_all)) > 0))]
}

# ----------------------------
# Build Δtone shocks on report days only (report-to-report change)
# ----------------------------
rep <- dt[is_report == 1, .(date,
                           tone_policy = get(col_policy),
                           tone_macro  = get(col_macro))]
if (!is.null(col_all)) rep[, tone_all := dt[is_report==1, get(col_all)]]
setorder(rep, date)

rep[, d_tone_policy := tone_policy - shift(tone_policy, 1)]
rep[, d_tone_macro  := tone_macro  - shift(tone_macro, 1)]
if (!is.null(col_all)) rep[, d_tone_all := tone_all - shift(tone_all, 1)]

rep[is.na(d_tone_policy), d_tone_policy := 0]
rep[is.na(d_tone_macro),  d_tone_macro  := 0]
if (!is.null(col_all)) rep[is.na(d_tone_all), d_tone_all := 0]

if (STANDARDIZE_SHOCK) {
  rep[, d_tone_policy := zscore(d_tone_policy)]
  rep[, d_tone_macro  := zscore(d_tone_macro)]
  if (!is.null(col_all)) rep[, d_tone_all := zscore(d_tone_all)]
}

# Merge back: shocks are nonzero on report days only
dt[, `:=`(d_tone_policy = 0.0, d_tone_macro = 0.0)]
dt[rep, on="date", `:=`(d_tone_policy = i.d_tone_policy, d_tone_macro = i.d_tone_macro)]
if (!is.null(col_all)) {
  dt[, d_tone_all := 0.0]
  dt[rep, on="date", d_tone_all := i.d_tone_all]
}

message("[stacked LP] report events = ", nrow(rep),
        " | sd(d_policy)=", round(sd(rep$d_tone_policy),4),
        " | sd(d_macro)=", round(sd(rep$d_tone_macro),4),
        if (!is.null(col_all)) paste0(" | sd(d_all)=", round(sd(rep$d_tone_all),4)) else "")

# ----------------------------
# Precompute return lags at event day (dynamic controls)
# (scoping-safe: use dt[[idx]] vector)
# ----------------------------
for (idx in INDICES) {
  y <- dt[[idx]]
  for (k in 1:P_LAGS) {
    dt[, (paste0(idx, "_l", k)) := shift(y, k)]
  }
}

# ----------------------------
# Build event table (one row per report event)
# ----------------------------
shock_cols <- if (TONE_MODE == "all") c("d_tone_all") else c("d_tone_policy","d_tone_macro")
event_cols <- unique(c("date","rid", shock_cols, CONTROLS))

events <- dt[is_report == 1, ..event_cols]
setorder(events, date)
events[, event_id := .I]

# Attach index-specific lag controls to events when running regressions
# (we will select the needed lag columns per index later)

N <- nrow(dt)

# ----------------------------
# Horizon-by-horizon cross-event regressions
# y_{i,h} computed via prefix sums (fast, no scoping issues)
# ----------------------------
results <- list()

for (idx in INDICES) {
  # prefix sum for cumulative return
  y <- dt[[idx]]
  ps <- c(0, cumsum(y))  # length N+1

  dyn_cols <- paste0(idx, "_l", 1:P_LAGS)

  # pull event-day lags
  ev_lags <- dt[is_report == 1, ..dyn_cols]
  ev_base <- cbind(events, ev_lags)

  for (h in 0:H_MAX) {
    rid0 <- ev_base$rid
    rid1 <- rid0 + h

    # cumulative sum from rid0 to rid1 (inclusive)
    ycum <- rep(NA_real_, length(rid0))
    ok <- rid1 <= N
    ycum[ok] <- ps[rid1[ok] + 1] - ps[rid0[ok]]

    dt_h <- copy(ev_base)
    dt_h[, y := ycum]

    keep <- c("y", shock_cols, CONTROLS, dyn_cols)
    dt_reg <- dt_h[, ..keep]
    dt_reg <- dt_reg[complete.cases(dt_reg)]

    if (nrow(dt_reg) < 30) {
      for (sc in shock_cols) {
        results[[length(results)+1]] <- data.table(index=idx, h=h, shock=sc, beta=NA_real_, se=NA_real_, nobs=nrow(dt_reg))
      }
      next
    }

    fml <- as.formula(paste("y ~", paste(c(shock_cols, CONTROLS, dyn_cols), collapse=" + ")))
    fit <- lm(fml, data=dt_reg)

    V <- vcovHC(fit, type="HC1")
    ct <- coeftest(fit, vcov.=V)

    for (sc in shock_cols) {
      beta <- if (sc %in% rownames(ct)) ct[sc, "Estimate"] else NA_real_
      se   <- if (sc %in% rownames(ct)) ct[sc, "Std. Error"] else NA_real_
      results[[length(results)+1]] <- data.table(index=idx, h=h, shock=sc, beta=as.numeric(beta), se=as.numeric(se), nobs=nrow(dt_reg))
    }
  }
}

res <- rbindlist(results, use.names=TRUE, fill=TRUE)

# CI bands
for (lvl in CI_LEVELS) {
  z <- qnorm(1 - (1-lvl)/2)
  res[, paste0("lo_", sprintf("%02d", as.integer(lvl*100))) := beta - z*se]
  res[, paste0("hi_", sprintf("%02d", as.integer(lvl*100))) := beta + z*se]
}

res[, shock_label := vapply(shock, pretty_shock, FUN.VALUE=character(1))]

fwrite(res, OUT_CSV)
message("Saved IRF table: ", OUT_CSV)

# ----------------------------
# Plot
# ----------------------------
p <- ggplot(res, aes(x=h, y=beta)) +
  geom_hline(yintercept=0, linewidth=0.3, alpha=0.6) +
  geom_ribbon(aes(ymin=lo_95, ymax=hi_95), alpha=0.15) +
  geom_ribbon(aes(ymin=lo_90, ymax=hi_90), alpha=0.25) +
  geom_line(linewidth=0.7) +
  geom_point(size=1.2, alpha=0.9) +
  facet_grid(index ~ shock_label, scales="free_y") +
  labs(
    title = "Stacked (Event-time) Local Projections: IRFs to dTone Shocks",
    subtitle = paste0(
      "Dep var: cumulative return R_{t,t+h} | h=0..", H_MAX,
      " | controls: ", paste(CONTROLS, collapse=", "),
      " + ", P_LAGS, " return lags | SE: HC1 across events",
      ifelse(STANDARDIZE_SHOCK, " | shocks z-scored on report events", " | shocks raw Δ(z-tone)")
    ),
    x = "Horizon h (trading days after report)",
    y = "Response (percentage points)"
  ) +
  theme_classic(base_size=11) +
  theme(
    plot.title = element_text(face="bold"),
    strip.background = element_rect(fill="grey95", color=NA),
    panel.spacing = unit(0.8, "lines")
  )

save_plot_pdf(p, PLOT_FILE, width=12, height=8)
message("Saved plot: ", PLOT_FILE)
