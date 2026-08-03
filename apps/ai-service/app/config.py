import os


class Settings:
    database_url = os.getenv("DATABASE_URL", "")
    llm_base_url = os.getenv("LLM_BASE_URL")
    llm_api_key = os.getenv("LLM_API_KEY")
    llm_model = os.getenv("LLM_MODEL")
    llm_enabled = os.getenv("LLM_ENABLED", "false").lower() == "true"
    llm_reasoning_effort = os.getenv("LLM_REASONING_EFFORT", "low")
    llm_fast_model = os.getenv("LLM_FAST_MODEL") or llm_model
    llm_fast_reasoning_effort = os.getenv("LLM_FAST_REASONING_EFFORT", "low")
    llm_reasoning_model = os.getenv("LLM_REASONING_MODEL") or llm_model
    llm_reasoning_profile_effort = os.getenv("LLM_REASONING_PROFILE_EFFORT", "medium")
    llm_reviewer_model = os.getenv("LLM_REVIEWER_MODEL") or llm_reasoning_model
    llm_reviewer_reasoning_effort = os.getenv("LLM_REVIEWER_REASONING_EFFORT", "medium")
    embedding_model = os.getenv("EMBEDDING_MODEL")
    embedding_dimensions = int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))
    embedding_batch_size = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))
    prompt_version = "1.0.0"
    action_confirmation_secret = os.getenv("ACTION_CONFIRMATION_SECRET", "local-demo-confirmation-secret-change-me")
    harness_version = os.getenv("HARNESS_VERSION", "v3")
    harness_v3_enabled = os.getenv("HARNESS_V3_ENABLED", "true").lower() == "true"
    langchain_agent_enabled = os.getenv("LANGCHAIN_AGENT_ENABLED", "true").lower() == "true"
    graphrag_worker_enabled = os.getenv("GRAPHRAG_WORKER_ENABLED", "true").lower() == "true"
    graphrag_worker_concurrency = int(os.getenv("GRAPHRAG_WORKER_CONCURRENCY", "4"))
    graphrag_poll_seconds = float(os.getenv("GRAPHRAG_POLL_SECONDS", "2"))
    agent_max_model_calls = max(3, int(os.getenv("AGENT_MAX_MODEL_CALLS", "3")))
    retrieval_token_budget = int(os.getenv("RETRIEVAL_TOKEN_BUDGET", "1200"))
    retrieval_max_chunks = int(os.getenv("RETRIEVAL_MAX_CHUNKS", "3"))
    lexical_fast_path_score = float(os.getenv("LEXICAL_FAST_PATH_SCORE", "0.05"))
    embedding_cache_ttl_seconds = int(os.getenv("EMBEDDING_CACHE_TTL_SECONDS", "1800"))
    embedding_cache_max_entries = int(os.getenv("EMBEDDING_CACHE_MAX_ENTRIES", "2000"))
    retrieval_cache_ttl_seconds = int(os.getenv("RETRIEVAL_CACHE_TTL_SECONDS", "300"))
    retrieval_cache_max_entries = int(os.getenv("RETRIEVAL_CACHE_MAX_ENTRIES", "1000"))
    web_origin = os.getenv("WEB_ORIGIN", "http://localhost:3000")


settings = Settings()
