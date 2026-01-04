# 立即行动：return lag测试（5分钟）

## 快速诊断：是否缺少return lags？

### 步骤1：修改MEAN_COLS（添加return lag）

编辑 `/code/scripts/run_egarch.r` 第40行：

```r
# 当前（无lag）：
MEAN_COLS <- c("S_gdp", "S_policy", "tone_p90_policy_z")

# 改为（带lag）：
MEAN_COLS <- c("S_gdp", "S_policy", "tone_p90_policy_z")
# 注意：r_{t-1} 会自动添加，见下面的create_return_lag()函数
```

不，实际上需要在数据准备步骤创建lag。让我直接给出修改清单。

---

## 正确的修改方法

需要在 `run_egarch.r` 中：

1. **在数据读取后添加lag创建**
2. **在MEAN_COLS中包含lag列名**

### 修改A：添加return lag到run_egarch.r

找到这行（大约第170行）：
```r
sub <- df[, c("date", ycol, mc, VAR_COLS)]
```

改为：
```r
# 创建return lag（前一天的returns）
df_with_lag <- df %>% 
  mutate(across(all_of(c("SH", "SZ", "HS300", "CSI500")), 
                list(lag1 = ~lag(., 1)), 
                .names = "{.col}_lag1"))

sub <- df_with_lag[, c("date", ycol, MEAN_COLS, paste0(ycol, "_lag1"), VAR_COLS)]
```

### 修改B：扩展MEAN_COLS（可选）

```r
# 原：
MEAN_COLS <- c("S_gdp", "S_policy", "tone_p90_policy_z")

# 可选扩展：
MEAN_COLS_WITH_LAG <- c("S_gdp", "S_policy", "tone_p90_policy_z", "r_lag1")
```

---

## 更简单的方法：使用现有的V2脚本

我已经创建了 `run_egarch_v2.r`，可以轻松测试return lag：

```r
# 在run_egarch_v2.r中，改这两行：

# 第26-27行：
TONE_VAR <- "tone_p90_policy_z"  # 保持原变量
INCLUDE_RETURN_LAG <- TRUE        # 改成TRUE！

# 然后运行：
Rscript run_egarch_v2.r
```

---

## 立即执行（现在）

### 命令1：修改V2脚本参数
```bash
cd /Users/kenxiong/Desktop/硕士毕业论文/code/scripts

# 编辑run_egarch_v2.r第27行：
# INCLUDE_RETURN_LAG <- FALSE → INCLUDE_RETURN_LAG <- TRUE
```

### 命令2：运行return lag版本
```bash
Rscript run_egarch_v2.r 2>&1 | tail -50
```

### 命令3：提取诊断并比较
```bash
# 创建新的诊断脚本专门对比return lag效果
Rscript << 'EOF'
# 快速对比：从输出文件读取Ljung-Box p-values
require(readr)

# 无lag版本（已存在）
original_files <- list.files(".", pattern="egarch_result_.*_roberta_r\\.txt")

# 新lag版本（待生成）
lag_files <- list.files(".", pattern="egarch_result_.*_roberta_r_v2.*\\.txt")

cat("比较return lag效果：\n\n")
for (f in original_files) {
  lines <- readLines(f)
  lb_idx <- grep("Weighted Ljung-Box Test on Standardized Residuals", lines)
  if (length(lb_idx) > 0) {
    lb_line <- lines[lb_idx[1] + 3]
    parts <- strsplit(lb_line, "\\s+")[[1]]
    pval <- as.numeric(parts[length(parts)])
    cat(sub("_roberta.*", "", f), "Ljung-Box p-val:", format(pval, digits=5), "\n")
  }
}
EOF
```

---

## 预期结果

如果return lag有效（解决残差自相关）：
```
原模型 (ARMA(2,1), no lag):
  SH: LB p = 0.0263 ⚠ 
  SZ: LB p = 0.0098 ⚠
  HS300: LB p = 0.0114 ⚠
  CSI500: LB p = 0.0351 ⚠

带return lag (ARMA(1,1), r_{t-1}):
  SH: LB p = ???? (希望 > 0.05) ✓
  SZ: LB p = ???? (希望 > 0.05) ✓
  HS300: LB p = ???? (希望 > 0.05) ✓
  CSI500: LB p = ???? (希望 > 0.05) ✓
```

---

## 如果return lag不起作用？

那么问题可能真的在于：
1. **结构性中断** (Nyblom提示的)
   → 需要滚动窗口或regime-switching

2. **高阶ARMA** (ARMA(3,1)或更高)
   → 日收益可能需要3-4阶AR结构

3. **非线性动态** 
   → ARMA无法捕捉

4. **真实的null效应** (最后的可能)
   → PBOC tone确实不影响市场

---

## 下一个优先级（如果return lag不工作）

按此顺序尝试：
1. ARMA(3,0) 或 ARMA(3,1) - 更高的AR阶数
2. 滚动窗口（250天）- 理解参数不稳定性
3. GJR-GARCH - 处理方差的非对称性
4. Regime-Switching - 显式建模structural breaks

---

## 检查清单

- [ ] 修改 run_egarch_v2.r INCLUDE_RETURN_LAG = TRUE
- [ ] 运行 Rscript run_egarch_v2.r  
- [ ] 检查输出中的Ljung-Box p-values
- [ ] 记录是否改善
- [ ] 比较4个输出文件的tone系数 & 诊断
- [ ] 决定下一步（成功继续，失败→优先级3）

---

**预计时间**: 5分钟运行 + 10分钟诊断 = 15分钟总计  
**临界性**: 高（快速判断return lag假设）  
**潜在影响**: 如果有效，可能解决3/4的Ljung-Box问题
