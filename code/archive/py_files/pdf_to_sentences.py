import os
import re
import glob
import pdfplumber
import pandas as pd

# ========= 配置 =========
# 把这里改成你本地存放所有 PDF 的目录
INPUT_DIR = "/Users/kenxiong/Desktop/硕士毕业论文/code/2001-2024央行货币政策"        # 所有 PDF 的目录
OUTPUT_CSV = "/Users/kenxiong/Desktop/硕士毕业论文/code/all_sentences.csv"   # 输出的 CSV 文件名
MIN_SENT_LEN = 3                   # 最短保留句子长度（字符数）


# ========= 工具函数 =========

def infer_year_quarter_from_filename(filename: str):
    """
    从文件名中推断年份和季度。
    例：2001第一季度.pdf, 2015Q3_货币政策执行报告.pdf
    """
    basename = os.path.basename(filename)

    # 年份
    year_match = re.search(r'(20\d{2})', basename)
    year = int(year_match.group(1)) if year_match else None

    # 季度
    quarter = None
    # Q1 / Q2 / Q3 / Q4
    q_match = re.search(r'[Qq]([1-4])', basename)
    if q_match:
        quarter = int(q_match.group(1))
    # “第一季度 / 第二季度 …”
    if quarter is None:
        chinese_q_map = {"一": 1, "二": 2, "三": 3, "四": 4}
        cq_match = re.search(r'第([一二三四])季度', basename)
        if cq_match:
            quarter = chinese_q_map.get(cq_match.group(1))

    if year is None or quarter is None:
        print(f"[警告] 无法从文件名推断 year/quarter：{basename} -> year={year}, quarter={quarter}")
    return year, quarter


def extract_pages_text(path: str):
    """
    返回一个 list，每个元素是一页的文本。
    对有问题的页面做 try/except，避免整份报告崩掉。
    """
    texts = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            try:
                page_text = page.extract_text(layout=True) or ""
            except Exception as e:
                print(f"[警告] 解析 {os.path.basename(path)} 第 {i} 页失败：{e}，跳过该页。")
                page_text = ""
            texts.append(page_text)
    return texts


def is_toc_page(text: str) -> bool:
    """
    粗略判断是否为目录页：
      - 前几百字符里包含“目录/目 录”
      - 同时出现“第X部分”
    """
    head = text[:300]
    if ("目录" in head or "目 录" in head) and re.search(r"第[一二三四五]部分", head):
        return True
    return False


def clean_section_chunk(chunk: str) -> str:
    """
    对一个章节的原始文本块做行级清洗：
      - 去掉以“第X部分”开头的标题行
      - 去掉以“[一二三…]、”开头且没有“。”/“：”的目录行
      - 去掉含“表/图/专栏”且带大量点号、但没有句号的目录行（包括 IV 专栏 专栏 1 ... 这种）
    """
    lines = [l.strip() for l in chunk.splitlines() if l.strip()]
    cleaned = []

    for l in lines:
        # 1) 章节标题行：例如“第一部分 货币政策分析”
        if re.match(r"^第[一二三四五]部分", l):
            continue

        # 2) 小目录行：例如“二、一季度主要货币政策措施……47”
        #    特征：以“X、”开头，且不含句号/冒号
        if re.match(r"^[一二三四五六七八九十]、", l) and "。" not in l and "：" not in l:
            continue

        # 3) 更通用的目录/专栏列表行：
        #   含“表/图/专栏” + 很多点号 + 没有句号
        dot_count = l.count(".") + l.count("…")
        has_table_kw = ("表" in l or "图" in l or "专栏" in l)
        if has_table_kw and dot_count > 5 and "。" not in l:
            # 覆盖“IV 专栏 专栏 1 ......”这类行
            continue

        cleaned.append(l)

    return "\n".join(cleaned)



def extract_sections_from_body(body_text: str, filename: str):
    """
    在已经去掉目录页的文本上，按“第X部分”切分为 S1~S5。
    对每个章节块调用 clean_section_chunk，剥离标题行和小目录行。
    返回 dict: {"S1": text, "S2": text, ...}
    """
    pattern = r"(第[一二三四五]部分[^\n]*)"
    matches = list(re.finditer(pattern, body_text))

    if len(matches) == 0:
        print(f"[警告] {filename} 未找到任何“第X部分”，整篇作为 S_all。")
        return {"S_all": body_text}

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
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(body_text)
        header_line = m.group(1)

        part_key = None
        for k, sk in key_map.items():
            if k in header_line:
                part_key = sk
                break

        if part_key is None:
            print(f"[提示] {filename} 遇到无法识别的章节头：{header_line}")
            continue

        raw_chunk = body_text[start:end]
        chunk = clean_section_chunk(raw_chunk)

        if part_key in sections:
            sections[part_key] += "\n" + chunk
        else:
            sections[part_key] = chunk

    return sections


