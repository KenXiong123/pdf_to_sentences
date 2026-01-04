# 诊断文件夹 (Diagnostics)

此文件夹包含所有EGARCH-X模型诊断、测试和改进相关的文件。

## 📋 文件清单

### 📊 诊断报告 (按阅读顺序)

| 文件 | 用途 | 优先级 |
|------|------|--------|
| **QUICK_REFERENCE_GUIDE.md** | 快速参考：原始结果概览、问题诊断 | ⭐⭐⭐ 先读 |
| **EGARCH_RESULTS_SUMMARY_A_D.md** | 初始EGARCH结果详细分析（选项A/D对比） | ⭐⭐ |
| **COMPREHENSIVE_DIAGNOSTIC_SUMMARY.md** | 3阶段改进策略详细总结 + 优先级行动计划 | ⭐⭐⭐ |
| **RETURN_LAG_COMPARISON.txt** | Return lag测试结果对比（完整诊断） | ⭐⭐ |
| **ARMA_COMPARISON_REPORT.md** | ARMA(0,0) vs (1,1) vs (2,1)对比分析 | ⭐ |
| **V1_vs_V2_COMPARISON.md** | tone_p90_policy_z vs tone_p90_all_z对比 | ⭐ |
| **ACTION_ITEM_RETURN_LAG_TEST.md** | Return lag测试执行指南（已完成） | 参考 |

### 🔧 诊断脚本 (R)

| 脚本 | 功能 | 使用场景 |
|------|------|----------|
| **egarch_final_diagnostics.r** | 从output文件提取Ljung-Box/ARCH/Nyblom统计量 | 运行完EGARCH后提取诊断 |
| **diagnose_return_lag_effect.r** | 对比有无return lag的Ljung-Box效果 | 评估return lag影响 |
| **run_egarch_v2.r** | EGARCH回归脚本（替代规格测试） | 测试不同tone变量和return lag |
| **run_egarch_arma_search.r** | 系统搜索ARMA阶数（3,0)/(1,2)/(3,1) | 寻找通过Ljung-Box的ARMA阶 |

---

## 🔍 核心发现摘要

### ✅ 已完成的诊断

**阶段1：ARMA阶数测试**
- ARMA(0,0) → (1,1) → (2,1)系统测试
- 结果：ARMA增加反而使SH恶化（p: 0.028→0.696）
- 结论：ARMA阶增加不是解决方案

**阶段2：Tone变量切换**
- tone_p90_policy_z vs tone_p90_all_z对比
- 结果：两个变量给出相同的显著性结果（p>0.6）
- 结论：Tone变量定义不影响非显著性结果

**阶段3：Return lag测试**
- 添加r_{t-1}到均值方程
- 结果：Return lag本身显著(p<0.001)但Ljung-Box不改善
  - SH: 0.0263 → 0.0290 (恶化)
  - SZ: 0.0098 → 0.0092 (恶化)
  - HS300: 0.0114 → 0.0061 (大幅恶化)
  - CSI500: 0.0351 → 0.0465 (改善但仍失败)
- 结论：自相关不是遗漏return lag引起的

### ❌ 根本问题

1. **参数不稳定性**（Nyblom > 3.51所有指数）
   - 表明2017-2024期间结构性中断
   - 常系数模型违反

2. **高阶自相关**（Ljung-Box p<0.05所有指数）
   - ARMA(2,1)仍不足
   - 需要ARMA(3,0)或更高阶

3. **持久ARCH效应**（所有指数p<0.05）
   - GARCH(1,1)可能不足
   - 考虑GJR-GARCH或GARCH(2,1)

---

## 🎯 下一步优先级

### Priority 1: ARMA阶搜索 ⏳ 进行中
```bash
Rscript run_egarch_arma_search.r
```
- 测试：ARMA(3,0), ARMA(1,2), ARMA(3,1)
- 目标：找到通过Ljung-Box的阶数
- 预计时间：15-30分钟

### Priority 2: 滚动窗口EGARCH
- 方法：250天滚动窗口拟合tone系数
- 目标：可视化参数随时间变化
- 预计时间：2小时

### Priority 3: Regime-Switching EGARCH
- 方法：2-state Markov regime-switching
- 目标：直接建模结构性中断
- 预计时间：4-6小时

### Priority 4: GJR-GARCH替代
- 变更：eGARCH → gjrGARCH
- 目标：处理非对称波动响应
- 预计时间：1小时

