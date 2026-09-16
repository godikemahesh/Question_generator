"""
Google Gemini API client wrapper.
Handles API calls, rate limiting, retries, and structured JSON output.
"""
from __future__ import annotations
import json
import time
import logging
from typing import Optional

import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config.settings import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    MAX_REQUESTS_PER_MINUTE,
    PAUSE_BETWEEN_BATCHES_SECONDS,
)

logger = logging.getLogger(__name__)


class GeminiClient:
    """Wrapper around the Google Gemini API with rate limiting and retries."""

    def __init__(self, api_key: str = "", model_name: str = ""):
        self.api_key = api_key or GEMINI_API_KEY
        self.model_name = model_name or GEMINI_MODEL

        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not set. Add it to .env file.")

        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel(self.model_name)

        # Rate limiting
        self._request_timestamps: list[float] = []
        self._max_rpm = MAX_REQUESTS_PER_MINUTE
        self._pause_seconds = PAUSE_BETWEEN_BATCHES_SECONDS

        # Stats
        self.total_requests = 0
        self.total_tokens_used = 0

        logger.info(f"Gemini client initialized with model: {self.model_name}")

    def _enforce_rate_limit(self):
        """Ensure we don't exceed MAX_REQUESTS_PER_MINUTE."""
        now = time.time()
        # Remove timestamps older than 60 seconds
        self._request_timestamps = [
            ts for ts in self._request_timestamps if now - ts < 60
        ]

        if len(self._request_timestamps) >= self._max_rpm:
            # Calculate wait time
            oldest_in_window = self._request_timestamps[0]
            wait_time = 60 - (now - oldest_in_window) + 1
            if wait_time > 0:
                logger.info(f"Rate limit reached. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)

        self._request_timestamps.append(time.time())

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        retry=retry_if_exception_type((Exception,)),
        before_sleep=lambda retry_state: logger.warning(
            f"Retrying API call (attempt {retry_state.attempt_number})..."
        ),
    )
    def generate(self, prompt: str, temperature: float = 0.7) -> str:
        """
        Send a prompt to Gemini and return the text response.
        Includes rate limiting and retries.
        """
        self._enforce_rate_limit()

        generation_config = genai.types.GenerationConfig(
            temperature=temperature,
        )

        try:
            response = self.model.generate_content(
                prompt,
                generation_config=generation_config,
            )
            self.total_requests += 1

            if response.text:
                return response.text.strip()
            else:
                logger.warning("Empty response from Gemini")
                return ""

        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            raise

    def generate_json(self, prompt: str, temperature: float = 0.4) -> Optional[dict | list]:
        """
        Send a prompt and parse the response as JSON.
        Uses lower temperature for more deterministic structured output.
        """
        # Add JSON instruction to prompt
        json_prompt = prompt + "\n\nIMPORTANT: Respond with valid JSON only. No markdown, no code fences, no extra text."

        raw = self.generate(json_prompt, temperature=temperature)

        # Clean up response — remove markdown code fences if present
        cleaned = raw.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.debug(f"Raw response: {raw[:500]}")
            return None

    def pause_between_batches(self):
        """Sleep between generation batches to stay within rate limits."""
        logger.info(f"Pausing {self._pause_seconds}s between batches...")
        time.sleep(self._pause_seconds)

    def get_stats(self) -> dict:
        """Return usage statistics."""
        return {
            "total_requests": self.total_requests,
            "model": self.model_name,
        }
