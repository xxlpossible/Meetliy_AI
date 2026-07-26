"""
MarkItDown 统一文档转换模块
============================

使用微软开源的 MarkItDown 将任意格式文档统一转换为 Markdown 文本，
作为知识库 RAG 流程的统一文档解析入口。

核心流程：原始文件 → MarkItDown → Markdown 文本 → LangChain MD 分块 → 向量化入库

支持格式：
    - 文档：PDF、Word(.doc/.docx)、Excel(.xls/.xlsx)、PowerPoint(.ppt/.pptx)
    - 文本：TXT、CSV、JSON、XML、HTML、Markdown
    - 图片：JPG、PNG、GIF、BMP、WEBP、TIFF（通过 OCR / 视觉模型）
    - 音频：MP3、WAV、M4A（通过转录，需配置转录服务）
    - 代码：Python、JavaScript、Java、Go、SQL、YAML 等纯文本代码

设计要点：
    1. MarkItDown 实例采用单例模式，避免重复初始化的开销
    2. PDF 使用 pdfplumber 增强处理，保留表格结构（转为 Markdown 表格）+ 后处理清理噪音/合并碎行
    3. .doc 格式跨平台转换：优先 LibreOffice (soffice) headless，Windows 回退 pywin32，均失败降级纯文本读取
    4. 所有异常均被捕获并降级到 _fallback_text_reader，保证流程不中断
    5. 使用 loguru 记录关键步骤，便于排查问题
"""

import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from loguru import logger

# ==========================================
# 支持的文件扩展名集合
# ==========================================
SUPPORTED_EXTENSIONS: set[str] = {
    # —— 文档类 ——
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    # —— 文本/结构化数据 ——
    ".txt", ".csv", ".json", ".xml", ".html", ".htm", ".md", ".markdown", ".rst",
    # —— 图片类（OCR / 视觉模型）——
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif",
    # —— 音频类（转录）——
    ".mp3", ".wav", ".m4a", ".flac",
    # —— 代码 / 配置（纯文本）——
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h", ".hpp",
    ".go", ".rs", ".rb", ".php", ".sh", ".bat", ".sql",
    ".yaml", ".yml", ".toml", ".ini", ".conf", ".properties", ".log",
}

# 需要作为纯文本读取的代码/配置扩展名（MarkItDown 不会特殊处理，直接走兜底更稳定）
_TEXT_FALLBACK_EXTENSIONS: set[str] = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h", ".hpp",
    ".go", ".rs", ".rb", ".php", ".sh", ".bat", ".sql",
    ".yaml", ".yml", ".toml", ".ini", ".conf", ".properties", ".log", ".rst",
}

# 音频扩展名（走硅基流动 SenseVoiceSmall 转录，不走 MarkItDown）
AUDIO_EXTENSIONS: set[str] = {".mp3", ".wav", ".m4a", ".flac"}

# 图片扩展名（走硅基流动 PaddleOCR-VL-1.5 OCR，不走 MarkItDown）
IMAGE_EXTENSIONS: set[str] = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"}


def get_knowledge_type(file_path_or_ext: str) -> int:
    """
    根据文件扩展名判断知识类型：
        0 = 文本（走 MarkItDown 解析）
        1 = 语音（走硅基流动 SenseVoiceSmall 转录）
        2 = 图片（走硅基流动 PaddleOCR-VL-1.5 OCR）

    :param file_path_or_ext: 文件路径或扩展名（含点，如 ".mp3" 或 "a.mp3"）
    :return: 0 / 1 / 2
    """
    ext = (os.path.splitext(file_path_or_ext)[1] or "").lower()
    # 兼容直接传 ".mp3" 的情况
    if not ext and file_path_or_ext.startswith("."):
        ext = file_path_or_ext.lower()
    if ext in AUDIO_EXTENSIONS:
        return 1
    if ext in IMAGE_EXTENSIONS:
        return 2
    return 0


# ==========================================
# MarkItDown 单例管理
# ==========================================
_markitdown_instance = None
_instance_lock = threading.Lock()


