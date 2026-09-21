"""
Web Search Manager with 3-Tier Free Provider Cascade:
1. Tavily: 1,000 free requests/month
2. Brave Search: $5/month (~1,000 free searches)
3. Exa Search: $10/month (~1,428 free searches)
Combined Free Capacity: ~3,428 basic searches/month.

Provides real-time grounded search context for General Knowledge and Current Affairs questions.
"""
import logging
from typing import Optional
import httpx

from config.settings import (
    TAVILY_API_KEY,
    BRAVE_API_KEY,
    EXA_API_KEY,
    WEB_SEARCH_ENABLED,
)

logger = logging.getLogger(__name__)


class WebSearchManager:
    """Cascading web search manager across Tavily, Brave, and Exa."""

    def __init__(
        self,
        tavily_key: Optional[str] = None,
        brave_key: Optional[str] = None,
        exa_key: Optional[str] = None,
        enabled: Optional[bool] = None,
    ):
        self.tavily_key = (tavily_key if tavily_key is not None else TAVILY_API_KEY) or ""
        self.brave_key = (brave_key if brave_key is not None else BRAVE_API_KEY) or ""
        self.exa_key = (exa_key if exa_key is not None else EXA_API_KEY) or ""
        self.enabled = enabled if enabled is not None else WEB_SEARCH_ENABLED
        self.smart_enabled = True
        self.last_provider_used: Optional[str] = None

    def reload_config(self, config: dict):
        """Update keys and toggle from runtime database config."""
        if "tavily_api_key" in config and config["tavily_api_key"] is not None:
            self.tavily_key = config["tavily_api_key"].strip()
        if "brave_api_key" in config and config["brave_api_key"] is not None:
            self.brave_key = config["brave_api_key"].strip()
        if "exa_api_key" in config and config["exa_api_key"] is not None:
            self.exa_key = config["exa_api_key"].strip()
        if "web_search_enabled" in config and config["web_search_enabled"] is not None:
            self.enabled = bool(config["web_search_enabled"])
        if "smart_search_enabled" in config and config["smart_search_enabled"] is not None:
            self.smart_enabled = bool(config["smart_search_enabled"])

    def detect_realworld_need(self, subject_name: str, topic_name: str, concepts: list | None = None) -> tuple[bool, str]:
        """
        Smart Real-World Intent Detector:
        Analyzes subject, topic, and sub-concepts to determine whether live online web search
        is required to ensure real-world accuracy (e.g. current events, policies, latest discoveries,
        laws, schemes, awards, statistics, or recency words).
        
        Returns: (needs_search: bool, search_query: str)
        """
        import re
        if not self.enabled or not self.smart_enabled:
            return False, ""

        text_to_check = f"{subject_name} {topic_name} "
        if concepts:
            for c in concepts[:4]:
                if isinstance(c, dict):
                    text_to_check += f"{c.get('name', '')} {c.get('description', '')} "
                elif isinstance(c, str):
                    text_to_check += f"{c} "
        text_lower = text_to_check.lower()

        # 1. Subject-level triggers
        gk_triggers = ["general knowledge", "gk", "current affairs", "general studies", "general awareness", "contemporary"]
        if any(t in text_lower for t in gk_triggers):
            return True, f"{subject_name} {topic_name} current developments facts 2024 2025"

        # 2. Temporal & Recency triggers
        recency_keywords = [
            "2023", "2024", "2025", "2026", "recent", "current", "latest", "newest", "modern developments",
            "recently", "amendment", "update", "new policy", "ongoing", "upcoming", "contemporary"
        ]
        if any(re.search(r'\b' + re.escape(w) + r'\b', text_lower) for w in recency_keywords):
            return True, f"{subject_name} {topic_name} latest updates facts 2024 2025"

        # 3. Governance, Laws, Schemes, International Organizations
        governance_keywords = [
            "government scheme", "yojana", "act", "statute", "policy", "national policy", "nep", "rbi",
            "budget", "census", "treaty", "summit", "g20", "brics", "cop", "un", "unesco", "who",
            "isro", "nasa", "drdo", "mission", "satellite", "index", "ranking", "olympics", "world cup",
            "sports award", "padma", "bharat ratna", "nobel prize", "appointment", "chief justice", "election"
        ]
        if any(re.search(r'\b' + re.escape(w) + r'\b', text_lower) for w in governance_keywords):
            return True, f"{subject_name} {topic_name} official facts updates"

        # 4. Special Ed & Welfare Policies (e.g. RPwD Act notifications, government guidelines)
        special_ed_policy_keywords = [
            "rpwd", "pwd act", "national institute", "rehabilitation council", "rci", "schemes for disabled",
            "accessible india", "sugamya bharat", "udid card", "nep 2020 inclusive education"
        ]
        if any(w in text_lower for w in special_ed_policy_keywords):
            return True, f"{subject_name} {topic_name} government schemes guidelines updates"

        return False, ""

    def _search_tavily(self, query: str, num_results: int = 5) -> list[dict]:
        """Tavily Search API (1,000 free credits/month)."""
        if not self.tavily_key:
            raise ValueError("Tavily API key not configured")

        url = "https://api.tavily.com/search"
        payload = {
            "api_key": self.tavily_key,
            "query": query,
            "search_depth": "basic",
            "max_results": num_results,
            "include_answer": False,
        }
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"Tavily error ({resp.status_code}): {resp.text[:200]}")
            data = resp.json()
            raw_results = data.get("results", [])
            snippets = []
            for r in raw_results:
                snippets.append({
                    "title": r.get("title", ""),
                    "snippet": r.get("content", ""),
                    "url": r.get("url", ""),
                    "provider": "tavily",
                })
            return snippets

    def _search_brave(self, query: str, num_results: int = 5) -> list[dict]:
        """Brave Web Search API ($5/month ~1,000 free searches)."""
        if not self.brave_key:
            raise ValueError("Brave API key not configured")

        url = "https://api.search.brave.com/res/v1/web/search"
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.brave_key,
        }
        params = {
            "q": query,
            "count": num_results,
        }
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, headers=headers, params=params)
            if resp.status_code != 200:
                raise RuntimeError(f"Brave Search error ({resp.status_code}): {resp.text[:200]}")
            data = resp.json()
            raw_results = data.get("web", {}).get("results", [])
            snippets = []
            for r in raw_results:
                snippets.append({
                    "title": r.get("title", ""),
                    "snippet": r.get("description", ""),
                    "url": r.get("url", ""),
                    "provider": "brave",
                })
            return snippets

    def _search_exa(self, query: str, num_results: int = 5) -> list[dict]:
        """Exa Search API ($10/month ~1,428 free searches)."""
        if not self.exa_key:
            raise ValueError("Exa API key not configured")

        url = "https://api.exa.ai/search"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.exa_key,
        }
        payload = {
            "query": query,
            "numResults": num_results,
            "contents": {
                "text": {"maxCharacters": 400}
            },
        }
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"Exa Search error ({resp.status_code}): {resp.text[:200]}")
            data = resp.json()
            raw_results = data.get("results", [])
            snippets = []
            for r in raw_results:
                snippets.append({
                    "title": r.get("title", ""),
                    "snippet": r.get("text", ""),
                    "url": r.get("url", ""),
                    "provider": "exa",
                })
            return snippets

    def search(self, query: str, num_results: int = 5) -> dict:
        """
        Execute cascading search:
        1st Priority: Tavily (1,000/mo)
        2nd Priority: Brave (~1,000/mo)
        3rd Priority: Exa (~1,428/mo)
        """
        if not self.enabled:
            return {
                "provider_used": "none",
                "query": query,
                "snippets": [],
                "formatted_context": "",
                "message": "Web search is disabled in settings.",
            }

        errors = []
        providers = [
            ("tavily", self._search_tavily),
            ("brave", self._search_brave),
            ("exa", self._search_exa),
        ]

        for prov_name, search_fn in providers:
            try:
                snippets = search_fn(query, num_results=num_results)
                if snippets:
                    self.last_provider_used = prov_name
                    lines = [f"[Real-Time Verified Web Search Results via {prov_name.capitalize()}]"]
                    for idx, s in enumerate(snippets, 1):
                        lines.append(f"{idx}. {s['title']}: {s['snippet']} (Source: {s['url']})")
                    return {
                        "provider_used": prov_name,
                        "query": query,
                        "snippets": snippets,
                        "formatted_context": "\n".join(lines),
                    }
            except Exception as e:
                errors.append(f"{prov_name}: {e}")
                logger.warning(f"Web search provider {prov_name} failed: {e}")

        # All providers failed or not configured
        self.last_provider_used = "none"
        return {
            "provider_used": "none",
            "query": query,
            "snippets": [],
            "formatted_context": "",
            "errors": errors,
        }

    def get_status(self) -> dict:
        """Return status of search provider cascade and free quota summary."""
        return {
            "enabled": self.enabled,
            "last_used": self.last_provider_used,
            "providers": [
                {
                    "name": "Tavily",
                    "priority": 1,
                    "has_key": bool(self.tavily_key),
                    "free_allowance": "1,000 credits/month (~1,000 basic searches)",
                },
                {
                    "name": "Brave Search",
                    "priority": 2,
                    "has_key": bool(self.brave_key),
                    "free_allowance": "$5/month (~1,000 basic searches)",
                },
                {
                    "name": "Exa",
                    "priority": 3,
                    "has_key": bool(self.exa_key),
                    "free_allowance": "$10/month (~1,428 basic searches)",
                },
            ],
            "total_free_searches_approx": 3428,
        }
