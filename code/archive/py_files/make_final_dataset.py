import os
import time
import sys

# 导入你的四个处理脚本作为模块
# 注意：文件名必须与 import 后面的名字一致（不带 .py）
try:
    import build_roberta_tone
    import build_variance_indicators
    import build_macro_controls
    import build_egarch_dataset
except ImportError as e:
    print("❌ 导入模块失败！请确保以下文件都在当前目录下：")
    print("   - build_roberta_tone.py")
    print("   - build_variance_indicators.py")
    print("   - build_macro_controls.py")
    print("   - build_egarch_dataset.py")
    print(f"错误详情: {e}")
    sys.exit(1)

def print_step(step_num, desc):
    print("\n" + "="*60)
    print(f"👉 Step {step_num}: {desc}")
    print("="*60)

def main():
    start_time = time.time()
    print("🚀 开始构建最终回归数据集流水线...\n")

    # ==========================================
    # Step 1: 聚合基础情绪指标 (RoBERTa -> Quarterly)
    # ==========================================
    print_step(1, "聚合 RoBERTa 情绪指标 (Real/Guidance)")
    # 依赖输入: all_sentences_with_roberta_score.csv
    # 输出: tone_by_quarter_roberta.csv
    try:
        build_roberta_tone.main()
    except Exception as e:
        print(f"❌ Step 1 失败: {e}")
        return

    # ==========================================
    # Step 2: 计算高级波动率指标 (TF-IDF Surprise + Readability)
    # ==========================================
    print_step(2, "计算 TF-IDF 惊吓指数与可读性指标")
    # 依赖输入: tone_by_quarter_roberta.csv (上一步生成的)
    # 输出: 覆盖 tone_by_quarter_roberta.csv (新增列)
    try:
        build_variance_indicators.main()
    except Exception as e:
        print(f"❌ Step 2 失败: {e}")
        return

    # ==========================================
    # Step 3: 处理宏观控制变量 (利率/汇率)
    # ==========================================
    print_step(3, "处理宏观控制变量")
    # 依赖输入: 控制变量.csv (Wind 原始数据)
    # 输出: macro_controls_daily.csv
    try:
        build_macro_controls.main()
    except Exception as e:
        print(f"❌ Step 3 失败: {e}")
        print("💡 提示: 请检查目录下是否有 '控制变量.csv'")
        return

    # ==========================================
    # Step 4: 合并所有数据生成 EGARCH 面板
    # ==========================================
    print_step(4, "合并所有数据 -> 生成最终回归面板")
    # 依赖输入: 
    #   - daily_returns_4idx.csv
    #   - tone_by_quarter_roberta.csv (Step 2 产出)
    #   - macro_controls_daily.csv (Step 3 产出)
    #   - report_dates.csv
    # 输出: egarch_daily_data_roberta.csv
    try:
        build_egarch_dataset.main()
    except Exception as e:
        print(f"❌ Step 4 失败: {e}")
        return

    # ==========================================
    # 完成
    # ==========================================
    elapsed = time.time() - start_time
    print("\n" + "="*60)
    print(f"✅ 流水线执行完毕！总耗时: {elapsed:.2f} 秒")
    print("最终文件已生成: egarch_daily_data_roberta.csv")
    print("接下来请直接运行: run_egarch.py")
    print("="*60)

if __name__ == "__main__":
    main()