````markdown
# 项目简介

这是一个用于从公司/季度报告文本构建宏观/事件驱动回归面板的处理流水线，包含：
- 文本情感打分（RoBERTa / 词典方法）
- 文本方差/相似度指标（TF‑IDF、可读性）
- 宏观控制变量处理
- 最终合并到日度 EGARCH 回归面板

## 当前目录（已重构）

- `data/raw/`：原始输入数据（CSV / XLSX）。
- `scripts/`：所有数据处理脚本（`build_*.py`, `run_*.py`, `run_egarch.r`）。
- `results/`：脚本输出（例如 `results/egarch/`, `results/macro/`）。
- `archive/`：历史实验和旧版本数据（保留以防需要回溯）。
- `__pycache__/`：Python 缓存（可忽略）。

> 我已将原先散乱的文件归档并把处理脚本统一放在 `scripts/`，数据放在 `data/raw/`，结果放在 `results/`。

## 快速开始（推荐）

1. 进入项目目录：

```bash
cd /Users/kenxiong/Desktop/硕士毕业论文/code
```

2. 创建并激活虚拟环境（如果还没创建）：

```bash
python3 -m venv .venv
source .venv/bin/activate
```

3. 安装依赖：

```bash
pip install -r requirements.txt
```

4. 运行完整预处理流水线（Python）：

```bash
python scripts/make_final_dataset.py
```

5. 运行 EGARCH 回归（R 脚本）：

```bash
Rscript scripts/run_egarch.r
```

## 常用脚本说明

- `scripts/build_roberta_tone.py`：从句子级 RoBERTa 评分聚合到季度层面。
- `scripts/build_variance_indicators.py`：计算 TF‑IDF 相似度、惊吓指数、可读性等指标。
- `scripts/build_macro_controls.py`：处理并生成日度宏观控制变量（`data/raw/macro_controls_daily.csv`）。
- `scripts/build_egarch_dataset.py`：把事件日映射到日度数据，生成 `results/egarch/` 下的回归面板。
- `scripts/make_final_dataset.py`：按顺序运行上述步骤，生成最终数据集。

## 注意事项

- 脚本内部已统一改为使用相对路径：
	```python
	BASE_DIR = Path(__file__).resolve().parents[1]
	DATA_RAW = BASE_DIR / "data" / "raw"
	```
- 如果要迁移仓库位置，确保相对路径关系不变或相应更新 `BASE_DIR` 的计算方式。
- 我已经修复了脚本中的路径问题并验证了流水线（4 个步骤）能完整运行。

## 清理与版本控制

- 如果不需要历史实验，请在确认后删除 `archive/` 下对应子目录。
- 推荐在重要变更后用 `git` 提交：

```bash
git add .
git commit -m "chore: reorganize project structure and fix script paths"
```

## 如果需要我帮忙

- 我可以：运行完整 pipeline、把脚本封装为可复用模块、或把 `scripts/` 打包为一个 Python package。

````
