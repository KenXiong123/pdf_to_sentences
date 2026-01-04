# 比较V1（tone_p90_policy_z）vs V2（tone_p90_all_z）的EGARCH结果

## 主要发现

### Tone变量对比：Policy-Specific vs General Sentiment

#### 平均方程中Tone系数比较（ARMA(2,1)，Robust SE）

| Index | tone_p90_policy_z | tone_p90_all_z | 变化 |
|-------|-----------------|----------------|------|
| **SH** | 0.1701 (p=0.696) | -0.0356 (p=0.878) | ✗ 两个都不显著，符号反向 |
| **SZ** | 0.1656 (p=0.630) | -0.1586 (p=0.591) | ✗ 两个都不显著，符号反向 |
| **HS300** | 0.1916 (p=0.685) | -0.1144 (p=0.649) | ✗ 两个都不显著，符号反向 |
| **CSI500** | 0.2500 (p=0.638) | -0.0892 (p=0.692) | ✗ 两个都不显著，符号反向 |

### Ljung-Box自相关测试（关键诊断）

| Index | tone_policy | tone_all | 改进？ |
|-------|-----------|---------|--------|
| **SH** | 0.0263 ⚠ | 0.0267 ⚠ | ✗ 无改进 |
| **SZ** | 0.0098 ⚠ | 0.0099 ⚠ | ✗ 无改进 |
| **HS300** | 0.0114 ⚠ | 0.0113 ⚠ | ✗ 无改进 |
| **CSI500** | 0.0351 ⚠ | 0.0354 ⚠ | ✗ 无改进 |

### Nyblom稳定性测试（参数不稳定性）

| Index | tone_policy | tone_all | 临界值(1%) |
|-------|-----------|---------|----------|
| **SH** | 4.4654 ✓ | 5.4176 ⚠ | 4.07 |
| **SZ** | 4.7271 ⚠ | 4.7764 ⚠ | 4.07 |
| **HS300** | 4.6854 ⚠ | 4.6986 ⚠ | 4.07 |
| **CSI500** | 6.5627 ⚠ | 6.5811 ⚠ | 4.07 |

## 关键结论

### 1. Tone变量选择无关紧要
- **Policy-specific (tone_p90_policy_z)** 和 **General (tone_p90_all_z)** 产生几乎相同的结果
- 两者都不显著（p > 0.59 对所有指数）
- **含义**：问题不在于tone的定义，而在于更深层的问题

### 2. Ljung-Box自相关问题持续存在
- ARMA(2,1) 无法解决3/4指数的残差自相关
- 增加ARMA阶数、改变tone变量都无效
- **可能原因**：
  - 指数变化动态需要更复杂的ARMA结构（3+阶）
  - 或者问题在于均值方程的规格本身

### 3. Nyblom稳定性有所改善但仍有问题
- tone_all 情况下 SH 变得不稳定（从4.47 → 5.42）
- 其他指数稳定性无改变或恶化
- 所有4个指数仍然 > 3.51 的1%临界值
- **含义**：模型参数随时间漂移（structural breaks或regime shifts）

### 4. ARCH效应普遍存在
- 所有指数在两个tone变量下都显示ARCH效应
- 暗示方差方程需要加强（GJR-GARCH、更高阶GARCH）

## 诊断建议

### ❌ 不要再尝试的
- ❌ 增加ARMA阶数（已尝试0-2，无改进）
- ❌ 更换tone变量定义（Policy vs General无区别）
- ❌ 调整z-score标准化（会引入数值不稳定性）

### ✅ 应该尝试的

**优先级1：参数不稳定性**
```
为什么Nyblom所有都> 3.51？
→ 滚动窗口估计：2017-2019, 2020-2022, 2023-2024
→ 绘制系数路径图
→ 识别structural breaks的具体时间
```

**优先级2：ARCH效应**
```
为什么所有指数都显示ARCH效应？
→ 升级到GJR-GARCH（gamma项）
→ 或使用GARCH(2,1)而非GARCH(1,1)
→ 或者Student-t分布不够（考虑skewed-t）
```

**优先级3：Ljung-Box自相关**
```
为什么ARMA(2,1)仍有自相关？
→ 测试ARMA(3,1)或ARMA(1,2)
→ 或添加return lag到mean equation
→ 检查数据是否有特殊结构（市场微观结构效应）
```

## 经济直觉

### Tone系数的含义（或缺失）

目前结果表明：
- **Tone effect ≈ 0** across all indices and definitions
- 这可能意味着：
  1. PBOC货币政策沟通对股票市场没有直接影响
  2. 市场有效性强（政策消息已完全被定价）
  3. Tone指标测量不当（错过了真正相关的政策维度）
  4. 因果关系反向（股市变化 → 央行tone改变，而非相反）
  5. 滞后效应（政策tone的影响延迟）

### 下一步论文方向

如果继续改进模型仍无tone效应：
- "Central Bank communication has limited direct impact on stock market returns"
- "PBOC tone reflects market conditions rather than drives them"
- "Policy transmission mechanism operates through different channels (credit, currency, expectations)"

## 技术总结

| 改进尝试 | 结果 | 状态 |
|--------|------|------|
| ARMA(0,0) | Ljung-Box: 3/4 indices fail | ❌ Baseline问题 |
| ARMA(1,1) | Ljung-Box: 4/4 indices fail | ❌ 恶化 |
| ARMA(2,1) | Ljung-Box: 4/4 indices fail | ❌ 无改进 |
| tone_all_z | Ljung-Box: 4/4 indices fail | ❌ 无改进 |
| Standardize regs | Numerical instability | ❌ 不可行 |
| **Conclusion** | Model misspecification fundamental | ⚠️ 需要重新思考 |

---

**建议**：在进行更多无效的改进之前，直接跳到**滚动窗口分析**来理解参数不稳定性的来源。这可能比增加更多参数更有启发性。