def _get_markitdown_instance():
    """
    获取 MarkItDown 单例实例（线程安全）。

    MarkItDown 初始化会加载多种转换器（PDF/Word/Excel/PPT/图片等），
    重复创建会有一定开销，因此使用单例 + 双重检查锁保证全局唯一。

    :return: MarkItDown 实例；若安装失败则返回 None
    """
    global _markitdown_instance
    if _markitdown_instance is None:
        with _instance_lock:
            if _markitdown_instance is None:
                try:
                    from markitdown import MarkItDown
                    _markitdown_instance = MarkItDown()
                    logger.info("[MarkItDown] 实例初始化成功")
                except ImportError:
                    logger.error("[MarkItDown] 未安装 markitdown 包，请执行 `uv add markitdown[all]`")
                    _markitdown_instance = None
                except Exception as e:
                    logger.error(f"[MarkItDown] 实例初始化失败: {e}")
                    _markitdown_instance = None
    return _markitdown_instance


# ==========================================
# PDF 增强处理
# ==========================================
def _table_to_markdown(table) -> str:
    """
    将 pdfplumber 提取的二维表格转换为 Markdown 表格语法。

    :param table: 二维列表，第一行为表头
    :return: Markdown 表格字符串
    """
    if not table or not table[0]:
        return ""

    # 对齐每行列数，避免 Markdown 表格错位
    col_count = max(len(row) for row in table)
    normalized = [
        [(str(cell) if cell is not None else "") for cell in row] + [""] * (col_count - len(row))
        for row in table
    ]

    header = normalized[0]
    body = normalized[1:]

    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * col_count) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


# ==========================================
# PDF 文本后处理（噪音清理 + 碎行合并）
# ==========================================
def _is_structural_line(line: str) -> bool:
    """判断是否为 Markdown 结构行（表格/标题/页码标记），后处理时应保护不被合并或删除。"""
    if not line:
        return False
    return (
        line.startswith("|")    # Markdown 表格行
        or line.startswith("#")  # Markdown 标题行（含页码标记 "## 第 N 页"）
    )


def _is_sentence_end(line: str) -> bool:
    """判断行尾是否为句末标点（段落结束标志）。"""
    if not line:
        return False
    return line[-1] in "。！？；.!?;"


def _pick_connector(cur: str, nxt: str) -> str:
    """
    选择碎行合并的连接符：
        - 中英文边界用空格（避免 "word中文" 或 "中文word" 粘连）
        - 纯中文之间不用空格（中文无词间空格）
    """
    if not cur or not nxt:
        return ""
    cur_end_ascii_alnum = cur[-1].isascii() and cur[-1].isalnum()
    nxt_start_ascii_alnum = nxt[0].isascii() and nxt[0].isalnum()
    if cur_end_ascii_alnum or nxt_start_ascii_alnum:
        return " "
    return ""


def _post_process_pdf_text(text: str) -> str:
    """
    PDF 提取文本后处理：清理噪音 + 智能合并碎行，同时保护 Markdown 结构。

    解决 PDF 文本提取的三个常见痛点：
        1. 页脚页码、孤立单字符噪音行
        2. 一个段落被物理拆分成多行（PDF 按视觉行断行，非按段落）
        3. 中文碎行合并时误加空格

    处理策略：
        - 噪音清理：移除纯页码行（1-4 位数字）、孤立单字符噪音（保留中文数字）
        - 结构保护：Markdown 表格行（|）、标题行（#）不参与清理与合并
        - 碎行合并：非句末行与下一行合并，中文无空格、中英边界加空格
        - 空行规整：合并连续空行为单个空行，保留段落分隔

    :param text: pdfplumber 提取的原始文本（已含 Markdown 表格/页码标记）
    :return: 清理后的 Markdown 文本
    """
    if not text or not text.strip():
        return ""

    lines = text.splitlines()

    # —— 步骤1：噪音清理 ——
    cleaned: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append("")  # 保留空行作为段落分隔
            continue

        # 结构行直接保留（表格/标题/页码标记）
        if _is_structural_line(stripped):
            cleaned.append(stripped)
            continue

        # 移除纯页码行（1-4 位纯数字，PDF 常见页脚页码）
        if re.match(r"^\d{1,4}$", stripped):
            continue

        # 移除孤立单字符噪音（保留中文数字，可能是有意义的列表/编号）
        if len(stripped) == 1 and stripped not in "一二三四五六七八九十零百千万":
            continue

        cleaned.append(stripped)

    # —— 步骤2：智能合并碎行 ——
    merged: list[str] = []
    i = 0
    while i < len(cleaned):
        cur = cleaned[i]

        # 空行、结构行、句末行：直接保留，不参与合并
        if cur == "" or _is_structural_line(cur) or _is_sentence_end(cur):
            merged.append(cur)
            i += 1
            continue

        # 当前行为段落内碎行，尝试与下一非结构行合并
        if i + 1 < len(cleaned):
            nxt = cleaned[i + 1]
            if nxt and not _is_structural_line(nxt):
                connector = _pick_connector(cur, nxt)
                merged.append(cur + connector + nxt)
                i += 2
                continue

        merged.append(cur)
        i += 1

    # —— 步骤3：空行规整（合并连续空行为单个）——
    result: list[str] = []
    prev_empty = False
    for line in merged:
        if line == "":
            if not prev_empty:
                result.append(line)
            prev_empty = True
        else:
            result.append(line)
            prev_empty = False

    return "\n".join(result).strip()


