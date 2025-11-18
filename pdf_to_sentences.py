import os
import re
import glob
import pdfplumber
import pandas as pd


# ========= 配置区域（你可以按需修改） =========

INPUT_DIR = "./2001-2024央行货币政策"       # 放 PDF 的文件夹
OUTPUT_CSV = "all_sentences.csv"  # 输出的句子级 CSV 文件
MIN_SENT_LEN = 4                  # 过滤过短句子（字数）



# ========= 工具函数 =========

def infer_year_quarter_from_filename(filename: str):
    """
    从文件名中尽量猜 year 和 quarter。
    规则：
      - 年份：匹配 4 位数字，如 2001, 2015
      - 季度：
          * Q1/Q2/Q3/Q4
          * '第一季度' '第二季度' 等中文
    如果没匹配到，就返回 (None, None)，后面你可以手动修。
    """
    basename = os.path.basename(filename)

    # 年份
    year_match = re.search(r'(20\d{2})', basename)
    year = int(year_match.group(1)) if year_match else None

    # 季度
    quarter = None

    # 形式一：Q1 / Q2 / Q3 / Q4
    q_match = re.search(r'[Qq]([1-4])', basename)
    if q_match:
        quarter = int(q_match.group(1))

    # 形式二：中文“第一季度”
    if quarter is None:
        chinese_q_map = {
            "一": 1, "二": 2, "三": 3, "四": 4
        }
        cq_match = re.search(r'第([一二三四])季度', basename)
        if cq_match:
            c = cq_match.group(1)
            quarter = chinese_q_map.get(c, None)

    if year is None or quarter is None:
        print(f"[警告] 无法从文件名推断年份或季度：{basename} -> year={year}, quarter={quarter}")

    return year, quarter


def extract_text_from_pdf(path: str) -> str:
    """
    使用 pdfplumber 提取整份 PDF 的纯文本。
    """
    text = ""
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text += page_text + "\n"
    return text


def extract_sections(full_text: str):
    """
    根据 '第X部分' 自动切分 S1~S5 章节。
    返回 dict: {"S1": text, "S2": text, ...}
    """
    pattern = r"(第[一二三四五]部分[^\n]*)"
    matches = list(re.finditer(pattern, full_text))

    if len(matches) == 0:
        print("[警告] 未找到任何 '第X部分' 章节标题，可能需要手动检查该文档格式。")
        return {}

    key_map = {
        "第一部分": "S1",
        "第二部分": "S2",
        "第三部分": "S3",
        "第四部分": "S4",
        "第五部分": "S5",
    }

    sections = {}

    for idx, m in enumerate(matches):
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(full_text)
        header_line = m.group(1)  # 如 '第一部分  货币信贷概况 ......1'

        part_key = None
        for k, sk in key_map.items():
            if k in header_line:
                part_key = sk
                break

        if part_key is None:
            print(f"[提示] 未能识别章节头：{header_line}")
            continue

        chunk = full_text[start:end]
        # 如果一个 Sx 出现多次（目录 + 正文），可以拼接
        if part_key in sections:
            sections[part_key] += "\n" + chunk
        else:
            sections[part_key] = chunk

    return sections


def split_sentences(text: str):
    """
    简单的中文句子切分：按 。！？ 分句，保留这些标点。
    """
    # 先替换掉一些奇怪的空白
    text = text.replace("\u3000", " ")  # 全角空格
    # 按句号/问号/叹号切分，并保留分隔符
    # (?<=[。！？])：匹配这些符号后的位置
    raw_sents = re.split(r'(?<=[。！？])', text)

    sents = []
    for s in raw_sents:
        s = s.strip()
        if not s:
            continue
        if len(s) < MIN_SENT_LEN:
            continue
        sents.append(s)
    return sents


def is_toc_like(sent: str) -> bool:
    """
    粗略过滤目录/页眉页脚等无用句子。
    规则：
      - 含大量 '.' 或 '…'
      - 含 '目录'
      - 末尾是页码
    """
    if "目录" in sent:
        return True
    # 很多点或省略号
    if sent.count(".") + sent.count("…") > 5:
        return True
    # 末尾是纯数字（可能是页码）
    if re.search(r'\d{1,3}\s*$', sent):
        return True
    return False


# ========= 主流程 =========

def process_all_pdfs(input_dir: str, output_csv: str):
    pdf_files = sorted(glob.glob(os.path.join(input_dir, "*.pdf")))
    if not pdf_files:
        print(f"[错误] 在目录 {input_dir} 中未找到任何 PDF 文件。")
        return

    all_rows = []

    for pdf_path in pdf_files:
        basename = os.path.basename(pdf_path)
        print(f"\n[处理] {basename}")

        year, quarter = infer_year_quarter_from_filename(pdf_path)
        if year is None or quarter is None:
            print(f"[警告] 跳过该文件（你也可以选择继续处理并手动填补年份/季度）：{basename}")
            # 这里你也可以选择继续处理，只是先给个提醒
            # 我这里选择继续处理，只是 year/quarter 可能为 None
            # continue

        # 1) 提取全文文本
        full_text = extract_text_from_pdf(pdf_path)

        # 2) 按章节切分
        sections = extract_sections(full_text)
        if not sections:
            print(f"[警告] 未成功切分章节：{basename}，将整篇视为 S_all")
            # 若完全无法切分，作为一个整体章节 S_all
            sections = {"S_all": full_text}

        # 3) 对每个章节切句 & 过滤
        for sec_key, sec_text in sections.items():
            sentences = split_sentences(sec_text)
            for s in sentences:
                if is_toc_like(s):
                    continue
                all_rows.append({
                    "year": year,
                    "quarter": quarter,
                    "section": sec_key,
                    "text": s.strip()
                })

    # 4) 汇总为 DataFrame 并导出 CSV
    df = pd.DataFrame(all_rows)
    print(f"\n[信息] 共得到句子数：{len(df)}")
    df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"[完成] 已保存为 {output_csv}")


if __name__ == "__main__":
    process_all_pdfs(INPUT_DIR, OUTPUT_CSV)
