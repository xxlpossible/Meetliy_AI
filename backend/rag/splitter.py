"""
文本分块器
==========

提供三种分块策略，分别适配不同场景：

1. split_documents（通用递归分块）
    使用 RecursiveCharacterTextSplitter，按标点符号递归切分。
    适用于纯文本场景（如会议转录结果），不感知 Markdown 结构。
    —— tasks.py 转录场景使用此方法，保持原有行为不变。

2. split_markdown_documents（Markdown 结构化分块）
    使用 LangChain 的 MarkdownTextSplitter，按 Markdown 标题 / 段落 /
    列表等结构边界切分，避免在标题或表格中间断开，保留语义完整性。
    —— knowledge.py 文件上传场景使用此方法（MarkItDown 转换后的 MD 文档）。

3. split_summary_documents（摘要级分块）
    对 AI 已提炼的结构化内容（摘要、行动项），直接包装为 Document
    不做拆分，保留完整语义。theme_segmentation 调用方自行按【主题名称】
    边界拆分后再传入。
    —— tasks.py 摘要入库场景使用此方法。

设计原则：
    - 三种方法签名一致（List[Document] -> List[Document]），便于切换
    - 分块参数集中为类常量，便于统一调优
    - Markdown 分块优先保证结构完整，通用分块优先保证长度均匀
    - 摘要级分块保留原文档完整性，不破坏结构化语义
"""


from langchain_core.documents import Document
from langchain_text_splitters import (
    MarkdownTextSplitter,
    RecursiveCharacterTextSplitter,
)
from loguru import logger


class Splitter:
    """文本分块器：提供通用分块与 Markdown 结构化分块两种策略。"""

    # —— 分块参数（可根据嵌入模型上下文窗口统一调优）——
    CHUNK_SIZE: int = 400
    CHUNK_OVERLAP: int = 150

    # 通用递归分块的分隔符（优先级从高到低）
    _SEPARATORS = ["\n\n", "\n", "。", "！", "？", ".", "!", "?", ",", "，"]

    @classmethod
    def split_documents(cls, documents: list[Document]) -> list[Document]:
        """
        通用递归分块（适用于纯文本，如转录结果）。

        使用 RecursiveCharacterTextSplitter 按标点符号递归切分，
        不感知 Markdown 结构，长度均匀但可能在语义边界中间断开。

        :param documents: LangChain Document 列表
        :return: 分块后的 Document 列表
        """
        text_splitter = RecursiveCharacterTextSplitter(
            separators=cls._SEPARATORS,
            chunk_size=cls.CHUNK_SIZE,
            chunk_overlap=cls.CHUNK_OVERLAP,
            length_function=len,
        )
        chunks = text_splitter.split_documents(documents)
        return chunks

    @classmethod
    def split_markdown_documents(cls, documents: list[Document]) -> list[Document]:
        """
        Markdown 结构化分块（适用于 MarkItDown 转换后的 MD 文档）。

        使用 LangChain 的 MarkdownTextSplitter，按 Markdown 标题（#）、
        段落、列表、代码块等结构边界切分，避免破坏标题层级与表格完整性，
        对知识库检索的召回质量有明显提升。

        :param documents: LangChain Document 列表（page_content 为 Markdown）
        :return: 分块后的 Document 列表（保留原 metadata）
        """
        markdown_splitter = MarkdownTextSplitter(
            chunk_size=cls.CHUNK_SIZE,
            chunk_overlap=cls.CHUNK_OVERLAP,
        )
        chunks = markdown_splitter.split_documents(documents)
        logger.info(f"[Splitter] Markdown 分块完成: {len(documents)} 篇 -> {len(chunks)} 块")
        return chunks

    @classmethod
    def split_summary_documents(cls, documents: list[Document]) -> list[Document]:
        """
        摘要级分块（不拆分，仅包装为 Document）。

        适用于 AI 已提炼的结构化内容（会议摘要、行动项、主题分段），
        这些内容天然具有高信息密度和全局视角，拆分反而破坏完整性。

        调用方负责：
        - 将 summary / action 作为单篇 Document 传入
        - 将 theme_segmentation 按【主题名称】边界拆分后再传入

        :param documents: LangChain Document 列表（篇幅适中，不需要拆分）
        :return: 直接返回输入（不拆分），仅包装确保 metadata 不丢失
        """
        result: list[Document] = []
        for doc in documents:
            content = doc.page_content.strip()
            if content:
                result.append(Document(
                    page_content=content,
                    metadata=dict(doc.metadata) if doc.metadata else {}
                ))
        logger.info(f"[Splitter] 摘要级分块: {len(documents)} 篇 -> {len(result)} 篇（不拆分）")
        return result