def _enhanced_pdf_processing(path: str) -> str:
    """
    PDF 增强处理：使用 pdfplumber 逐页提取文本与表格，
    将表格还原为 Markdown 表格语法，保留结构化信息。

    相比 MarkItDown 默认的 PDF 处理，此方法能更好地保留表格结构，
    对知识库检索（尤其是含表格的报表/论文）召回质量有显著提升。

    :param path: PDF 文件路径
    :return: Markdown 文本
    """
    try:
        import pdfplumber
    except ImportError:
        logger.warning("[MarkItDown] pdfplumber 未安装，降级为 MarkItDown 默认 PDF 处理")
        md_instance = _get_markitdown_instance()
        if md_instance is None:
            return _fallback_text_reader(path)
        try:
            result = md_instance.convert(path)
            return getattr(result, "text_content", "") or ""
        except Exception as e:
            logger.error(f"[MarkItDown] PDF 默认处理也失败 {path}: {e}")
            return _fallback_text_reader(path)

    md_parts = []
    try:
        with pdfplumber.open(path) as pdf:
            total_pages = len(pdf.pages)
            logger.info(f"[MarkItDown] PDF 增强处理开始：{path}（共 {total_pages} 页）")

            for page_idx, page in enumerate(pdf.pages, start=1):
                # 页码标记改为内联前缀（不单独成 ## 标题行，避免被 splitter 切成碎块）
                page_tag = f"【第{page_idx}页】"

                # 1. 提取正文文本，页码作为内联前缀加到正文开头
                page_text = page.extract_text() or ""
                has_text = bool(page_text.strip())
                if has_text:
                    md_parts.append(f"\n{page_tag} {page_text.strip()}")

                # 2. 提取表格并转为 Markdown 表格
                try:
                    tables = page.extract_tables() or []
                    for t_idx, table in enumerate(tables, start=1):
                        md_table = _table_to_markdown(table)
                        if md_table:
                            # 表格号用普通文本行（不用 ### 标题），避免被单独切分成碎块；
                            # 该页无正文时，页码标记加到首个表格前作定位
                            if t_idx == 1 and not has_text:
                                md_parts.append(f"\n{page_tag} 表格{t_idx}：\n{md_table}\n")
                            else:
                                md_parts.append(f"\n表格{t_idx}：\n{md_table}\n")
                except Exception as te:
                    logger.debug(f"[MarkItDown] 第 {page_idx} 页表格提取失败（可忽略）: {te}")

        markdown_text = "\n".join(md_parts).strip()
        # 后处理：清理页码/碎行噪音 + 智能合并段落碎行（保护 Markdown 表格/标题结构）
        markdown_text = _post_process_pdf_text(markdown_text)
        logger.info(f"[MarkItDown] PDF 增强处理完成：{path} -> {len(markdown_text)} chars Markdown")
        return markdown_text

    except Exception as e:
        logger.error(f"[MarkItDown] PDF 增强处理失败 {path}: {e}，降级为兜底读取")
        return _fallback_text_reader(path)


