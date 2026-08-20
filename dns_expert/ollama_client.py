"""HTTP Client for local Ollama daemon supporting embeddings and streaming chat."""

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Generator, List, Optional
from dns_expert.config import CHAT_MODEL, EMBED_MODEL, FALLBACK_CHAT_MODELS, OLLAMA_HOST


class OllamaError(Exception):
    pass


class OllamaClient:
    def __init__(self, host: str = OLLAMA_HOST, model: str = CHAT_MODEL, embed_model: str = EMBED_MODEL):
        self.host = host.rstrip('/')
        self.model = model
        self.embed_model = embed_model

    def _request(self, endpoint: str, data: Optional[Dict[str, Any]] = None, timeout: int = 60) -> Dict[str, Any]:
        url = f"{self.host}{endpoint}"
        req_data = json.dumps(data).encode("utf-8") if data is not None else None
        headers = {"Content-Type": "application/json"} if data is not None else {}
        req = urllib.request.Request(url, data=req_data, headers=headers, method="POST" if data is not None else "GET")

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp_bytes = resp.read()
                if not resp_bytes:
                    return {}
                return json.loads(resp_bytes.decode("utf-8"))
        except urllib.error.URLError as e:
            if "Connection refused" in str(e) or isinstance(e.reason, ConnectionRefusedError):
                raise OllamaError(
                    f"Could not connect to Ollama at {self.host}.\nPlease make sure Ollama is running (ollama serve or Ollama app)."
                ) from e
            raise OllamaError(f"Ollama request to {endpoint} failed: {e}") from e
        except Exception as e:
            raise OllamaError(f"Unexpected error connecting to Ollama: {e}") from e

    def check_health(self) -> bool:
        try:
            self._request("/api/tags", data=None, timeout=5)
            return True
        except Exception:
            return False

    def list_models(self) -> List[str]:
        try:
            res = self._request("/api/tags", data=None, timeout=5)
            models = res.get("models", [])
            return [m.get("name", "") for m in models if m.get("name")]
        except Exception:
            return []

    def get_best_available_model(self) -> str:
        installed = self.list_models()
        if not installed:
            return self.model

        for target in [self.model] + FALLBACK_CHAT_MODELS:
            for inst in installed:
                if inst == target or inst.startswith(f"{target}:") or target.startswith(f"{inst}:"):
                    return inst

        for inst in installed:
            if "embed" not in inst.lower():
                return inst

        return self.model

    def get_embedding(self, text: str, model: Optional[str] = None) -> List[float]:
        use_model = model or self.embed_model
        payload = {"model": use_model, "prompt": text}

        try:
            res = self._request("/api/embeddings", data=payload, timeout=30)
            embedding = res.get("embedding", [])
            if not embedding:
                res_embed = self._request("/api/embed", data={"model": use_model, "input": text}, timeout=30)
                embeddings = res_embed.get("embeddings", [])
                if embeddings:
                    embedding = embeddings[0]
            if not embedding:
                raise OllamaError(f"Failed to generate embedding with model {use_model}")
            return embedding
        except Exception as e:
            raise OllamaError(f"Error generating embedding: {e}") from e

    def get_embeddings_batch(
        self, texts: List[str], model: Optional[str] = None, retry_count: int = 3
    ) -> List[List[float]]:
        results = []
        for text in texts:
            success = False
            last_err = None
            for attempt in range(retry_count):
                try:
                    emb = self.get_embedding(text, model=model)
                    results.append(emb)
                    success = True
                    break
                except Exception as e:
                    last_err = e
                    time.sleep(0.2 * (attempt + 1))
            if not success:
                raise OllamaError(f"Batch embedding failed after {retry_count} attempts: {last_err}")
        return results

    def chat_complete(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.2,
        options: Optional[Dict[str, Any]] = None,
    ) -> str:
        use_model = model or self.get_best_available_model()
        opts = options or {"temperature": temperature, "num_ctx": 8192}

        payload = {
            "model": use_model,
            "messages": messages,
            "stream": False,
            "options": opts,
        }

        res = self._request("/api/chat", data=payload, timeout=120)
        return res.get("message", {}).get("content", "")

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.2,
        options: Optional[Dict[str, Any]] = None,
    ) -> Generator[str, None, None]:
        use_model = model or self.get_best_available_model()
        opts = options or {"temperature": temperature, "num_ctx": 8192}

        url = f"{self.host}/api/chat"
        payload = {
            "model": use_model,
            "messages": messages,
            "stream": True,
            "options": opts,
        }

        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=req_data, headers={"Content-Type": "application/json"}, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                for line in resp:
                    if not line:
                        continue
                    line_str = line.decode("utf-8").strip()
                    if not line_str:
                        continue
                    try:
                        chunk = json.loads(line_str)
                        content = chunk.get("message", {}).get("content", "")
                        if content:
                            yield content
                        if chunk.get("done", False):
                            break
                    except json.JSONDecodeError:
                        continue
        except urllib.error.URLError as e:
            if "Connection refused" in str(e) or isinstance(e.reason, ConnectionRefusedError):
                raise OllamaError(
                    f"Lost connection to Ollama at {self.host}.\nPlease check that Ollama is still running."
                ) from e
            raise OllamaError(f"Ollama stream error: {e}") from e
