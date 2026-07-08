# rag.py（修正版）
import os
from dotenv import load_dotenv
from zhipuai import ZhipuAI
from langchain.embeddings.base import Embeddings
from langchain_chroma import Chroma

load_dotenv()

client = ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))

class ZhipuEmbedding(Embeddings):
    def embed_documents(self, texts):
        embeddings = []
        for text in texts:
            resp = client.embeddings.create(
                model="embedding-3",
                input=text
            )
            embeddings.append(resp.data[0].embedding)
        return embeddings

    def embed_query(self, text):
        resp = client.embeddings.create(
            model="embedding-3",
            input=text
        )
        return resp.data[0].embedding


embedding = ZhipuEmbedding()

vectordb = Chroma(
    persist_directory="./oxalis_chroma",
    embedding_function=embedding
)

def retrieve_docs(query, k=3):
    docs = vectordb.similarity_search(query, k=k)
    return "\n".join(d.page_content for d in docs)
