from typing import List
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


class Splitter:
    @staticmethod
    def split_documents(documents: List[Document]):
        text_splitter = RecursiveCharacterTextSplitter(
            separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", ",", "，"],
            chunk_size=400,
            chunk_overlap=150,
            length_function=len
        )
        return text_splitter.split_documents(documents)
