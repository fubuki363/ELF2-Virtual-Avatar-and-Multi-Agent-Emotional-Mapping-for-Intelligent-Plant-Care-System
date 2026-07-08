# ingest_docs.py
import os
from docx import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from rag import ZhipuEmbedding

DOCS_DIR = "./docs"
CHROMA_DIR = "./oxalis_chroma"

def load_txt(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def load_docx(path: str) -> str:
    doc = Document(path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)

def load_all_texts():
    texts = []

    for filename in os.listdir(DOCS_DIR):
        path = os.path.join(DOCS_DIR, filename)

        if filename.endswith(".txt"):
            texts.append(load_txt(path))

        elif filename.endswith(".docx"):
            texts.append(load_docx(path))

    return texts

def ingest():
    raw_texts = load_all_texts()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=100
    )

    chunks = []
    for text in raw_texts:
        chunks.extend(splitter.split_text(text))

    embedding = ZhipuEmbedding()

    vectordb = Chroma.from_texts(
        texts=chunks,
        embedding=embedding,
        persist_directory=CHROMA_DIR
    )

    print(f"✅ 成功导入 {len(chunks)} 条知识片段（txt + docx）")

if __name__ == "__main__":
    ingest()
