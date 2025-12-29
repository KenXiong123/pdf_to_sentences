import os
import re
import glob
from collections import Counter
import pdfplumber
import pandas as pd

# ========= 配置 =========
# 把这里改成你本地存放所有 PDF 的目录
INPUT_DIR = "/Users/kenxiong/Desktop/硕士毕业论文/code/archive/2001-2024央行货币政策"        # 所有 PDF 的目录
OUTPUT_CSV = "/Users/kenxiong/Desktop/硕士毕业论文/code/scripts/all_sentences.csv"   # 输出的 CSV 文件名
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
    更鲁棒地识别“目录/章节列表页”（很多报告目录页不一定写“目录”）：
      1) 前几百字符包含“目录/目 录”，且出现“第X部分”
      2) 或者：页面里有大量“点线/省略号 + 页码”的行（典型目录样式）
      3) 或者：短页内出现多次“第X部分”，且伴随明显目录样式
    """
    head = text[:800]
    if ("目录" in head or "目 录" in head) and re.search(r"第[一二三四五]部分", head):
        return True

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) < 12:
        return False

    # 目录典型：大量“……/..... + 页码”
    dotleader_lines = [
        l for l in lines
        if re.search(r"(\.{4,}|…{2,})\s*\d+\s*$", l)
    ]
    ratio = len(dotleader_lines) / max(len(lines), 1)

    if len(dotleader_lines) >= 8 and ratio >= 0.25:
        return True

    # 某些目录页没有点线，但会在一页内密集列出“第一部分…第五部分”
    if len(re.findall(r"第[一二三四五]部分", head)) >= 3 and len(dotleader_lines) >= 4:
        return True

    return False


def normalize_line(l: str) -> str:
    """
    对单行文本做轻量清洗，重点去掉“点线+页码”、页眉页脚残留。
    额外处理：去除 pdf 布局造成的“.../……”断裂符，以及中文/数字之间的多余空格。
    """
    if not l:
        return l
    s = l.strip()

    # 去掉开头的点线/省略号/项目符号等 + 页码（目录/页眉）
    s = re.sub(r'^[\.·•…\s]{3,}\s*\d+\s*', '', s)

    # 去掉“点线+页码”（目录条目常见）
    s = re.sub(r'(\.{3,}|…{2,})\s*\d+\s*$', '', s).strip()
    s = re.sub(r'(\.{3,}|…{2,})\s*\d+\s+', ' ', s).strip()

    # 删除正文中偶发的“.../……”（通常是 PDF 提取断裂符）
    s = re.sub(r'(\.{3,}|…{2,})', '', s)

    # 去掉常见“第X页 / Page X”残留
    s = re.sub(r'(第\s*\d+\s*页|Page\s*\d+)', ' ', s, flags=re.IGNORECASE).strip()

    # 去掉行首孤立页码（例如 “24 一是……”）
    s = re.sub(r'^\d{1,3}\s+(?=[\u4e00-\u9fff（(])', '', s)

    # 去掉中文之间、数字与中文之间的多余空格（提升可读性/降低污染）
    s = re.sub(r'(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])', '', s)
    s = re.sub(r'(?<=\d)\s+(?=[\u4e00-\u9fff])', '', s)
    s = re.sub(r'(?<=[\u4e00-\u9fff])\s+(?=\d)', '', s)

    # 统一空白
    s = re.sub(r'\s+', ' ', s).strip()
    return s



def _is_roman_pageno(l: str) -> bool:
    # 前言部分经常出现 I/II/III/IV … 或单独“1”“2”
    if re.fullmatch(r"[IVX]{1,8}", l):
        return True
    if re.fullmatch(r"\d{1,4}", l):
        return True
    return False


def clean_section_chunk(chunk: str) -> str:
    """
    对一个章节的原始文本块做行级清洗：
      - 去掉以“第X部分”开头的标题行（但标题会在 extract_sections_from_body 里保留）
      - 去掉目录/列表行（含多位中文序号，如“十一、”）
      - 去掉含“表/图/专栏”或“点线+页码”的目录样式残留
      - 去掉纯页码/孤立数字、罗马数字页码
      - 尽可能提前剔除“图/表标题、数据来源、注释”等（避免和正文粘连）
    """
    raw_lines = chunk.splitlines()
    lines = [normalize_line(l) for l in raw_lines]
    lines = [l for l in lines if l and l.strip()]
    cleaned = []

    for l in lines:
        # 0) 罗马页码 / 纯页码
        if _is_roman_pageno(l):
            continue

        # 1) 章节标题行：例如“第一部分 货币政策分析”
        if re.match(r"^第[一二三四五]部分", l):
            continue

        # 2) 目录/小标题列表行（多位中文序号也要匹配：十一、十二、…）
        if re.match(r"^[一二三四五六七八九十]+、", l) and ("。" not in l and "：" not in l and "；" not in l):
            continue
        if re.match(r"^\(?[一二三四五六七八九十]+\)?", l) and ("。" not in l and "：" not in l and "；" not in l):
            # 兜底：形如“(一)”“（二）”的纯标题行
            if len(l) <= 30:
                continue

        # 3) 目录式点线残留（normalize_line 可能已去掉点线，但仍可能残留很多点/省略号）
        dot_count = l.count(".") + l.count("…")
        if dot_count >= 6 and ("。" not in l and "：" not in l):
            continue

        # 4) “表/图/专栏/目录列表行”（标题行经常非常短，且不是正文句）
        if re.match(r"^(表|图|专栏)\s*\d+", l) and len(l) <= 120:
            continue
        if re.match(r"^(数据来源|资料来源|来源|注|说明)\s*[：:]", l) and len(l) <= 120:
            continue

        # 5) 更通用的目录/专栏列表行：含“表/图/专栏”且基本无正文标点
        has_table_kw = ("表" in l or "图" in l or "专栏" in l)
        if has_table_kw and ("。" not in l and "：" not in l) and len(l) <= 60:
            continue

        cleaned.append(l)

    return "\n".join(cleaned)


def extract_sections_from_body(body_text: str, filename: str):
    """
    在已经去掉目录页的文本上，按“第X部分”切分为 S1~S5。
    返回 dict: {"S1": {"title":..., "text":...}, ...}
    """
    pattern = r"(第[一二三四五]部分[^\n]*)"
    matches = list(re.finditer(pattern, body_text))

    if len(matches) == 0:
        print(f"[警告] {filename} 未找到任何“第X部分”，整篇作为 S_all。")
        return {"S_all": {"title": "S_all", "text": body_text}}

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
        header_line = normalize_line(m.group(1))

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
            sections[part_key]["text"] += "\n" + chunk
        else:
            sections[part_key] = {"title": header_line.strip(), "text": chunk}

    return sections


def strip_leading_caption(s: str) -> str:
    """
    保留：旧逻辑兼容（只在能明确找到正文起点时截断，以免误伤）。
    """
    ss = s.strip()
    if not ss:
        return ss

    # 图/表标题粘连正文：优先从“19xx年/20xx年”处截断
    if re.match(r"^(图|表)\s*\d+", ss):
        m = re.search(r"(19|20)\d{2}年", ss)
        if m and 0 < m.start() < 120:
            return ss[m.start():].strip()

    # “IV 专栏 … 展望未来 …” 这类：从“展望/未来/总体来看”等正文引导词截断
    if re.match(r"^[IVX]{1,4}\s*专栏", ss) or ss.startswith("专栏"):
        m = re.search(r"(展望|未来|总体来看|综合来看|总的来看|下一阶段|下一步)", ss)
        if m and 0 < m.start() < 160:
            return ss[m.start():].strip()

    return ss


def postprocess_sentence(s: str) -> str:
    """
    句子级后处理：
      1) 清掉（图1）（表2）等“括号图表引用”（降低 QA 的 HAS_TABLEFIG，且不影响语义）
      2) 把“如图 8所示 / 见图 8 / 参见表 3”改写为“如下图所示 / 见下图 / 参见下表”（避免携带数字）
      3) 如果出现“... 表 7：...”这类嵌入式图表标题，从该处截断（避免正文被表标题污染）
      4) 删除“数据来源/资料来源/来源/注/说明”这类纯注释句
      5) 删除明显的“图/表标题句”（以 图/表 开头的短句）
    """
    if not s:
        return ""
    s = s.strip()
    if not s:
        return ""

    # (图 1)/(表 3)
    s = re.sub(r"[（(]\s*(图|表)\s*\d+\s*[）)]", "", s)

    # “如图 8所示”/“图 8所示”/“见图 8”
    s = re.sub(r"如\s*图\s*\d+\s*所示", "如下图所示", s)
    s = re.sub(r"图\s*\d+\s*所示", "下图所示", s)
    s = re.sub(r"(参见|见)\s*图\s*\d+", r"\1下图", s)
    s = re.sub(r"(参见|见)\s*表\s*\d+", r"\1下表", s)

    # 剩余的“图 8/表 3”一律替换为“下图/下表”（避免 QA 误报）
    s = re.sub(r"(?<!图)图\s*\d+", "下图", s)
    s = re.sub(r"(?<!表)表\s*\d+", "下表", s)

    # “表 7：...”/“图 3: ...”嵌入式标题：截断
    m = re.search(r"\s(图|表)\s*\d+\s*[：:]", s)
    if m:
        prefix = s[:m.start()].strip()
        if len(prefix) < 12:
            return ""
        s = prefix

    # 纯“数据来源/注释”句：删除
    if re.match(r"^(数据来源|资料来源|来源|注|说明)\s*[：:]", s):
        return ""

    # 以“图/表”开头的短句（大概率是图表标题/数据轴）：删除
    if re.match(r"^(图|表)\s*\d+", s) and len(s) <= 160:
        return ""

    s = re.sub(r"\s+", " ", s).strip()
    return s


def split_sentences(text: str):
    """
    把各种空白压成一个空格，再按句号/问号/叹号切句。
    注意：最终是否保留句子，以 noise_reason 为准（主流程里会过滤）。
    """
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text)  # 所有空白压成一个空格
    raw_sents = re.split(r"(?<=[。！？])", text)

    sents = []
    for s in raw_sents:
        s = s.strip()
        if not s:
            continue
        s = normalize_line(s)
        if not s:
            continue
        s = strip_leading_caption(s)
        if not s:
            continue
        s = postprocess_sentence(s)
        if not s:
            continue
        if len(s) < MIN_SENT_LEN:
            continue
        sents.append(s)
    return sents


def _count_chars(s: str):
    chinese = sum(1 for ch in s if '\u4e00' <= ch <= '\u9fff')
    digits = sum(1 for ch in s if ch.isdigit())
    latin = sum(1 for ch in s if ('a' <= ch.lower() <= 'z'))
    return chinese, digits, latin


def is_table_like(sent: str) -> bool:
    """
    更保守的“表格/图注/来源注释”判别（尽量避免误杀正文里的“12月…LPR…下降…”这类数值句）：
    1) 高置信：图/表标题、来源/注释行、单位行
    2) 结构特征：明显“列/轴”形态（大量空格分隔 token、分隔符、数字 token 非常多且中文占比低）
    3) 防误杀：若中文占比高且空格 token 很少（像正常句子），即便数字较多也不判为表格
    """
    s = (sent or "").strip()
    if not s:
        return True

    n = len(s)
    chinese, digits, latin = _count_chars(s)
    chinese_ratio = chinese / max(n, 1)
    digit_ratio = digits / max(n, 1)

    # 以空格分隔的 token 数（PDF 表格残留常见：很多 token 被空格隔开）
    space_tokens = [t for t in re.split(r"\s+", s) if t]
    n_tokens = len(space_tokens)

    num_tokens = re.findall(r"\d+(?:\.\d+)?", s)
    pct_tokens = re.findall(r"\d+(?:\.\d+)?%", s)

    # --- 高置信噪声：图表标题/来源注释/单位行 ---
    if re.match(r"^(表|图)\s*\d+", s):
        return True
    if re.match(r"^(数据来源|资料来源|来源|注|说明)\s*[：:]", s):
        return True
    if re.match(r"^单位\s*[：:]", s):
        return True

    # --- 强信号“正文句”保护：含典型叙述动词 + 句读符号 + token 不多时，不当作表格 ---
    # 例："12月，1年期和5年期以上LPR分别为…下降…" 这类是正文，不应被当作坐标轴/表格行。
    if n_tokens <= 10 and re.search(r"(同比|环比|增长|下降|上升|提高|降低|增加|减少|分别|达到|为|较上年|较上季|较上月)", s) and re.search(r"[，。；；:：]", s):
        return False


    # --- 防误杀：像正常句子就放过 ---
    # 典型正文：中文占比高 + token 不多（几乎不靠空格分列）
    if chinese_ratio >= 0.65 and n_tokens <= 8:
        # 即便数字较多，也先认为不是表格（比如“12月…LPR…下降…”）
        # 但如果仍然出现明显的表格分隔符，再另行处理（见后面规则）
        pass
    else:
        # --- 数字/百分号密度很高 + 中文较少：更像表格/坐标轴 ---
        if len(pct_tokens) >= 4 and chinese_ratio < 0.6:
            return True
        if len(num_tokens) >= 12 and (digit_ratio >= 0.25 or n_tokens >= 10) and chinese_ratio < 0.6:
            return True

        # 以数字开头且数字 token 很多：仅在“列化”特征明显时才判噪（避免误杀正文）
        if re.match(r"^\d", s) and len(num_tokens) >= 8 and (n_tokens >= 10 or chinese_ratio < 0.55) and digit_ratio >= 0.15:
            return True

        # 超长 + 中文占比低 + 数字较多：典型表格拼接行
        if n >= 70 and chinese_ratio < 0.30 and (digit_ratio > 0.15 or len(num_tokens) >= 8):
            return True

        # 大量分隔符/横线/竖线等（表格）
        if n >= 60 and chinese_ratio < 0.50:
            sep_hits = len(re.findall(r"[|│┃┆┊┇—–\-_=]{3,}", s))
            if sep_hits >= 1:
                return True

    # --- 表头/项目清单类：token 很多 + 几乎无句末标点 ---
    if n_tokens >= 14 and not re.search(r"[。！？；]", s):
        # 典型表头经常包含“单位/余额/同比/增速/项目/合计”等
        if re.search(r"单位|余额|同比|增速|项目|合计|小计|其中", s) or digit_ratio > 0.10 or len(num_tokens) >= 6:
            return True

    # “来源/注” + 数字密集且中文少（图表说明行）
    if ("来源" in s or "注" in s) and n >= 25 and chinese_ratio < 0.65 and len(num_tokens) >= 6:
        return True

    # 纯数字/符号（防御性）
    if chinese == 0 and (digits > 0 or latin > 0):
        return True

    return False


def noise_reason(sent: str):
    """
    返回噪声原因（用于 QA / 计数），非噪声返回 None。
    """
    s = normalize_line(sent)
    if not s:
        return "empty"

    # 目录句
    if "目录" in s or "目 录" in s:
        return "toc"

    # 目录式点线残留（极少数会漏进来）
    if re.search(r"(\.{6,}|…{4,})", s) and ("。" not in s and "：" not in s):
        return "dotleader"

    # 极短碎片
    if len(s) <= 2:
        return "short"

    # 页码式短句
    if re.fullmatch(r"(第\s*\d+\s*页|Page\s*\d+)", s, flags=re.IGNORECASE):
        return "pageno"

    # 表格/图注/数据轴/来源注释
    if is_table_like(s):
        return "table"

    return None


def is_noise_sentence(sent: str) -> bool:
    return noise_reason(sent) is not None


def _detect_repeated_headers_footers(page_texts):
    """
    针对单份报告，识别“页眉/页脚”类重复行，并在后续页面级清洗时剔除。
    逻辑：统计每页前2行+后2行出现频次，超过 50% 的短行视为页眉/页脚。
    """
    norm_pages = []
    for t in page_texts:
        t = t or ""
        ls = [normalize_line(x) for x in t.splitlines()]
        ls = [x for x in ls if x]
        norm_pages.append(ls)

    n_pages = len(norm_pages)
    if n_pages <= 3:
        return set()

    cand = []
    for ls in norm_pages:
        if not ls:
            continue
        cand.extend(ls[:2])
        cand.extend(ls[-2:])

    freq = Counter(cand)
    threshold = max(3, int(0.5 * n_pages))
    banned = set()
    for line, c in freq.items():
        if c >= threshold and 2 <= len(line) <= 50:
            # 不要误杀章节标题
            if re.search(r"第[一二三四五]部分", line):
                continue
            banned.add(line)
    return banned


def _clean_page_text(t: str, banned_lines: set) -> str:
    if not t:
        return ""
    ls = [normalize_line(x) for x in t.splitlines()]
    ls = [x for x in ls if x]
    if banned_lines:
        ls = [x for x in ls if x not in banned_lines]
    # 防止残留页码/罗马页码
    ls = [x for x in ls if not _is_roman_pageno(x)]
    return "\n".join(ls)


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

        # 2) 去掉目录页 + 清理页眉页脚
        banned_lines = _detect_repeated_headers_footers(page_texts)

        body_pages = []
        for i, t in enumerate(page_texts, start=1):
            if is_toc_page(t):
                print(f"[提示] {basename} 第 {i} 页识别为目录页，已剔除。")
                continue
            cleaned_page = _clean_page_text(t, banned_lines)
            if cleaned_page.strip():
                body_pages.append(cleaned_page)

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
        total_after_split = 0
        noise_counts = {}

        for sec_key, sec_obj in sections.items():
            sec_text = sec_obj["text"] if isinstance(sec_obj, dict) else str(sec_obj)
            sec_title = sec_obj.get("title", "") if isinstance(sec_obj, dict) else ""
            sentences = split_sentences(sec_text)
            total_after_split += len(sentences)
            for s in sentences:
                reason = noise_reason(s)
                if reason is not None:
                    noise_counts[reason] = noise_counts.get(reason, 0) + 1
                    continue
                all_rows.append({
                    "id": global_id,
                    "year": year,
                    "quarter": quarter,
                    "section": sec_key,
                    "section_title": sec_title,
                    "sent_id_in_report": sent_id_in_report,
                    "text": s.strip()
                })
                global_id += 1
                sent_id_in_report += 1
                file_sentence_count += 1

        kept = file_sentence_count
        dropped = sum(noise_counts.values())
        print(f"[信息] {basename} 抽取句子数：{kept} (split后总句={total_after_split}, 过滤={dropped})")
        if noise_counts:
            top = ", ".join([f"{k}={v}" for k, v in sorted(noise_counts.items(), key=lambda x: -x[1])[:8]])
            print(f"[信息] {basename} 过滤原因Top: {top}")

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
