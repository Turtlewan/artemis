from artemis.adapters.model_adapters import _is_ollama


def test_is_ollama_true_for_local_dev_endpoint() -> None:
    assert _is_ollama("http://127.0.0.1:11434/v1") is True


def test_is_ollama_false_for_cloud_endpoints() -> None:
    assert _is_ollama("https://api.deepseek.com/v1") is False
    assert _is_ollama("http://127.0.0.1:8040/v1") is False
