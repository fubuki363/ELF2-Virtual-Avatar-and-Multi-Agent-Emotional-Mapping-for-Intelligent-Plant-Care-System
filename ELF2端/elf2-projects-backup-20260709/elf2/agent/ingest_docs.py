"""
文档知识库导入工具 —— 从 PC 端迁移至 ELF2。
将 docs/ 目录下的 .txt/.docx 植物资料导入 Chroma 向量数据库。
"""
import os
from docx import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from .rag import ZhipuEmbedding

DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "docs")
CHROMA_DIR = "./oxalis_chroma"


def load_txt(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_docx(path: str) -> str:
    doc = Document(path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


def load_all_texts() -> list[str]:
    """加载 docs/ 下所有 .txt 和 .docx 文件。"""
    texts = []
    if not os.path.isdir(DOCS_DIR):
        print(f"[Ingest] 文档目录不存在: {DOCS_DIR}")
        return texts

    for filename in os.listdir(DOCS_DIR):
        path = os.path.join(DOCS_DIR, filename)
        try:
            if filename.endswith(".txt"):
                texts.append(load_txt(path))
            elif filename.endswith(".docx"):
                texts.append(load_docx(path))
        except Exception as e:
            print(f"[Ingest] 跳过 {filename}: {e}")
    return texts


def ingest() -> int:
    """执行文档导入，返回导入的片段数量。"""
    raw_texts = load_all_texts()
    if not raw_texts:
        print("[Ingest] 没有找到可导入的文档")
        return 0

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500, chunk_overlap=100
    )
    chunks = []
    for text in raw_texts:
        chunks.extend(splitter.split_text(text))

    embedding = ZhipuEmbedding()
    Chroma.from_texts(
        texts=chunks,
        embedding=embedding,
        persist_directory=CHROMA_DIR,
    )
    print(f"[Ingest] 成功导入 {len(chunks)} 条知识片段")
    return len(chunks)


if __name__ == "__main__":
    ingest()
