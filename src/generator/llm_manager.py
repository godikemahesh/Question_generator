"""
Multi-Provider LLM Orchestrator with Multi-Key Pool & Model Rotation:
1st Priority: Google Gemini (Pool of API Keys + Multi-Model Rotation)
2nd Priority: OpenRouter API (Pool of API Keys + Web Search support)
3rd Priority: Groq API (Pool of API Keys with Llama 3.3 70B)

Bulletproof Fault-Tolerance:
- Tracks rate limits (HTTP 429 / ResourceExhausted) per key and applies temporary cooldowns.
- Rotates Gemini models (flash vs pro) when a model hits capacity.
- Cascades seamlessly across pools: Gemini Keys -> OpenRouter Keys -> Groq Keys.
- Never crashes the server or generation worker.
"""
from __future__ import annotations
import json
import logging
import re
import time
from typing import Optional, Any
import httpx
import google.generativeai as genai

from config.settings import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL,
    GROQ_API_KEY,
    GROQ_MODEL,
)

logger = logging.getLogger(__name__)

# Default Gemini model cascade priority (verified live working models)
DEFAULT_GEMINI_MODELS = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-2.5-flash",
]


DEPRECATED_MODELS = {
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-2.0-flash",
    "gemini-2.5-pro",
    "gemini-2.5-flash-lite",
}


def sanitize_gemini_models(models: Optional[list[str]]) -> list[str]:
    """Filter out deprecated/retired models from any saved config or input."""
    valid = [m for m in (models or []) if m and m not in DEPRECATED_MODELS]
    return valid if valid else DEFAULT_GEMINI_MODELS


