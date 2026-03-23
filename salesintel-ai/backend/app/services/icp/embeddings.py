"""
Embedding service — Local fastembed (ONNX) integration.
"""
import numpy as np
import structlog
from fastembed import TextEmbedding

logger = structlog.get_logger("icp.embeddings")

_model = None


def _get_model() -> TextEmbedding:
    """Lazy load the fastembed model."""
    global _model
    if _model is None:
        logger.info("loading_fastembed_model", model_name="BAAI/bge-small-en-v1.5")
        _model = TextEmbedding("BAAI/bge-small-en-v1.5")
    return _model


async def embed_text(text: str) -> list[float]:
    """
    Embed a single text string using fastembed.
    Returns a list of 384 floats.
    """
    if not text or not text.strip():
        return [0.0] * 384

    try:
        model = _get_model()
        # fastembed returns a generator of numpy arrays
        embeddings = list(model.embed([text]))
        embedding = embeddings[0].tolist()
        logger.debug("embed_success", text_length=len(text), dims=len(embedding))
        return embedding
    except Exception as e:
        logger.error("embed_error", error=str(e))
        raise


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """
    Embed multiple texts locally.
    Returns a list of embedding vectors.
    """
    if not texts:
        return []

    cleaned = [t if t else "" for t in texts]

    try:
        model = _get_model()
        embeddings = list(model.embed(cleaned))
        logger.debug("batch_embed_success", count=len(texts))
        return [e.tolist() for e in embeddings]
    except Exception as e:
        logger.error("batch_embed_error", error=str(e))
        raise


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a = np.array(vec_a)
    b = np.array(vec_b)
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))