# ==========================================
# .doc 转 .docx
# ==========================================
def _convert_doc_to_docx(doc_path: str) -> str | None:
    """
    将 .doc 文件转换为 .docx 文件（跨平台）。

    转换策略（按优先级）：
        1. LibreOffice (soffice) headless 命令行 —— 跨平台首选，Linux/Windows/Mac 均可
        2. Windows COM (pywin32) —— 仅 Windows，作为 LibreOffice 不可用时的回退
        3. 都不可用返回 None，由上层降级为兜底文本读取

    跨平台部署说明：
        - Linux 服务器：安装 LibreOffice 即可（`apt install libreoffice` 或 Docker 镜像内置）
        - 不再强依赖 Windows Office，解决 pywin32 在 Linux 无法运行的问题

    :param doc_path: .doc 文件路径
    :return: 转换后的 .docx 路径；失败返回 None
    """
    # 策略1：LibreOffice（跨平台首选）
    docx_path = _convert_doc_via_libreoffice(doc_path)
    if docx_path:
        return docx_path

    # 策略2：Windows pywin32 回退
    docx_path = _convert_doc_via_win32(doc_path)
    if docx_path:
        return docx_path

    logger.warning("[MarkItDown] .doc 转换失败：LibreOffice 与 pywin32 均不可用")
    return None


def _convert_doc_via_libreoffice(doc_path: str) -> str | None:
    """
    通过 LibreOffice headless 命令行将 .doc 转换为 .docx（跨平台）。

    服务器端处理 .doc 的事实标准方案：
        - 跨平台：Linux / Windows / macOS 均可
        - Linux 安装：`apt install libreoffice` 或 `yum install libreoffice`
        - Docker 部署：在镜像中内置 libreoffice 即可

    并发安全：每次转换使用独立的 UserInstallation profile 目录，
    避免多进程并发转换时 LibreOffice 配置锁冲突。

    :param doc_path: .doc 文件路径
    :return: 转换后的 .docx 路径；失败/未安装 LibreOffice 返回 None
    """
    # 检测 soffice / libreoffice 命令是否可用
    soffice_bin = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice_bin:
        logger.debug("[MarkItDown] 未检测到 LibreOffice (soffice)，跳过此转换方式")
        return None

    abs_path = os.path.abspath(doc_path)
    out_dir = tempfile.mkdtemp(prefix="lo_convert_")
    # 隔离用户配置目录，避免并发转换时 LibreOffice profile 冲突
    profile_dir = tempfile.mkdtemp(prefix="lo_profile_")
    profile_url = Path(profile_dir).as_uri()

    try:
        cmd = [
            soffice_bin,
            "--headless",
            "--norestore",
            "--nolockcheck",
            f"-env:UserInstallation={profile_url}",
            "--convert-to", "docx",
            "--outdir", out_dir,
            abs_path,
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,  # .doc 转换可能较慢，给足时间
        )
        if result.returncode != 0:
            logger.warning(
                f"[MarkItDown] LibreOffice 转换失败 (returncode={result.returncode}): "
                f"{(result.stderr or '').strip() or (result.stdout or '').strip()}"
            )
            return None

        # 输出文件名：原文件名 + .docx
        base_name = os.path.splitext(os.path.basename(abs_path))[0]
        expected_path = os.path.join(out_dir, base_name + ".docx")
        if os.path.exists(expected_path):
            logger.info(f"[MarkItDown] LibreOffice .doc 转换成功：{abs_path} -> {expected_path}")
            return expected_path

        # 兜底：扫描 out_dir 找 .docx（文件名可能因特殊字符变化）
        for fname in os.listdir(out_dir):
            if fname.lower().endswith(".docx"):
                return os.path.join(out_dir, fname)

        logger.warning("[MarkItDown] LibreOffice 转换后未找到 .docx 输出文件")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("[MarkItDown] LibreOffice 转换超时（120s）")
        return None
    except Exception as e:
        logger.warning(f"[MarkItDown] LibreOffice 转换异常: {e}")
        return None


