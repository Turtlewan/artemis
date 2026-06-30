"""Configuration for Artemis memory backends."""

from pydantic import BaseModel, Field


class MemoryConfig(BaseModel):
    """Cognee memory backend configuration."""

    llm_provider: str = "ollama"
    llm_model: str = "qwen3:4b"
    llm_endpoint: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    embedding_provider: str = "ollama"
    embedding_model: str = "qwen3-embedding:0.6b"
    embedding_endpoint: str = "http://localhost:11434/api/embed"
    embedding_dim: int = 1024
    embedding_tokenizer: str = "Qwen/Qwen3-Embedding-0.6B"
    data_root: str | None = None
    default_dataset: str = "artemis"
    layer_datasets: dict[str, str] = Field(default_factory=dict)
    retrieve_candidates: int = 20
    mmr_lambda: float = 0.7
    use_embedding_mmr: bool = True
    search_type: str = "CHUNKS"
    consolidate_on_write: bool = False
    consolidation_similar_k: int = 5
    decay_half_life_days: float = 30.0
    default_salience: float = 1.0
