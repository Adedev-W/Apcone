from __future__ import annotations

from collections.abc import Sequence

from fastembed import TextEmbedding


class EmbeddingService:
    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_query(self, query: str) -> list[float]:
        raise NotImplementedError


class FastEmbedEmbeddingService(EmbeddingService):
    def __init__(self, model_name: str) -> None:
        self._model = TextEmbedding(model_name=model_name)

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.embed(texts)]

    def embed_query(self, query: str) -> list[float]:
        return self.embed_texts([query])[0]

