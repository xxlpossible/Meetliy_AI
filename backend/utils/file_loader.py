from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, UnstructuredExcelLoader, TextLoader
from langchain_core.documents import Document
import pandas as pd
import os
import win32com.client as win32

class FileLoader:
    def load_document(self, file_path: str, file_type: str):
        loader = None
        docs = None
        if file_type == "pdf":
            loader = PyPDFLoader(file_path)
        elif file_type == "doc":
            # 先转换
            file_path = self._convert_doc_to_docx(file_path)
            # 转换后按 docx 处理
            loader = Docx2txtLoader(file_path)
        elif file_type == "docx":
            loader = Docx2txtLoader(file_path)
        elif file_type in ["xls", "xlsx"]:
            docs = self.excel_to_structured_chunks(file_path)
        # --- 新增 Markdown 支持 ---
        elif file_type == "md":
            loader = TextLoader(file_path, encoding='utf-8')
        else:
            raise ValueError("Unsupported file type")

        documents = loader.load() if docs is None else docs
        return documents

    def excel_to_structured_chunks(self, file_path):
        # 读取 Excel
        df = pd.read_excel(file_path)
        df = df.fillna("")  # 处理空值

        headers = df.columns.tolist()
        documents = []

        for index, row in df.iterrows():
            # 将每一行转为： 表头1: 值1, 表头2: 值2...
            row_context = []
            for header in headers:
                row_context.append(f"{header}: {row[header]}")

            content = "\n".join(row_context)

            # 还可以把表名或Sheet名加入 metadata
            doc = Document(
                page_content=content,
                metadata={"source": file_path, "row_index": index}
            )
            documents.append(doc)

        return documents

    def _convert_doc_to_docx(self, doc_path):
        """将 .doc 转换为 .docx"""
        # 获取绝对路径
        abs_path = os.path.abspath(doc_path)
        word = win32.gencache.EnsureDispatch('Word.Application')
        doc = word.Documents.Open(abs_path)

        # 构造新的文件名 .docx
        new_path = abs_path + "x"
        # FileFormat=16 代表 docx 格式
        doc.SaveAs(new_path, FileFormat=16)
        doc.Close()
        # word.Quit() # 如果频繁处理，不要每次都 Quit，建议类初始化时创建 word 对象
        return new_path