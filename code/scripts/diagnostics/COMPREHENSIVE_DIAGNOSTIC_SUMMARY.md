# 2025年EGARCH诊断完整总结与方向建议

**日期**: 2025年1月4日  
**分析阶段**: 3个主要迭代（ARMA改进、Tone变量测试、诊断总结）

---

## 执行摘要

经过系统的模型改进和诊断测试，发现**PBOC政策tone对股市回报的影响不显著且不稳定**，但这**可能反映模型误设而非真实的null效应**。

### 关键发现

| 方面 | 发现 | 含义 |
|------|------|------|
| **Tone显著性** | 0/4指数显著（p>0.59） | Effect不存在或太弱检测 |
| **残差自相关** | 4/4指数Ljung-Box失败 | ARMA阶数不足或mean eq误设 |
| **参数稳定性** | 4/4指数Nyblom > 3.51 | Structural breaks或regime shifts |
| **ARCH效应** | 4/4指数显示 | 方差模型需加强 |
| **改进有效性** | ARMA↑、Tone改变、标准化 全无效 | 问题更深层 |

---

## 完整改进日志

### 阶段1：ARMA规格升级（2025年1月4日）

**尝试**：ARMA(0,0) → ARMA(1,1) → ARMA(2,1)

**结果**：
```
ARMA(0,0) → (1,1)：Ljung-Box全部恶化
  SH: 0.987 → 0.0002 ⚠
  SZ: 0.009 → 0.025 (相同)
  HS300: 0.005 → 0.032 ⚠
  CSI500: 0.037 → 0.010 (恶化)

ARMA(1,1) → (2,1)：边际改进或无效
  整体：仍然4/4失败
```

**教训**：增加ARMA阶数并不能系统地解决自相关。可能存在：
- 非线性动态ARMA无法捕捉
- 结构性变化导致的autocorr（不能用线性滤波解决）
- 数据中的regime switches

---

### 阶段2：Tone变量替换（2025年1月4日）

**尝试**：tone_p90_policy_z (政策特定) → tone_p90_all_z (总体)

**结果**：
```
均值方程tone系数：
  Policy-spec:  0.170-0.250 (p=0.63-0.70)
  General:     -0.035 to -0.159 (p=0.59-0.88)

Ljung-Box：几乎相同，都失败
Nyblom：轻微恶化或不变
```

**教训**：Tone的定义无关紧要。问题不在于sentiment measure的选择，而在于：
- Tone变量本身可能无经济意义
- 或者信号被其他因素淹没
- 或者因果关系反向（市场→央行，而非央行→市场）

---

### 阶段3：诊断深化（2025年1月4日）

**提取的诊断指标**：

**Ljung-Box结果（所有规格）**：
- SH: p=0.0002-0.027 ⚠ (自相关)
- SZ: p=0.0098-0.025 ⚠ (自相关)
- HS300: p=0.0113-0.032 ⚠ (自相关)
- CSI500: p=0.0095-0.037 ⚠ (自相关)

**Nyblom稳定性**（Joint Statistic vs 3.51临界值）：
- SH: 4.47-13.68 ⚠ (所有不稳定)
- SZ: 3.91-4.77 ⚠ (所有不稳定)
- HS300: 4.47-17.14 ⚠ (所有不稳定)
- CSI500: 6.04-6.58 ⚠ (所有不稳定)

**ARCH LM测试** (ARCH Lag[3])：
- 所有指数/规格：p < 0.05 ⚠ (方差clustering)

---

## 根本原因分析

### 为什么Tone不显著？

**不是**：
- ✗ 模型缺少ARMA阶数（已测ARMA 0-2）
- ✗ Tone测量不当（Policy vs General无区别）
- ✗ SE估计过大（Robust SE已调整）

**可能是**：
1. **模型误设** (HIGH PRIORITY)
   - Mean equation缺少关键动态
   - Return lags可能需要
   - Tone的lag结构（tone_{t-1}, tone_{t-2}）
   - 非线性关系（tone × events）