def _convert_doc_via_win32(doc_path: str) -> str | None:
    """
    通过 Windows COM (Word) 将 .doc 转换为 .docx（仅 Windows）。

    作为 LibreOffice 不可用时的 Windows 回退方案，转换质量最高
    （原生 Word 引擎），但强依赖 Windows + Office，无法用于 Linux。

    :param doc_path: .doc 文件路径
    :return: 转换后的 .docx 路径；失败/非 Windows 返回 None
    """
    try:
        import win32com.client as win32  # type: ignore
    except ImportError:
        return None

    abs_path = os.path.abspath(doc_path)
    new_path = abs_path + "x"  # .doc -> .docx
    if os.path.exists(new_path):
        return new_path

    word = None
    doc = None
    try:
        word = win32.gencache.EnsureDispatch("Word.Application")
        word.Visible = False
        doc = word.Documents.Open(abs_path)
        doc.SaveAs(new_path, FileFormat=16)  # 16 = docx 格式
        logger.info(f"[MarkItDown] pywin32 .doc 转换成功：{abs_path} -> {new_path}")
        return new_path
    except Exception as e:
        logger.warning(f"[MarkItDown] pywin32 .doc 转换失败（可能未安装 Word）: {e}")
        return None
    finally:
        try:
            if doc is not None:
                doc.Close()
        except Exception:
            pass
        # 不 Quit Word，避免频繁启停；进程退出时由系统回收


# ==========================================
# 兜底文本读取
# ==========================================
def _fallback_text_reader(path: str) -> str:
    """
    兜底文本读取：当 MarkItDown 转换失败时，尝试用多种编码读取纯文本。

    遍历常见编码（UTF-8 / GBK / GB2312 / Latin-1 / UTF-16），
    首个成功读取的编码即返回，保证流程不中断。

    :param path: 文件路径
    :return: 读取到的文本；全部失败返回空字符串
    """
    if not os.path.exists(path):
        return ""

    encodings = ["utf-8", "gbk", "gb2312", "latin-1", "utf-16"]
    for enc in encodings:
        try:
            with open(path, "r", encoding=enc) as f:
                content = f.read()
            logger.info(f"[MarkItDown] 兜底文本读取成功（{enc}）：{path} -> {len(content)} chars")
            return content
        except (UnicodeDecodeError, UnicodeError):
            continue
        except Exception:
            continue

    logger.warning(f"[MarkItDown] 兜底文本读取失败：所有编码均无法解码 {path}")
    return ""


# ==========================================
# Excel 专用结构化处理
# ==========================================
def _excel_to_markdown(path: str) -> str:
    """
    Excel 专用结构化转换：把每个 sheet 的每行数据转成「列名: 值」键值对，
    让每行自带表头语义，避免分块后表头丢失导致的语义断裂。

    为什么不用 MarkItDown 默认的整表 Markdown 表格方案：
        MarkItDown 把整个 sheet 转成一个 Markdown 表格，表头只在顶部出现一次。
        当表格行数较多被 MarkdownTextSplitter 分块时，中间/尾部的 chunk 只含
        数据行（如 `| 张三 | 25 |`），丢失列名上下文，向量检索时语义不明。

    本方法的处理策略：
        - 多 sheet：每个 sheet 用 `## Sheet名` 分隔
        - 每行数据转成 `列名1: 值1 | 列名2: 值2 | ...` 的键值对，自带表头
        - 空值跳过，合并单元格 forward fill 补全
        - 列名为空时自动命名为「列N」

    :param path: Excel 文件路径（.xlsx/.xls）
    :return: 结构化 Markdown 文本
    """
    try:
        import pandas as pd
    except ImportError:
        logger.warning("[MarkItDown] pandas 未安装，Excel 降级为 MarkItDown 默认处理")
        md_instance = _get_markitdown_instance()
        if md_instance is None:
            return _fallback_text_reader(path)
        try:
            result = md_instance.convert(path)
            return getattr(result, "text_content", "") or ""
        except Exception:
            return _fallback_text_reader(path)

    ext = (os.path.splitext(path)[1] or "").lower()
    engine = "openpyxl" if ext == ".xlsx" else "xlrd"

    try:
        sheets = pd.read_excel(path, sheet_name=None, engine=engine)
    except Exception as e:
        logger.warning(f"[MarkItDown] Excel 读取失败 {path}: {e}，降级 MarkItDown 默认处理")
        md_instance = _get_markitdown_instance()
        if md_instance is not None:
            try:
                result = md_instance.convert(path)
                text = getattr(result, "text_content", "") or ""
                if text.strip():
                    return text
            except Exception:
                pass
        return _fallback_text_reader(path)

    md_parts: list[str] = []
    for sheet_name, df in sheets.items():
        # 处理空值 + 合并单元格 forward fill（pandas 读合并单元格会得到 NaN）
        df = df.fillna("").ffill()

        # 表头（列名）；空列名自动命名为「列N」
        headers = []
        for i, h in enumerate(df.columns):
            h_str = str(h).strip()
            if not h_str or h_str == "nan":
                h_str = f"列{i + 1}"
            headers.append(h_str)

        # 每行转成键值对，自带表头语义；sheet 名作为行前缀
        # （不单独成 ## 标题行，避免被 splitter 切成无意义碎块，同时让每行自带 sheet 上下文）
        sheet_prefix = f"[{sheet_name}] "
        for _, row in df.iterrows():
            kv_parts = []
            for header, val in zip(headers, row):
                val_str = str(val).strip()
                if val_str and val_str != "nan":
                    kv_parts.append(f"{header}: {val_str}")
            if kv_parts:
                md_parts.append(sheet_prefix + " | ".join(kv_parts))

    markdown_text = "\n".join(md_parts).strip()
    logger.info(f"[MarkItDown] Excel 结构化转换完成：{path} -> {len(markdown_text)} chars Markdown")
    return markdown_text


