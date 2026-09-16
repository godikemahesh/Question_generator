"""
Multi-Provider LLM Orchestrator with Strict Priority Fallback:
1st: Google Gemini
2nd: OpenRouter API (with real-time Web Search for General Knowledge & Current Affairs)
3rd: Groq API (Ultra-fast Llama 3.3 70B fallback)
"""
from __future__ import annotations
import json
import logging
import re
from typing import Optional, Any
import httpx

from config.settings import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL,
    GROQ_API_KEY,
    GROQ_MODEL,
)
from src.generator.gemini_client import GeminiClient

logger = logging.getLogger(__name__)


class MultiProviderLLM:
    """
    Orchestrates multi-provider LLM calls with automatic cascade fallback.
    - 1st: Gemini (primary)
    - 2nd: OpenRouter (with online web search for GK/Current Affairs)
    - 3rd: Groq (ultra-fast fallback)
    """

    def __init__(
        self,
        gemini_key: str = "",
        openrouter_key: str = "",
        groq_key: str = "",
    ):
        self.gemini_key = gemini_key or GEMINI_API_KEY
        self.openrouter_key = openrouter_key or OPENROUTER_API_KEY
        self.groq_key = groq_key or GROQ_API_KEY

        # Initialize primary Gemini
        self.gemini_client: Optional[GeminiClient] = None
        if self.gemini_key:
            try:
                self.gemini_client = GeminiClient(api_key=self.gemini_key)
            except Exception as e:
                logger.warning(f"Failed to initialize GeminiClient: {e}")

        # Active provider tracking
        self.last_used_provider: str = "gemini"

    def update_keys(self, gemini_key: str = "", openrouter_key: str = "", groq_key: str = ""):
        """Update API keys dynamically from admin UI settings."""
        if gemini_key:
            self.gemini_key = gemini_key
            try:
                self.gemini_client = GeminiClient(api_key=self.gemini_key)
            except Exception as e:
                logger.warning(f"Failed to re-initialize GeminiClient: {e}")
        if openrouter_key:
            self.openrouter_key = openrouter_key
        if groq_key:
            self.groq_key = groq_key

    # ── Call Implementations ──────────────────────────────────────────────────

    def _call_gemini(self, prompt: str, temperature: float = 0.7) -> str:
        if not self.gemini_client:
            raise ValueError("Gemini API key is not configured")
        return self.gemini_client.generate(prompt, temperature=temperature)

    def _call_openrouter(self, prompt: str, temperature: float = 0.7) -> str:
        if not self.openrouter_key:
            raise ValueError("OpenRouter API key is not configured")

        model = OPENROUTER_MODEL

        headers = {
            "Authorization": f"Bearer {self.openrouter_key}",
            "HTTP-Referer": "https://examforge-pink.vercel.app",
            "X-Title": "ExamForge Question Generator",
            "Content-Type": "application/json",
        }

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert exam question generator for competitive exams like RRB and DSC. "
                    "Provide accurate, educational, and high-quality multiple choice questions. Return only the requested output."
                ),
            },
            {"role": "user", "content": prompt},
        ]

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }

        with httpx.Client(timeout=60.0) as client:
            resp = client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"OpenRouter API error ({resp.status_code}): {resp.text}")
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()

    def _call_groq(self, prompt: str, temperature: float = 0.7) -> str:
        if not self.groq_key:
            raise ValueError("Groq API key is not configured")

        try:
            from groq import Groq
            client = Groq(api_key=self.groq_key)
            chat_completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are an expert examination question generator."},
                    {"role": "user", "content": prompt},
                ],
                model=GROQ_MODEL,
                temperature=temperature,
            )
            return chat_completion.choices[0].message.content.strip()
        except Exception as e:
            # Direct HTTP fallback
            headers = {
                "Authorization": f"Bearer {self.groq_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
            }
            with httpx.Client(timeout=45.0) as http_client:
                resp = http_client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers=headers,
                    json=payload,
                )
                if resp.status_code != 200:
                    raise RuntimeError(f"Groq API error ({resp.status_code}): {resp.text}")
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()

    # ── Cascade Generation Method ─────────────────────────────────────────────

    def generate(self, prompt: str, is_gk: bool = False, temperature: float = 0.7) -> str:
        """
        Execute generation with strict priority cascade:
        1st Priority: Gemini
        2nd Priority: OpenRouter
        3rd Priority: Groq
        """
        errors = []
        providers_order = ["gemini", "openrouter", "groq"]

        for provider in providers_order:
            try:
                if provider == "gemini":
                    result = self._call_gemini(prompt, temperature=temperature)
                    if result:
                        self.last_used_provider = "gemini"
                        return result
                elif provider == "openrouter":
                    result = self._call_openrouter(prompt, temperature=temperature)
                    if result:
                        self.last_used_provider = "openrouter"
                        return result
                elif provider == "groq":
                    result = self._call_groq(prompt, temperature=temperature)
                    if result:
                        self.last_used_provider = "groq"
                        return result
            except Exception as e:
                err_msg = f"{provider.capitalize()} failed: {str(e)[:150]}"
                logger.warning(err_msg)
                errors.append(err_msg)

        raise RuntimeError(f"All LLM providers failed: {'; '.join(errors)}")

    def generate_json(
        self,
        prompt: str,
        is_gk: bool = False,
        temperature: float = 0.3,
    ) -> Optional[dict | list]:
        """
        Generate structured JSON response with cascade fallback and markdown stripping.
        """
        json_prompt = (
            f"{prompt}\n\n"
            "CRITICAL: Return ONLY valid JSON (no markdown formatting, no ```json code fences, no introductory remarks)."
        )

        raw = self.generate(json_prompt, is_gk=is_gk, temperature=temperature)

        # Clean code fences
        cleaned = raw.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        # Extract JSON array or object if surrounded by extra text
        match = re.search(r"(\[.*\]|\{.*\})", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}\nRaw output: {raw[:300]}")
            return None

    def get_status(self) -> dict:
        """Return provider readiness status for UI indicator."""
        return {
            "gemini": {
                "name": "Google Gemini",
                "configured": bool(self.gemini_key),
                "model": GEMINI_MODEL,
                "priority": 1,
            },
            "openrouter": {
                "name": "OpenRouter",
                "configured": bool(self.openrouter_key),
                "model": OPENROUTER_MODEL,
                "priority": 2,
            },
            "groq": {
                "name": "Groq Llama 3.3 70B",
                "configured": bool(self.groq_key),
                "model": GROQ_MODEL,
                "priority": 3,
            },
            "last_used_provider": self.last_used_provider,
        }