def split_sentences(text: str):
    """
    把各种空白（空格、换行、制表符）压成一个空格，再按句号/问号/叹号切句。
    """
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text)  # 所有空白压成一个空格
    # 按句号/问号/叹号切句，保留标点
    raw_sents = re.split(r"(?<=[。！？])", text)

    sents = []
    for s in raw_sents:
        s = s.strip()
        if not s:
            continue
        if len(s) < MIN_SENT_LEN:
            continue
        sents.append(s)
    return sents


def is_noise_sentence(sent: str) -> bool:
    """
    过滤明显没用的“垃圾”句子：
      - 含目录关键字
      - 极短
      - 纯数字或几乎都是数字（表格行）
    """
    s = sent.strip()
    if not s:
        return True

    # 目录句
    if "目录" in s or "目 录" in s:
        return True

    # 极短碎片
    if len(s) <= 2:
        return True

    # 统计中文和数字数量
    chinese_chars = sum(1 for ch in s if '\u4e00' <= ch <= '\u9fff')
    digits = sum(1 for ch in s if ch.isdigit())

    # 没有中文、只有数字/符号 → 高概率是表格噪音
    if chinese_chars == 0 and digits > 0:
        return True

    # 中文很少、数字很多，且句子不长 → 大概率是表格
    if digits > 0 and chinese_chars > 0:
        if digits / (digits + chinese_chars) > 0.7 and len(s) < 30:
            return True

    return False


# ========= 主流程 =========

def process_all_pdfs(input_dir: str, output_csv: str):
    pdf_files = sorted(glob.glob(os.path.join(input_dir, "*.pdf")))
    if not pdf_files:
        print(f"[错误] 在目录 {input_dir} 中未找到任何 PDF 文件。")
        return

    all_rows = []
    global_id = 1  # 全局句子 ID

    for pdf_path in pdf_files:
        basename = os.path.basename(pdf_path)
        print(f"\n[处理] {basename}")

        year, quarter = infer_year_quarter_from_filename(pdf_path)
        if year is None or quarter is None:
            print(f"[警告] {basename} year/quarter 未识别，将 year/quarter 设为 None。")

        # 1) 每页文本
        page_texts = extract_pages_text(pdf_path)

        # 2) 去掉目录页
        body_pages = []
        for i, t in enumerate(page_texts, start=1):
            if is_toc_page(t):
                print(f"[提示] {basename} 第 {i} 页识别为目录页，已剔除。")
                continue
            body_pages.append(t)

        if not body_pages:
            print(f"[警告] {basename} 所有页面都被识别为目录或空白，跳过该文件。")
            continue

        body_text = "\n".join(body_pages)

        # 3) 章节切分
        sections = extract_sections_from_body(body_text, basename)
        if not sections:
            print(f"[警告] {basename} 章节切分结果为空，跳过该文件。")
            continue

        # 4) 对每个章节切句
        file_sentence_count = 0
        sent_id_in_report = 1  # 报告内部的句子顺序 ID

        for sec_key, sec_text in sections.items():
            sentences = split_sentences(sec_text)
            for s in sentences:
                if is_noise_sentence(s):
                    continue
                all_rows.append({
                    "id": global_id,
                    "year": year,
                    "quarter": quarter,
                    "section": sec_key,
                    "sent_id_in_report": sent_id_in_report,
                    "text": s.strip()
                })
                global_id += 1
                sent_id_in_report += 1
                file_sentence_count += 1

        print(f"[信息] {basename} 抽取句子数：{file_sentence_count}")

    # 5) 汇总导出
    df = pd.DataFrame(all_rows)
    print(f"\n[总计] 共得到句子数：{len(df)}")
    try:
        print(df.groupby(['year', 'quarter'])['text'].count().describe())
    except Exception:
        pass
    df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"[完成] 已保存为 {output_csv}")


if __name__ == "__main__":
    process_all_pdfs(INPUT_DIR, OUTPUT_CSV)
