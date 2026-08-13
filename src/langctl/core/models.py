"""Chat model providers.

`init_chat_model` accepts 27 providers, each supplied by its own package and
reading its own API key. This registry records that mapping so a feature and its
dependency cannot drift — the same rule the memory backends and middleware
follow, and for the same reason: a missing package is a startup failure that
`langgraph validate` reports as valid.

The list is open, not closed. An unrecognised provider is allowed as long as the
project says which package supplies it, because pinning langctl to a fixed set
would mean a new LangChain integration could not be used until langctl shipped a
release.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    """How to install and authenticate one chat model provider."""

    key: str
    package: str | None
    #: Env var holding the credential. None when the provider needs no key
    #: (a local runtime) or uses ambient credentials (cloud SDK config).
    api_key_env: str | None
    #: Default model, so `--model-provider x` alone produces a working project.
    default_model: str | None = None
    note: str | None = None


#: Verified against `langchain.chat_models.init_chat_model`.
PROVIDERS: dict[str, Provider] = {
    p.key: p
    for p in (
        Provider("anthropic", "langchain-anthropic>=1.0", "ANTHROPIC_API_KEY", "claude-opus-5"),
        Provider("openai", "langchain-openai>=1.0", "OPENAI_API_KEY", "gpt-5.5"),
        Provider("google_genai", "langchain-google-genai>=2.0", "GOOGLE_API_KEY",
                 "gemini-2.5-pro"),
        Provider("google_vertexai", "langchain-google-vertexai>=3.0",
                 "GOOGLE_APPLICATION_CREDENTIALS", "gemini-2.5-pro",
                 note="Uses a service-account file, not an API key."),
        Provider("azure_openai", "langchain-openai>=1.0", "AZURE_OPENAI_API_KEY",
                 note="Also needs AZURE_OPENAI_ENDPOINT."),
        Provider("azure_ai", "langchain-azure-ai>=1.0", "AZURE_AI_API_KEY"),
        Provider("bedrock", "langchain-aws>=1.0", "AWS_ACCESS_KEY_ID",
                 note="Uses the standard AWS credential chain."),
        Provider("bedrock_converse", "langchain-aws>=1.0", "AWS_ACCESS_KEY_ID"),
        Provider("anthropic_bedrock", "langchain-aws>=1.0", "AWS_ACCESS_KEY_ID"),
        Provider("cohere", "langchain-cohere>=1.0", "COHERE_API_KEY"),
        Provider("mistralai", "langchain-mistralai>=1.0", "MISTRAL_API_KEY"),
        Provider("groq", "langchain-groq>=1.0", "GROQ_API_KEY"),
        Provider("together", "langchain-together>=1.0", "TOGETHER_API_KEY"),
        Provider("fireworks", "langchain-fireworks>=1.0", "FIREWORKS_API_KEY"),
        Provider("openrouter", "langchain-openrouter>=1.0", "OPENROUTER_API_KEY"),
        Provider("deepseek", "langchain-deepseek>=1.0", "DEEPSEEK_API_KEY"),
        Provider("xai", "langchain-xai>=1.0", "XAI_API_KEY"),
        Provider("perplexity", "langchain-perplexity>=1.0", "PPLX_API_KEY"),
        Provider("nvidia", "langchain-nvidia-ai-endpoints>=1.0", "NVIDIA_API_KEY"),
        Provider("ibm", "langchain-ibm>=1.0", "WATSONX_APIKEY"),
        Provider("upstage", "langchain-upstage>=1.0", "UPSTAGE_API_KEY"),
        Provider("baseten", "langchain-baseten>=1.0", "BASETEN_API_KEY"),
        Provider("litellm", "langchain-litellm>=1.0", None,
                 note="Credentials depend on the model the proxy routes to."),
        Provider("huggingface", "langchain-huggingface>=1.0", "HUGGINGFACEHUB_API_TOKEN"),
        Provider("ollama", "langchain-ollama>=1.0", None, "llama3.2",
                 note="Runs locally; no API key. Needs Ollama running."),
    )
}

#: Offered in the interactive wizard. The rest stay available via --model-provider
#: so the prompt does not become a list of 25 things to scroll.
WIZARD_PROVIDERS = ("anthropic", "openai", "google_genai", "ollama", "openrouter", "groq")

#: Accepted spellings that are not the canonical key.
PROVIDER_ALIASES = {
    "google": "google_genai",
    "gemini": "google_genai",
    "vertexai": "google_vertexai",
    "azure": "azure_openai",
    "aws": "bedrock",
    "hf": "huggingface",
}


def normalise(provider: str) -> str:
    return PROVIDER_ALIASES.get(provider.strip().lower(), provider.strip().lower())


def get(provider: str) -> Provider | None:
    return PROVIDERS.get(normalise(provider))


def is_known(provider: str) -> bool:
    return normalise(provider) in PROVIDERS


def suggest(provider: str, limit: int = 4) -> list[str]:
    """Close matches for an unrecognised provider, for the error message."""
    import difflib

    return difflib.get_close_matches(normalise(provider), PROVIDERS, n=limit, cutoff=0.5)
