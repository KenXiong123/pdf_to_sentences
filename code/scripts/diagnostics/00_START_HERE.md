# 📊 EGARCH-X 模型诊断中心

**欢迎来到诊断文件夹！** 这里汇集了所有关于EGARCH-X模型改进的诊断报告、测试脚本和分析结果。

---

## 🚀 3步快速开始

### 第1步：理解当前状态（5分钟）
```
→ 打开：QUICK_REFERENCE_GUIDE.md
  - 原始模型的4个关键问题
  - Ljung-Box测试结果
  - Nyblom稳定性诊断
  - 可视化表格对比
```

### 第2步：了解改进尝试（15分钟）
```
→ 打开：COMPREHENSIVE_DIAGNOSTIC_SUMMARY.md
  - 3阶段系统改进日志
  - ARMA升级、Tone变量切换、Return lag测试
  - 每个阶段为什么失败
  - 根本原因分析（4个假设）
```

### 第3步：查看详细结果（10分钟）
```
→ 打开：RETURN_LAG_COMPARISON.txt
  - Return lag测试的完整诊断
  - 4个指数的对比数据
  - 为什么Return lag不是解决方案
```

---

## 📂 文件导航地图

```
诊断文件夹/
│
├─ 📖 必读文档 (必看)
│  ├─ 00_START_HERE.md          ← 你在这里
│  ├─ QUICK_REFERENCE_GUIDE.md  ⭐ 快速参考
│  └─ COMPREHENSIVE_DIAGNOSTIC_SUMMARY.md ⭐ 深度分析
│
├─ 📊 诊断报告 (参考)
│  ├─ EGARCH_RESULTS_SUMMARY_A_D.md        初始结果分析
│  ├─ RETURN_LAG_COMPARISON.txt            Return lag详细对比
│  ├─ ARMA_COMPARISON_REPORT.md            ARMA(0,0)/(1,1)/(2,1)对比
│  ├─ V1_vs_V2_COMPARISON.md               Tone变量对比
│  └─ ACTION_ITEM_RETURN_LAG_TEST.md       执行指南（已完成）
│
├─ 🔧 诊断脚本 (执行)
│  ├─ egarch_final_diagnostics.r           提取统计量
│  ├─ diagnose_return_lag_effect.r         Return lag对比
│  ├─ run_egarch_v2.r                      替代规格测试
│  └─ run_egarch_arma_search.r             ARMA阶数搜索
│
└─ 📚 参考 (这个文件)
   └─ README.md                            完整说明文档
```

---

## ⚡ 快速诊断概览

### 当前模型状态（ARMA(2,1)）

| 指标 | SH | SZ | HS300 | CSI500 | 状态 |
|------|----|----|-------|--------|------|
| Ljung-Box p | 0.026 | 0.010 | 0.011 | 0.035 | ❌ 4/4失败 |
| 需要 | p>0.05 | p>0.05 | p>0.05 | p>0.05 | - |
| Tone p值 | 0.696 | 0.630 | 0.685 | 0.638 | ❌ 全不显著 |
| Nyblom稳定 | 13.68 | 4.47 | 4.59 | 6.46 | ❌ 全>3.51 |

### 已测试的改进方案

| 改进方案 | 结果 | 原因 |
|---------|------|------|
| ARMA(0,0)→(1,1) | ❌ 更差 | 自相关增加 |
| ARMA(1,1)→(2,1) | ❌ 部分改善 | SH从p=0.028降到p=0.696 |
| Tone变量切换 | ❌ 无效 | Tone变量选择无关 |
| Return lag添加 | ❌ 无效 | Ljung-Box 3/4恶化，1/4勉强改善 |

### 根本原因排序

```
优先级 1 (最严重) → 参数不稳定
                   • Nyblom > 3.51 (所有指数)
                   • 表明2017-2024结构性中断
                   • 常系数模型违反
                   
优先级 2          → 高阶自相关  
                   • Ljung-Box p<0.05 (所有指数)
                   • ARMA(2,1)仍不足
                   • 需要ARMA(3,0)或更高
                   
优先级 3          → ARCH效应持续
                   • 所有指数ARCH p<0.05
                   • GARCH(1,1)可能不足
                   
优先级 4          → Tone真实null
                   • 政策可能通过其他渠道传导
```

---

## 🎯 下一步行动计划

### ✅ 已完成
- [x] 初始EGARCH回归与诊断
- [x] ARMA阶数系统测试 (0,0)→(1,1)→(2,1)
- [x] Tone变量替代测试
- [x] Return lag包含/排除测试
- [x] 根本原因分析与排序

### ⏳ Priority 1: ARMA阶搜索 (进行中)
**文件**: `run_egarch_arma_search.r`  
**时间**: 15-30分钟  
**命令**:
```bash
cd ../
Rscript diagnostics/run_egarch_arma_search.r
```
**目标**: 找到通过Ljung-Box (p>0.05)的ARMA阶

