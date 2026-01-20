from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader


class FileLoader:
    def load_document(file_path: str, file_type: str):
        if file_type == "pdf":
            loader = PyPDFLoader(file_path)
        elif file_type in ["doc", "docx"]:
            loader = Docx2txtLoader(file_path)
        else:
            raise ValueError("Unsupported file type")

        documents = loader.load()
        return documents
