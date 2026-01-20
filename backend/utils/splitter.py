from langchain_text_splitters import RecursiveCharacterTextSplitter


class Splitter:
    def split_documents(documents):
        text_splitter = RecursiveCharacterTextSplitter(
            separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", ",", "，"],
            chunk_size=800,
            chunk_overlap=150,
            length_function=len
        )
        return text_splitter.split_documents(documents)