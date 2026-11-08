"""Embedding and answer-generation providers. Swappable, and faked in tests."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class Generator(Protocol):
    def answer(self, question: str, sources: list[str]) -> str: ...


class OpenAIEmbedder:
    def __init__(self, api_key: str | None, model: str = "text-embedding-3-small", dim: int = 1536):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self.client.embeddings.create(model=self.model, input=texts, dimensions=self.dim)
        return [d.embedding for d in response.data]


ANSWER_PROMPT = """Answer the question using only the numbered sources below.
Cite sources inline like [1] or [2]. If the sources don't contain the answer, say you don't know.

Sources:
{sources}

Question: {question}"""


class OpenAIGenerator:
    def __init__(self, api_key: str | None, model: str = "gpt-4o-mini"):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key)
        self.model = model

    def answer(self, question: str, sources: list[str]) -> str:
        numbered = "\n\n".join(f"[{i}] {s}" for i, s in enumerate(sources, 1))
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=[{"role": "user", "content": ANSWER_PROMPT.format(sources=numbered, question=question)}],
        )
        return response.choices[0].message.content or ""


class HashingEmbedder:
    """Deterministic bag-of-words embedding. No API key needed: good for local demos and tests."""

    def __init__(self, dim: int = 256):
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.dim
            for word in re.findall(r"[a-z0-9]+", text.lower()):
                h = int.from_bytes(hashlib.blake2b(word.encode(), digest_size=8).digest(), "big")
                vec[h % self.dim] += 1.0 if (h >> 32) & 1 else -1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


class ExtractiveGenerator:
    """Offline fallback: returns the best-matching source with its citation."""

    def answer(self, question: str, sources: list[str]) -> str:
        if not sources:
            return "I don't know. None of your documents cover that."
        return f"{sources[0]} [1]"