2. **参数不稳定性** (CRITICAL)
   - Nyblom全部 > 3.51 → structural breaks
   - 2017-2024包含多个制度变化：
     - 2018年：中美贸易战、股市下跌
     - 2020年：COVID-19崩溃和反弹
     - 2022年：严格防控、经济下行
   - 常数系数模型不适用

3. **方差方程不足** (MEDIUM PRIORITY)
   - ARCH效应普遍存在
   - GARCH(1,1)无法捕捉所有波动持久性
   - 可能需要GJR-GARCH或更高阶

4. **真实null效应** (LOWER PRIORITY)
   - PBOC tone可能确实不影响市场
   - 政策信号已完全定价
   - 传导机制通过其他渠道（信用、汇率）

---

## 建议的下一步行动计划

### 立即行动（本周）

**优先级1：滚动窗口分析**（处理参数不稳定性）
```
目标：理解Nyblom高值的来源
方法：
  - 拟合250天rolling window EGARCH
  - 绘制tone系数随时间变化
  - 识别coefficients显著变化的时期
  - 与市场事件（崩溃、政策变化）对齐

预期产出：
  - 4个图表（SH, SZ, HS300, CSI500）
  - 系数路径plot展示instability何处发生
  - 证据支持regime-switching或breakpoint模型
  
时间：2小时编程 + 5分钟运行
代码：code/scripts/rolling_window_egarch.r
```

**优先级2：return lag测试**（处理Ljung-Box自相关）
```
目标：检查return momentum/reversion是否缺失
方法：
  修改MEAN_COLS：c("S_gdp", "S_policy", "tone", "r_{t-1}")
  重新拟合ARMA(1,1)
  检查Ljung-Box p-value是否改善

预期：
  - r_{t-1}应该显著（日收益有持久性）
  - Ljung-Box可能改善（captured momentum）
  - 需要检查多重共线性

时间：5分钟编辑run_egarch.r + 2分钟运行
```

### 中期行动（本周末）

**优先级3：Regime-Switching模型**（对抗参数不稳定性）
```
目标：允许系数基于隐藏状态变化
方法：
  - Hamilton regime-switching EGARCH
  - 或：Markov Switching GARCH
  需要包：MSwM 或 regswitch (R)

优势：
  - 直接处理structural breaks
  - 允许"牛市"vs"熊市"系数不同
  - 比rolling window更优雅

时间：4-6小时
```

**优先级4：GJR-GARCH升级**（处理ARCH效应）
```
目标：添加非对称性到方差方程
方法：
  spec: variance.model = list(model = "gjrGARCH", ...)
  
优势：
  - Gamma项捕捉负冲击的非对称响应
  - 可能减少ARCH LM p-value
  
时间：1小时（主要改变model string）
```

### 长期行动（2周）

**优先级5：跨市场比较**
```
- 测试其他指数（中小板SME、创业板CY）
- Tone对不同市场的差异影响？
- 是否存在套利机会？
```

**优先级6：因果方向分析**
```
- Granger causality: tone → returns?
- 反向：returns → tone (央行反应)
- VAR脉冲响应分析
```

---

## 论文应该如何处理这个问题

### 当前阶段：诊断文献

**应该写的**：
> "Our initial EGARCH-X specification with ARMA(0,0) shows policy tone
> is not significant across most indices (p>0.6). Diagnostic tests reveal
> systematic model misspecification: (1) residual autocorrelation persists
> despite ARMA extensions (Ljung-Box p<0.05 for 4/4 indices), (2) parameter
> instability across the 2017-2024 sample (Nyblom statistics exceed 1%
> critical values), and (3) unexplained variance clustering (ARCH effects).
> These results suggest the model requires structural improvements beyond
> tone variable specification."

**不应该说的**：
- ✗ "Tone has no effect" (possible model artifact, not economic conclusion)
- ✗ "Results are robust" (Nyblom instability contradicts this)
- ✗ "PBOC communication irrelevant" (conclusion requires better model)

### 下一阶段：改进模型

