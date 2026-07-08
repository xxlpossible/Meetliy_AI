"""
文件加载器
==========

使用 MarkItDown 将任意格式文档统一转换为 Markdown 文本，
并包装为 LangChain Document 返回，供下游 Markdown 分块器处理。

改造说明（相较旧版）：
    - 旧版使用 PyPDFLoader / Docx2txtLoader / UnstructuredExcelLoader 等多个分散的 Loader，
      且 .doc 依赖 win32com、Excel 需自定义结构化处理。
    - 新版统一通过 MarkItDown 转换为 Markdown，逻辑收敛到单一入口，
      支持格式大幅扩展（PDF/Word/Excel/PPT/图片/音频/文本/代码 等），
      且移除了对 win32com 的直接依赖（已下沉到 markitdown_converter 内部按需调用）。
"""

import os
from typing import List, Optional

from langchain_core.documents import Document
from loguru import logger

from utils.markitdown_converter import convert_to_markdown, is_supported, get_knowledge_type


class FileLoader:
    """
    统一文件加载器：任意格式 → Markdown → LangChain Document。

    使用方式：
        loader = FileLoader()
        docs = loader.load_document(file_path="/path/to/file.pdf", file_type="pdf")
    """

    def load_document(
        self,
        file_path: str,
        file_type: Optional[str] = None
    ) -> List[Document]:
        """
        加载文档并转换为 Markdown 形式的 LangChain Document 列表。

        :param file_path: 文件路径
        :param file_type: 文件类型（扩展名，不含点）；为空时从路径自动推断
        :return: LangChain Document 列表（page_content 为 Markdown 文本）
        :raises ValueError: 文件类型不支持或转换结果为空
        """
        if not file_path or not os.path.exists(file_path):
            raise ValueError(f"文件不存在: {file_path}")

        # file_type 为空时从路径推断
        if not file_type:
            file_type = os.path.splitext(file_path)[1].lstrip(".").lower()

        # 校验是否为受支持的类型
        if not is_supported(file_path):
            raise ValueError(
                f"Unsupported file type: .{file_type}，"
                f"当前支持 PDF/Word/Excel/PPT/图片/音频/文本/代码 等格式"
            )

        # 根据知识类型路由解析：文本走 MarkItDown、语音走硅基流动转录、图片走硅基流动 OCR
        ktype = get_knowledge_type(file_path)
        if ktype == 1:
            # 语音：调用硅基流动 SenseVoiceSmall 转录（不走 MarkItDown）
            from utils.siliconflow_media_parser import transcribe_audio
            logger.info(f"[FileLoader] 语音转录开始: {file_path} (type={file_type})")
            text = transcribe_audio(file_path)
        elif ktype == 2:
            # 图片：调用硅基流动 deepseek-ai/DeepSeek-OCR（不走 MarkItDown）
            from utils.siliconflow_media_parser import ocr_image
            logger.info(f"[FileLoader] 图片 OCR 开始: {file_path} (type={file_type})")
            text = ocr_image(file_path)
        else:
            # 文本：通过 MarkItDown 统一转换为 Markdown
            logger.info(f"[FileLoader] 文档加载开始: {file_path} (type={file_type})")
            text = convert_to_markdown(file_path)

        if not text or not text.strip():
            raise ValueError(f"文件内容为空或解析失败: {file_path}")

        # 包装为 LangChain Document 返回，保留来源信息
        document = Document(
            page_content=text,
            metadata={
                "source": file_path,
                "file_type": file_type,
            }
        )

        logger.info(f"[FileLoader] 文件加载完成: {file_path} -> {len(text)} chars")
        return [document]
