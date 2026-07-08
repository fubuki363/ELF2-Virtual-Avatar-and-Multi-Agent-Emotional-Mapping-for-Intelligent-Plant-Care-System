"""
植物知识库 RAG 检索 —— 从 PC 端迁移至 ELF2。
使用智谱AI Embedding + Chroma 向量数据库进行本地植物资料检索。
"""
import os
from dotenv import load_dotenv

load_dotenv()


class ZhipuEmbedding:
    """智谱AI Embedding 封装 (兼容 LangChain Embeddings 接口)。"""

    def __init__(self):
        from zhipuai import ZhipuAI
        self._client = ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        embeddings = []
        for text in texts:
            resp = self._client.embeddings.create(
                model="embedding-3", input=text
            )
            embeddings.append(resp.data[0].embedding)
        return embeddings

    def embed_query(self, text: str) -> list[float]:
        resp = self._client.embeddings.create(
            model="embedding-3", input=text
        )
        return resp.data[0].embedding


def get_vectordb():
    """获取 Chroma 向量数据库实例 (惰性初始化)。"""
    from langchain_chroma import Chroma
    embedding = ZhipuEmbedding()
    return Chroma(
        persist_directory="./oxalis_chroma",
        embedding_function=embedding,
    )


def retrieve_docs(query: str, k: int = 3) -> str:
    """从植物知识库中检索相关文档片段。

    Args:
        query: 用户问题
        k: 返回结果数量

    Returns:
        拼接后的文档内容字符串，若向量库不存在则返回空字符串。
    """
    try:
        vectordb = get_vectordb()
        docs = vectordb.similarity_search(query, k=k)
        return "\n".join(d.page_content for d in docs)
    except Exception as e:
        print(f"[RAG] 检索失败: {e}")
        return ""