**实施以上4个优先项目后**：
- 如果tone仍不显著：
  > "Despite specification improvements (rolling window, return lags,
  > GJR-GARCH), tone coefficient remains insignificant. This suggests either
  > PBOC monetary policy communication does not directly affect stock market
  > returns, or transmission operates through alternative channels."

- 如果tone变显著：
  > "After controlling for parameter instability and return persistence,
  > policy tone exhibits a [direction] effect on [which indices]. Magnitude:
  > [X] std-dev change in tone → [Y]% return impact."

---

## 关键文件与脚本状态

| 文件 | 版本 | 用途 | 状态 |
|------|------|------|------|
| run_egarch.r | V1 (current) | tone_p90_policy_z, ARMA(2,1) | ✅ Active |
| run_egarch_v2.r | V2 | tone_p90_all_z, ARMA(2,1) | ✅ Alternative |
| rolling_window_egarch.r | 待创建 | 滚动窗口分析 | ⏳ Priority 1 |
| gjr_garch.r | 待创建 | GJR非对称模型 | ⏳ Priority 4 |
| ARMA_COMPARISON_REPORT.md | ✅ | 阶段1总结 | ✓ |
| V1_vs_V2_COMPARISON.md | ✅ | 阶段2总结 | ✓ |

---

## 统计数据快照

### 当前模型评分卡（ARMA(2,1), tone_policy）

| 指数 | Tone p-val | LB p-val | Nyblom | ARCH p-val | 总体评级 |
|------|-----------|---------|--------|-----------|---------|
| SH | 0.696 | 0.0263 ⚠ | 4.47 ⚠ | 0.021 ⚠ | ⚠ Fair |
| SZ | 0.630 | 0.0098 ⚠ | 4.73 ⚠ | 0.023 ⚠ | ⚠ Fair |
| HS300 | 0.685 | 0.0114 ⚠ | 4.69 ⚠ | 0.030 ⚠ | ⚠ Fair |
| CSI500 | 0.638 | 0.0351 ⚠ | 6.56 ⚠ | 0.020 ⚠ | ⚠ Fair |

**平均来说**：
- Tone significance: 0% (0/4显著)
- Autocorrelation问题: 100% (4/4失败)
- Stability问题: 100% (4/4不稳定)
- ARCH问题: 100% (4/4存在)

---

## 论文时间表

```
当前 (1月4-6日)
  ↓ 完成Priority 1-2（滚动窗口 + return lag）
  
1月6-8日：中期评估
  ↓ 结果是否改善？
  
是 → 拟定论文结果 (1月10-15日)
否 → 实施Priority 3-4（Regime-switching/GJR） (1月8-12日)

最终：论文讨论 (1月15-20日)
```

---

## 最后的建议

### ⚠️ 重要警告

**不要陷入"参数调整"陷阱**。目前的问题不是优化现有框架，而是：
1. 理解为什么当前框架失败
2. 明确下一个假设和设计
3. 目标明确地改进（而不是盲目尝试）

目前已测试：
- ✓ 5种不同ARMA组合
- ✓ 2种tone变量
- ✓ 标准化选项
- ✓ 各种诊断提取

**下一步应该是：**
- ✓ 一次彻底的参数稳定性分析（rolling window）
- ✓ 一种处理structural breaks的显式模型（regime-switching）
- ✓ 对残留动态的理论驱动的诊断

### ✅ 你的下一个行动

**现在就做**：
```bash
# 修改run_egarch.r添加return lag
MEAN_COLS <- c("S_gdp", "S_policy", "tone_p90_policy_z", "r_lag1")
FIXED_ARMA <- c(1, 1)  # 简化为ARMA(1,1)
STANDARDIZE_MEAN <- FALSE

# 运行并检查Ljung-Box是否改善
Rscript run_egarch.r
Rscript egarch_final_diagnostics.r
```

这需要5分钟，可以快速判断return lag是否缓解自相关问题。

---

**报告完成时间**: 2025年1月4日 15:50 UTC  
**下一次检查**: 2025年1月6日（Priority 1-2完成）