class MultiProviderLLM:
    """
    Orchestrates multi-provider LLM calls with key pools and dynamic model rotation.
    """

    def __init__(
        self,
        gemini_keys: Optional[list[str]] = None,
        openrouter_keys: Optional[list[str]] = None,
        groq_keys: Optional[list[str]] = None,
        gemini_models: Optional[list[str]] = None,
        gemini_key: str = "",
        openrouter_key: str = "",
        groq_key: str = "",
    ):
        # 1. Initialize pools (merging legacy single keys if provided)
        self.gemini_keys: list[str] = [k.strip() for k in (gemini_keys or []) if k and k.strip()]
        if not self.gemini_keys and (gemini_key or GEMINI_API_KEY):
            self.gemini_keys = [gemini_key or GEMINI_API_KEY]

        self.openrouter_keys: list[str] = [k.strip() for k in (openrouter_keys or []) if k and k.strip()]
        if not self.openrouter_keys and (openrouter_key or OPENROUTER_API_KEY):
            self.openrouter_keys = [openrouter_key or OPENROUTER_API_KEY]

        self.groq_keys: list[str] = [k.strip() for k in (groq_keys or []) if k and k.strip()]
        if not self.groq_keys and (groq_key or GROQ_API_KEY):
            self.groq_keys = [groq_key or GROQ_API_KEY]

        # 2. Gemini model priority list (sanitized against deprecated models)
        self.gemini_models: list[str] = sanitize_gemini_models(gemini_models)

        # 3. Health & Cooldown Tracking { key_identifier: timestamp_until_cooldown }
        self.cooldowns: dict[str, float] = {}
        self.key_errors: dict[str, int] = {}
        self.key_successes: dict[str, int] = {}

        # 4. Active provider tracking
        self.last_used_provider: str = "gemini"
        self.last_used_model: str = self.gemini_models[0] if self.gemini_models else "gemini-3.6-flash"
        self.last_used_key_preview: str = ""

    def update_pools(
        self,
        gemini_keys: Optional[list[str]] = None,
        openrouter_keys: Optional[list[str]] = None,
        groq_keys: Optional[list[str]] = None,
        gemini_models: Optional[list[str]] = None,
    ):
        """Dynamically update key pools and model rotation in-memory without server restart."""
        if gemini_keys is not None:
            self.gemini_keys = [k.strip() for k in gemini_keys if k and k.strip()]
        if openrouter_keys is not None:
            self.openrouter_keys = [k.strip() for k in openrouter_keys if k and k.strip()]
        if groq_keys is not None:
            self.groq_keys = [k.strip() for k in groq_keys if k and k.strip()]
        if gemini_models is not None and len(gemini_models) > 0:
            self.gemini_models = sanitize_gemini_models(gemini_models)
        logger.info(
            f"MultiProviderLLM pools updated: Gemini={len(self.gemini_keys)} keys, "
            f"OpenRouter={len(self.openrouter_keys)} keys, Groq={len(self.groq_keys)} keys."
        )

    def update_keys(self, gemini_key: str = "", openrouter_key: str = "", groq_key: str = ""):
        """Legacy helper to add or update single keys."""
        if gemini_key and gemini_key not in self.gemini_keys:
            self.gemini_keys.insert(0, gemini_key)
        if openrouter_key and openrouter_key not in self.openrouter_keys:
            self.openrouter_keys.insert(0, openrouter_key)
        if groq_key and groq_key not in self.groq_keys:
            self.groq_keys.insert(0, groq_key)

    def _is_cooling_down(self, identifier: str) -> bool:
        """Check if key or model is currently in temporary cooldown."""
        exp = self.cooldowns.get(identifier, 0)
        return time.time() < exp

    def _set_cooldown(self, identifier: str, seconds: float = 60.0, reason: str = ""):
        """Put a key or model in temporary cooldown after rate limit/error."""
        self.cooldowns[identifier] = time.time() + seconds
        self.key_errors[identifier] = self.key_errors.get(identifier, 0) + 1
        mask = f"{identifier[:8]}...{identifier[-4:]}" if len(identifier) > 12 else identifier
        logger.warning(f"[RATE-LIMIT] Cooling down '{mask}' for {seconds}s ({reason})")

    def _record_success(self, identifier: str):
        """Record success for a key."""
        self.key_successes[identifier] = self.key_successes.get(identifier, 0) + 1
        if identifier in self.cooldowns:
            del self.cooldowns[identifier]

    # ── 1. Google Gemini Pool & Model Rotation ────────────────────────────────

    def _call_gemini_pool(self, prompt: str, temperature: float = 0.7) -> str:
        """
        Iterates over all Gemini API keys in the pool.
        For each key, rotates through available Gemini models if rate-limited.
        """
        if not self.gemini_keys:
            raise ValueError("No Gemini API keys configured in pool")

        errors = []
        # Sort keys so non-cooldown keys are attempted first
        sorted_keys = sorted(self.gemini_keys, key=lambda k: self.cooldowns.get(k, 0))

        for key in sorted_keys:
            if self._is_cooling_down(key):
                continue

            # Configure genai with this key
            try:
                genai.configure(api_key=key)
            except Exception as e:
                self._set_cooldown(key, 120, str(e))
                errors.append(f"Key init failed: {str(e)[:80]}")
                continue

            # Rotate through available Gemini models for this key
            for model_name in self.gemini_models:
                combo_id = f"{key[:8]}_{model_name}"
                if self._is_cooling_down(combo_id):
                    continue

                try:
                    model = genai.GenerativeModel(model_name)
                    response = model.generate_content(
                        prompt,
                        generation_config={"temperature": temperature, "top_p": 0.95}
                    )
                    text = response.text.strip() if response and hasattr(response, "text") else ""
                    if text:
                        self._record_success(key)
                        self._record_success(combo_id)
                        self.last_used_provider = "gemini"
                        self.last_used_model = model_name
                        self.last_used_key_preview = f"{key[:6]}...{key[-4:]}"
                        return text
                except Exception as e:
                    err_str = str(e).lower()
                    is_rate_limit = any(x in err_str for x in ["429", "quota", "resourceexhausted", "limit", "exhausted"])
                    if is_rate_limit:
                        # Put this model on 45s cooldown and try next model for this key
                        self._set_cooldown(combo_id, 45.0, "Model rate limit")
                        logger.warning(f"Gemini model '{model_name}' hit rate limit on key {key[:6]}... Trying next model.")
                        continue
                    elif "404" in err_str or "not found" in err_str or "no longer available" in err_str:
                        # Model is deprecated or doesn't exist - skip to next model
                        self._set_cooldown(combo_id, 86400.0, "Model deprecated/not found")
                        logger.warning(f"Gemini model '{model_name}' deprecated/not found (404). Skipping to next model.")
                        continue
                    else:
                        errors.append(f"Gemini {model_name} error: {str(e)[:100]}")
                        break  # Non-rate-limit error on this key, try next key

            # If all models for this key failed, put key on 60s cooldown
            self._set_cooldown(key, 60.0, "All models rate-limited or exhausted")

        raise RuntimeError(f"All Gemini pool keys/models exhausted: {'; '.join(errors[:3])}")

    # ── 2. OpenRouter Pool ───────────────────────────────────────────────────

    def _call_openrouter_pool(self, prompt: str, temperature: float = 0.7) -> str:
        """Iterate over OpenRouter keys pool."""
        if not self.openrouter_keys:
            raise ValueError("No OpenRouter API keys configured in pool")

        errors = []
        sorted_keys = sorted(self.openrouter_keys, key=lambda k: self.cooldowns.get(k, 0))

        for key in sorted_keys:
            if self._is_cooling_down(key):
                continue

            headers = {
                "Authorization": f"Bearer {key}",
                "HTTP-Referer": "https://examforge-pink.vercel.app",
                "X-Title": "ExamForge Question Generator",
                "Content-Type": "application/json",
            }
            payload = {
                "model": OPENROUTER_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are an expert exam question generator. Return only the requested output.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": temperature,
            }

            try:
                with httpx.Client(timeout=45.0) as client:
                    resp = client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        content = data["choices"][0]["message"]["content"].strip()
                        self._record_success(key)
                        self.last_used_provider = "openrouter"
                        self.last_used_model = OPENROUTER_MODEL
                        self.last_used_key_preview = f"{key[:6]}...{key[-4:]}"
                        return content
                    elif resp.status_code in [429, 402, 403]:
                        self._set_cooldown(key, 90.0, f"OpenRouter HTTP {resp.status_code}")
                    else:
                        errors.append(f"OpenRouter ({resp.status_code}): {resp.text[:80]}")
            except Exception as e:
                self._set_cooldown(key, 45.0, str(e)[:50])
                errors.append(str(e)[:80])

        raise RuntimeError(f"All OpenRouter pool keys failed: {'; '.join(errors[:3])}")

    # ── 3. Groq Pool ──────────────────────────────────────────────────────────

    def _call_groq_pool(self, prompt: str, temperature: float = 0.7) -> str:
        """Iterate over Groq keys pool."""
        if not self.groq_keys:
            raise ValueError("No Groq API keys configured in pool")

        errors = []
        sorted_keys = sorted(self.groq_keys, key=lambda k: self.cooldowns.get(k, 0))

        for key in sorted_keys:
            if self._is_cooling_down(key):
                continue

            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": "You are an expert examination question generator."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": temperature,
            }

            try:
                with httpx.Client(timeout=35.0) as client:
                    resp = client.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        content = data["choices"][0]["message"]["content"].strip()
                        self._record_success(key)
                        self.last_used_provider = "groq"
                        self.last_used_model = GROQ_MODEL
                        self.last_used_key_preview = f"{key[:6]}...{key[-4:]}"
                        return content
                    elif resp.status_code in [429, 403]:
                        self._set_cooldown(key, 90.0, f"Groq HTTP {resp.status_code}")
                    else:
                        errors.append(f"Groq ({resp.status_code}): {resp.text[:80]}")
            except Exception as e:
                self._set_cooldown(key, 45.0, str(e)[:50])
                errors.append(str(e)[:80])

        raise RuntimeError(f"All Groq pool keys failed: {'; '.join(errors[:3])}")

    # ── Main Cascade Generator ────────────────────────────────────────────────

    def generate(self, prompt: str, is_gk: bool = False, temperature: float = 0.7) -> str:
        """
        Execute generation with strict priority cascade across pools:
        1st Priority: Google Gemini Pool (rotating models and keys)
        2nd Priority: OpenRouter Pool (rotating keys)
        3rd Priority: Groq Pool (rotating keys)
        """
        cascade_errors = []

        # 1. Try Gemini Pool
        if self.gemini_keys:
            try:
                return self._call_gemini_pool(prompt, temperature=temperature)
            except Exception as e:
                cascade_errors.append(f"Gemini Pool: {str(e)[:120]}")

        # 2. Try OpenRouter Pool
        if self.openrouter_keys:
            try:
                logger.info("Cascading to OpenRouter keys pool...")
                return self._call_openrouter_pool(prompt, temperature=temperature)
            except Exception as e:
                cascade_errors.append(f"OpenRouter Pool: {str(e)[:120]}")

        # 3. Try Groq Pool
        if self.groq_keys:
            try:
                logger.info("Cascading to Groq keys pool...")
                return self._call_groq_pool(prompt, temperature=temperature)
            except Exception as e:
                cascade_errors.append(f"Groq Pool: {str(e)[:120]}")

        raise RuntimeError(f"All LLM key pools failed: {'; '.join(cascade_errors)}")

    def generate_json(
        self,
        prompt: str,
        is_gk: bool = False,
        temperature: float = 0.3,
    ) -> Optional[dict | list]:
        """Generate structured JSON with automatic markdown fence stripping."""
        json_prompt = (
            f"{prompt}\n\n"
            "CRITICAL: Return ONLY valid JSON (no markdown formatting, no ```json code fences, no introductory remarks)."
        )

        try:
            raw = self.generate(json_prompt, is_gk=is_gk, temperature=temperature)
        except Exception as e:
            logger.error(f"Multi-provider LLM generate_json failed: {e}")
            return None

        # Strip code fences
        cleaned = raw.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        # Extract JSON array or object
        match = re.search(r"(\[.*\]|\{.*\})", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error(f"JSONDecodeError: {e}\nRaw snippet: {raw[:200]}")
            return None

    def get_status(self) -> dict:
        """Return provider readiness and key counts for UI display."""
        active_gemini = len([k for k in self.gemini_keys if not self._is_cooling_down(k)])
        active_openrouter = len([k for k in self.openrouter_keys if not self._is_cooling_down(k)])
        active_groq = len([k for k in self.groq_keys if not self._is_cooling_down(k)])

        return {
            "gemini": {
                "name": "Google Gemini",
                "configured": len(self.gemini_keys) > 0,
                "key_count": len(self.gemini_keys),
                "active_key_count": active_gemini,
                "models": self.gemini_models,
                "priority": 1,
            },
            "openrouter": {
                "name": "OpenRouter",
                "configured": len(self.openrouter_keys) > 0,
                "key_count": len(self.openrouter_keys),
                "active_key_count": active_openrouter,
                "model": OPENROUTER_MODEL,
                "priority": 2,
            },
            "groq": {
                "name": "Groq Llama 4 Scout",
                "configured": len(self.groq_keys) > 0,
                "key_count": len(self.groq_keys),
                "active_key_count": active_groq,
                "model": GROQ_MODEL,
                "priority": 3,
            },
            "last_used_provider": self.last_used_provider,
            "last_used_model": self.last_used_model,
            "last_used_key": self.last_used_key_preview,
        }
