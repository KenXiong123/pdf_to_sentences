# debug_ljung_box.r - Check structure of Ljung-Box in rugarch output
suppressPackageStartupMessages({
  library(rugarch)
  library(xts)
})

# Quick test fit
set.seed(123)
data_ts <- xts(rnorm(1000), order.by = seq(as.Date("2020-01-01"), length.out=1000, by="day"))

spec <- ugarchspec(
  variance.model = list(model = "eGARCH", garchOrder = c(1,1)),
  mean.model = list(armaOrder = c(1,1), include.mean = TRUE),
  distribution.model = "std"
)

fit <- ugarchfit(spec = spec, data = data_ts, verbose = FALSE)

cat("✓ Model fitted successfully\n\n")

cat("--- Testing access to @fit$tests ---\n")
cat("Class of fit@fit$tests:", class(fit@fit$tests), "\n")
cat("Names:", names(fit@fit$tests), "\n\n")

if ("Ljung.Box" %in% names(fit@fit$tests)) {
  cat("✓ Ljung.Box exists\n")
  lb <- fit@fit$tests$Ljung.Box
  cat("  Class:", class(lb), "\n")
  cat("  Dim:", dim(lb), "\n")
  print(lb)
} else {
  cat("✗ Ljung.Box NOT found\n")
  cat("  Available tests:\n")
  for (nm in names(fit@fit$tests)) {
    cat("    -", nm, "\n")
  }
}

cat("\n--- Alternative access via show() output ---\n")
# Try extracting from show output
sink("test_output.txt")
show(fit)
sink()

lines <- readLines("test_output.txt")
idx <- grep("Ljung-Box", lines)
cat("Found Ljung-Box at lines:", idx, "\n")
if (length(idx) > 0) {
  cat("Context:\n")
  print(lines[(idx[1]-2):(idx[1]+8)])
}
