import sys
import time
from pathlib import Path
import argparse

# ✅ 确保同目录脚本可 import（无论你从哪里运行）
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

try:
    import build_event_shocks_daily          # 你最新的那版：survey.xlsx + S_Policy.xlsx -> gdp_events.csv/policy_events.csv
    import build_roberta_tone                # all_sentences_with_roberta_score.csv -> tone_by_quarter_roberta.csv
    import build_variance_indicators         # tone_by_quarter_roberta.csv -> (覆盖写回，新增 similarity/surprise/readability 等)
    import build_macro_controls              # 控制变量.csv -> macro_controls_daily.csv（可选）
    import build_egarch_dataset              # 合并所有数据 -> egarch_daily_data_roberta.csv
except ImportError as e:
    print("❌ 导入模块失败！请确保以下文件都在当前目录下：")
    print("   - build_event_shocks_daily.py")
    print("   - build_roberta_tone.py")
    print("   - build_variance_indicators.py")
    print("   - build_macro_controls.py (可选)")
    print("   - build_egarch_dataset.py")
    print(f"错误详情: {e}")
    sys.exit(1)


def print_step(step_num, desc):
    print("\n" + "=" * 60)
    print(f"👉 Step {step_num}: {desc}")
    print("=" * 60)


def run_main_with_argv(module, argv_list):
    """
    某些脚本（如 build_event_shocks_daily.py）用 argparse 读取 sys.argv
    这里临时替换 sys.argv，确保它按我们传入的参数运行，不跟本脚本的参数冲突
    """
    old_argv = sys.argv[:]
    try:
        sys.argv = [f"{module.__name__}.py"] + argv_list
        module.main()
    finally:
        sys.argv = old_argv


def main():
    parser = argparse.ArgumentParser(description="One-click pipeline to build final EGARCH dataset.")
    parser.add_argument("--survey_xlsx", default="survey.xlsx", help="Bloomberg survey file (GDP).")
    parser.add_argument("--spolicy_xlsx", default="S_Policy.xlsx", help="S_Policy file (policy tools + interbank 7d).")
    parser.add_argument("--start_year", type=int, default=2001, help="Min year kept in GDP events (by obs_date quarter).")

    parser.add_argument("--include_lpr_in_D_policy", action="store_true",
                        help="Include LPR 1Y into D_policy (announce-first else change-point).")

    # 跳过项（方便你调试/节省时间）
    parser.add_argument("--skip_events", action="store_true", help="Skip building gdp_events/policy_events.")
    parser.add_argument("--skip_text", action="store_true", help="Skip building tone & variance indicators.")
    parser.add_argument("--skip_macro", action="store_true", help="Skip macro controls step.")
    parser.add_argument("--require_macro", action="store_true",
                        help="Fail if macro controls step cannot run (default: skip if missing).")

    args = parser.parse_args()

    start_time = time.time()
    print("🚀 开始构建最终回归数据集流水线...\n")

    # ==========================================================
    # Step 0: 事件冲击（GDP/Policy）——与你最近的改动联动的关键步骤
    # ==========================================================
    if not args.skip_events:
        print_step(0, "构建事件冲击：GDP(公布日) + Policy(公告日优先/变动点兜底)")
        # 输出写到 scripts/ 目录，保证 build_egarch_dataset.py 能优先 resolve 到
        out_dir = str(SCRIPT_DIR)

        ev_argv = [
            "--survey_xlsx", str(Path(args.survey_xlsx)),
            "--spolicy_xlsx", str(Path(args.spolicy_xlsx)),
            "--out_dir", out_dir,
            "--start_year", str(args.start_year),
        ]
        if args.include_lpr_in_D_policy:
            ev_argv.append("--include_lpr_in_D_policy")

        try:
            run_main_with_argv(build_event_shocks_daily, ev_argv)
        except Exception as e:
            print(f"❌ Step 0 失败: {e}")
            return
    else:
        print_step(0, "跳过事件冲击构建（使用现有 gdp_events.csv / policy_events.csv）")

    # ==========================================================
    # Step 1-2: 文本变量（你原来的流程）
    # ==========================================================
    if not args.skip_text:
        print_step(1, "聚合 RoBERTa 情绪指标 (Real/Guidance)")
        try:
            build_roberta_tone.main()
        except Exception as e:
            print(f"❌ Step 1 失败: {e}")
            return

        print_step(2, "计算 TF-IDF 惊吓指数与可读性指标")
        try:
            build_variance_indicators.main()
        except Exception as e:
            print(f"❌ Step 2 失败: {e}")
            return
    else:
        print_step(1, "跳过文本变量构建（使用现有 tone_by_quarter_roberta.csv）")

    # ==========================================================
    # Step 3: 宏观控制变量（建议默认“有就跑、没有就跳过”）
    # ==========================================================
    if not args.skip_macro:
        print_step(3, "处理宏观控制变量（可选）")
        try:
            build_macro_controls.main()
        except Exception as e:
            if args.require_macro:
                print(f"❌ Step 3 失败(已设置 require_macro): {e}")
                print("💡 提示: 请检查目录下是否有 '控制变量.csv'")
                return
            else:
                print(f"⚠️ Step 3 跳过（宏观控制变量不可用）: {e}")
                print("   将继续生成 EGARCH 面板（build_egarch_dataset.py 会自动忽略缺失的 macro_controls_daily.csv）")
    else:
        print_step(3, "跳过宏观控制变量构建")

    # ==========================================================
    # Step 4: 合并所有数据生成 EGARCH 面板
    # ==========================================================
    print_step(4, "合并所有数据 -> 生成最终回归面板")
    try:
        build_egarch_dataset.main()
    except Exception as e:
        print(f"❌ Step 4 失败: {e}")
        return

    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print(f"✅ 流水线执行完毕！总耗时: {elapsed:.2f} 秒")
    print("最终文件已生成: egarch_daily_data_roberta.csv")
    print("接下来请运行: run_egarch.r")
    print("=" * 60)


if __name__ == "__main__":
    main()
