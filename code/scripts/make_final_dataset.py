# make_final_dataset.py
# -*- coding: utf-8 -*-
"""
一键自动化流水线：后半程 (Post-NLP Pipeline)

前提：
  你必须已经跑完了 roberta_pipeline.py 和 build_roberta_tone.py，
  有了 tone_by_quarter_roberta.csv (基础版)。

本脚本会自动执行：
  1. build_variance_indicators.py -> 计算相似度和可读性，填入季度文件
  2. build_event_shocks_daily.py  -> 生成 GDP 和 Policy 外部冲击事件
  3. build_macro_controls.py      -> 生成日度宏观控制变量 (容错)
  4. build_egarch_dataset.py      -> 最终合并，生成 egarch_daily_data_roberta.csv
"""

import sys
import subprocess
from pathlib import Path

def run_step(script_name, description):
    print("\n" + "="*60)
    print(f"🚀 正在执行: {description}")
    print(f"   脚本: {script_name}")
    print("="*60)
    
    script_path = Path(__file__).parent / script_name
    if not script_path.exists():
        print(f"❌ 找不到文件: {script_name}")
        return False
        
    try:
        # 使用 subprocess 调用，保证环境隔离，避免变量污染
        result = subprocess.run(
            [sys.executable, str(script_path)],
            check=True
        )
        print(f"✅ {script_name} 执行成功！")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {script_name} 执行失败 (Exit Code: {e.returncode})")
        return False
    except Exception as e:
        print(f"❌ 发生未知错误: {e}")
        return False

def main():
    print(">>> 启动后半程数据构建流水线 (Post-NLP Pipeline) <<<\n")
    
    # 1. 检查前提条件
    tone_file = Path("tone_by_quarter_roberta.csv")
    if not tone_file.exists():
        print(f"⚠️ 警告: 没找到 {tone_file}。")
        print("   通常你需要先运行 build_roberta_tone.py。")
        print("   但如果你确信你改了文件名，可以忽略此提示。")
        # 这里不强制退出，因为也许你在 build_roberta_tone 里改了输出路径
        
    # ==========================================
    # 2. 补充方差指标 (Similarity / Readability)
    # ==========================================
    # 这一步会修改 tone_by_quarter_roberta.csv
    if not run_step("build_variance_indicators.py", "计算文本相似度与可读性"):
        print("⚠️ 相似度计算失败，后续方差方程可能缺变量。")

    # ==========================================
    # 3. 生成外部冲击 (GDP / Policy Events)
    # ==========================================
    # 这一步生成 gdp_events.csv 和 policy_events.csv
    # build_egarch_dataset 强依赖这个
    if not run_step("build_event_shocks_daily.py", "生成 GDP 和 Policy 外部冲击事件"):
        print("❌ 严重: 外部冲击生成失败，回归模型将缺少核心变量 S_policy！")
        user_input = input("是否继续？(y/n): ")
        if user_input.lower() != 'y':
            sys.exit(1)

    # ==========================================
    # 4. 生成宏观控制变量 (Macro Controls)
    # ==========================================
    # 这一步生成 macro_controls_daily.csv
    if not run_step("build_macro_controls.py", "生成日度宏观控制变量"):
        print("⚠️ 宏观变量生成失败，回归模型将缺少控制变量。")

    # ==========================================
    # 5. 最终合并 (Final Merge)
    # ==========================================
    if run_step("build_egarch_dataset.py", "最终数据合并 (生成回归面板)"):
        print("\n" + "*"*60)
        print("🎉🎉🎉 全部完成！ 🎉🎉🎉")
        print("现在你可以去 R 语言里运行 run_egarch.r 了。")
        print("输出文件: egarch_daily_data_roberta.csv")
        print("*"*60)
    else:
        print("\n❌ 最终合并失败，请检查上方报错信息。")

if __name__ == "__main__":
    main()