---

## 📖 文件快速查询

**想了解原始模型有什么问题？**
→ 阅读 `QUICK_REFERENCE_GUIDE.md`

**想看系统的改进尝试与结果？**
→ 阅读 `COMPREHENSIVE_DIAGNOSTIC_SUMMARY.md`

**想复现Return lag测试？**
→ 运行 `diagnose_return_lag_effect.r` 或参考 `RETURN_LAG_COMPARISON.txt`

**想自己测试ARMA阶数？**
→ 修改并运行 `run_egarch_arma_search.r`

**想对比两个不同的EGARCH规格？**
→ 编辑 `run_egarch_v2.r` 参数，运行回归

---

## 🗂️ 文件依赖关系

```
原始EGARCH结果 (code/scripts/egarch_result_*.txt)
    ↓
egarch_final_diagnostics.r (提取统计量)
    ↓
诊断报告 (QUICK_REFERENCE, EGARCH_RESULTS_SUMMARY)
    ↓
系统改进阶段
  ├─ ARMA(0,0)→(2,1)测试 → ARMA_COMPARISON_REPORT.md
  ├─ Tone变量切换 → V1_vs_V2_COMPARISON.md
  └─ Return lag添加 → RETURN_LAG_COMPARISON.txt
    ↓
COMPREHENSIVE_DIAGNOSTIC_SUMMARY.md (汇总所有发现)
    ↓
下一步：Priority 1-4优先级计划
```

---

## ⚙️ 如何使用此文件夹

### 快速开始（5分钟）
1. 阅读 `QUICK_REFERENCE_GUIDE.md`
2. 查看 `RETURN_LAG_COMPARISON.txt` 的摘要
3. 决定下一步优先级

### 深度诊断（30分钟）
1. 按顺序阅读 `EGARCH_RESULTS_SUMMARY_A_D.md`
2. 研究 `COMPREHENSIVE_DIAGNOSTIC_SUMMARY.md` 的根本原因分析
3. 查看 `ARMA_COMPARISON_REPORT.md` 和 `V1_vs_V2_COMPARISON.md`

### 重现分析（1-2小时）
```bash
# 提取所有诊断统计量
cd ../
Rscript diagnostics/egarch_final_diagnostics.r

# 对比return lag效果
Rscript diagnostics/diagnose_return_lag_effect.r

# 搜索最优ARMA阶
Rscript diagnostics/run_egarch_arma_search.r
```

### 修改脚本参数测试新规格
编辑 `run_egarch_v2.r`：
```r
TONE_VAR <- "tone_p90_policy_z"  # 改为其他变量
INCLUDE_RETURN_LAG <- TRUE        # 启用/禁用
ARMA_MODE <- "fixed"
FIXED_ARMA <- c(3, 0)             # 测试不同ARMA
```

然后运行回归：
```bash
cd ../
Rscript diagnostics/run_egarch_v2.r
```

---

## 📝 关键数据点

| 指标 | SH | SZ | HS300 | CSI500 |
|------|----|----|-------|--------|
| **Ljung-Box p (ARMA(2,1))** | 0.0263 | 0.0098 | 0.0114 | 0.0351 |
| **Pass p>0.05？** | ✗ | ✗ | ✗ | ✗ |
| **Tone p值** | 0.696 | 0.630 | 0.685 | 0.638 |
| **Nyblom稳定性** | 13.68 | 4.47 | 4.59 | 6.46 |
| **Critical值** | 3.51 | 3.51 | 3.51 | 3.51 |

---

## 💡 工作流建议

```
论文写作流程：

1. 诊断阶段 ← 你在这里
   ├─ 阅读所有诊断报告
   ├─ 理解根本问题
   └─ 确定改进策略
   
2. 改进阶段 ← 接下来
   ├─ Priority 1: ARMA搜索
   ├─ Priority 2: 滚动窗口
   └─ Priority 3: Regime-switching
   
3. 最终分析阶段
   ├─ 选择最优模型
   ├─ 跑LP-IRF分析
   └─ 论文初稿
```

---

## 👤 维护者

创建时间：2026年1月4日  
最后更新：2026年1月4日  
当前状态：✅ 诊断完成，待优先级1执行

---

**有问题？** 查看 `COMPREHENSIVE_DIAGNOSTIC_SUMMARY.md` 的"常见问题"部分