### 📅 Priority 2: 滚动窗口EGARCH (待做)
**时间**: 2小时  
**目标**: 可视化参数如何随时间变化  
**方法**: 250天滚动窗口

### 📅 Priority 3: Regime-Switching (待做)
**时间**: 4-6小时  
**目标**: 直接建模2-state结构性中断  
**模型**: Markov regime-switching EGARCH

### 📅 Priority 4: GJR-GARCH (待做)
**时间**: 1-2小时  
**目标**: 处理非对称波动响应  
**改变**: eGARCH→gjrGARCH

---

## 💡 按用途快速查找

**"我想了解模型有什么问题"**
→ [QUICK_REFERENCE_GUIDE.md](QUICK_REFERENCE_GUIDE.md)

**"我想看所有的改进尝试过程"**
→ [COMPREHENSIVE_DIAGNOSTIC_SUMMARY.md](COMPREHENSIVE_DIAGNOSTIC_SUMMARY.md)

**"我想看return lag的具体测试结果"**
→ [RETURN_LAG_COMPARISON.txt](RETURN_LAG_COMPARISON.txt)

**"我想自己运行诊断提取脚本"**
→ `Rscript egarch_final_diagnostics.r`

**"我想测试新的ARMA阶数"**
→ 编辑`run_egarch_v2.r`中的FIXED_ARMA参数

**"我想了解为什么ARMA升级失败了"**
→ [ARMA_COMPARISON_REPORT.md](ARMA_COMPARISON_REPORT.md)

---

## 📋 检查清单

按以下顺序进行诊断：

- [ ] 阅读 `QUICK_REFERENCE_GUIDE.md`（5分钟）
- [ ] 阅读 `COMPREHENSIVE_DIAGNOSTIC_SUMMARY.md`（15分钟）
- [ ] 浏览 `RETURN_LAG_COMPARISON.txt`（5分钟）
- [ ] 选择Priority 1-4中的一个来执行
- [ ] 记录新结果
- [ ] 更新论文方法部分

---

## 🔬 一句话总结每个诊断

| 文件 | 关键发现 |
|------|---------|
| QUICK_REFERENCE | Ljung-Box全失败，原因是参数不稳定与高阶自相关 |
| COMPREHENSIVE_DIAGNOSTIC | 3个改进尝试全失败，根本问题是结构性中断（Nyblom） |
| EGARCH_RESULTS | 初始模型：tone非显著，SH边界显著但负号，其他指数p>0.6 |
| RETURN_LAG_COMPARISON | Return lag本身显著但不能修复Ljung-Box，3/4恶化1/4勉强 |
| ARMA_COMPARISON | ARMA升级反效果，SH最坏（从p=0.028→0.696） |
| V1_vs_V2_COMPARISON | Tone变量选择无关，问题更深层 |

---

## 🎓 论文工作流

```
当前进度：
├─ 分析阶段 ✅ 完成
│  └─ 诊断出根本问题：参数不稳定 + 高阶自相关
│
├─ 改进阶段 ⏳ 进行中
│  ├─ Priority 1: ARMA搜索 (待执行)
│  ├─ Priority 2: 滚动窗口 (计划中)
│  ├─ Priority 3: Regime-switching (计划中)
│  └─ Priority 4: GJR-GARCH (备选)
│
└─ 论文写作阶段 📝 待准备
   ├─ 方法部分：描述诊断过程与改进尝试
   ├─ 结果部分：报告最优模型（Priority 1-3之一）
   └─ 讨论部分：解释为什么tone不显著（可能性4个）
```

---

## 📞 常见问题 FAQ

**Q: 为什么Ljung-Box测试这么重要？**
A: 它检测残差中的自相关。如果p<0.05，说明模型遗漏了重要的动态，结果不可信。

**Q: 为什么ARMA升级反而让SH变差？**
A: 可能是因为SH在2017-2024有结构性中断。在这期间添加AR项实际上恶化了拟合。

**Q: Return lag应该被包含吗？**
A: 是的，economically显著（p<0.001）。虽然不能修复Ljung-Box，但应在最终模型中保留。

**Q: 下一步应该做什么？**
A: Priority 1是ARMA搜索（15-30分钟）。如果ARMA(3,0)等都失败，跳到Priority 2（滚动窗口）。

**Q: 我应该选择哪个Priority先做？**
A: 按顺序做：1→2→3→4。每个优先级建立在前面诊断的基础上。

---

## 📈 进度追踪

```
诊断进度：████████████████████ 100% ✅ (所有诊断完成)
改进进度：█░░░░░░░░░░░░░░░░░░░  5% ⏳ (Priority 1准备中)
论文进度：░░░░░░░░░░░░░░░░░░░░  0% 📝 (待诊断完成)
```

---

**最后更新**: 2026年1月4日  
**下一步**: 执行Priority 1 (ARMA搜索)  
**预期完成**: 2026年1月4-5日

👉 **现在就开始**: [打开 QUICK_REFERENCE_GUIDE.md](QUICK_REFERENCE_GUIDE.md)