# ==========================================
# 统一转换入口
# ==========================================
def _convert_to_markdown(path: str) -> str:
    """
    通用文档转 Markdown 入口（与参考代码同名）。

    根据文件扩展名路由到不同处理逻辑：
        - PDF   → _enhanced_pdf_processing（pdfplumber 增强处理）
        - .doc  → 先 win32com 转 .docx，再走 MarkItDown
        - 代码/配置文件 → _fallback_text_reader（更稳定）
        - 其他  → MarkItDown 统一转换
        - 任何环节失败 → _fallback_text_reader 兜底

    :param path: 文件路径
    :return: Markdown 文本；失败返回空字符串
    """
    if not os.path.exists(path):
        logger.error(f"[MarkItDown] 文件不存在: {path}")
        return ""

    ext = (os.path.splitext(path)[1] or "").lower()

    # 1. PDF 使用增强处理（保留表格结构）
    if ext == ".pdf":
        return _enhanced_pdf_processing(path)

    # 2. Excel 使用专用结构化处理（每行自带表头，避免分块后表头丢失）
    if ext in (".xlsx", ".xls"):
        return _excel_to_markdown(path)

    # 3. .doc 先转换为 .docx 再处理
    if ext == ".doc":
        docx_path = _convert_doc_to_docx(path)
        if docx_path and os.path.exists(docx_path):
            path = docx_path
            ext = ".docx"
        else:
            logger.warning(f"[MarkItDown] .doc 转换失败，降级为兜底读取: {path}")
            return _fallback_text_reader(path)

    # 4. 代码 / 配置文件直接走兜底读取（更稳定，避免 MarkItDown 误判）
    if ext in _TEXT_FALLBACK_EXTENSIONS:
        return _fallback_text_reader(path)

    # 5. 其他格式使用 MarkItDown 统一转换
    md_instance = _get_markitdown_instance()
    if md_instance is None:
        logger.warning("[MarkItDown] 实例不可用，降级为兜底读取")
        return _fallback_text_reader(path)

    try:
        result = md_instance.convert(path)
        markdown_text = getattr(result, "text_content", None)
        if isinstance(markdown_text, str) and markdown_text.strip():
            logger.info(f"[MarkItDown] 转换成功：{path} -> {len(markdown_text)} chars Markdown")
            return markdown_text
        logger.warning(f"[MarkItDown] 转换结果为空：{path}")
        return _fallback_text_reader(path)
    except Exception as e:
        logger.warning(f"[MarkItDown] 转换失败 {path}: {e}，降级为兜底读取")
        return _fallback_text_reader(path)


# ==========================================
# 对外公开接口
# ==========================================
def convert_to_markdown(path: str) -> str:
    """
    对外公开的统一转换入口（convert_to_markdown 是 _convert_to_markdown 的公开别名）。

    :param path: 文件路径
    :return: Markdown 文本
    """
    return _convert_to_markdown(path)


def is_supported(file_path: str) -> bool:
    """
    判断文件是否被支持解析。

    :param file_path: 文件路径或文件名
    :return: 支持返回 True
    """
    ext = (os.path.splitext(file_path)[1] or "").lower()
    return ext in SUPPORTED_EXTENSIONS


def get_supported_extensions() -> set[str]:
    """返回支持的文件扩展名集合（用于接口层校验）。"""
    return SUPPORTED_EXTENSIONS
