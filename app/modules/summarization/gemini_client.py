import json
import re
from time import perf_counter
from typing import Any, Literal

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import Settings, get_settings
from app.core.exceptions import ExternalServiceError
from app.modules.email_source.interface import EmailMessage
from app.modules.summarization.prompts import REDUCE_PROMPT
from app.modules.summarization.schemas import (
    Actor,
    ConcludedDiscussion,
    GeminiSummarySchema,
    OpenActionItem,
)
from app.observability.metrics import GEMINI_CALLS_TOTAL, GEMINI_FAILURES_TOTAL, GEMINI_LATENCY_SECONDS

EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}")
NAME_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


class GeminiClient:
    """Client for structured summary generation, with a deterministic mock fallback."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def summarize_emails(self, emails: list[EmailMessage]) -> GeminiSummarySchema:
        if self.settings.use_mock_gemini or not self.settings.gemini_api_key:
            return self._mock_summary(emails)
        return await self._call_gemini(emails)

    async def merge_summaries(self, summaries: list[GeminiSummarySchema]) -> GeminiSummarySchema:
        if not summaries:
            return GeminiSummarySchema(actors=[], concluded_discussions=[], open_action_items=[])
        if not self.settings.use_mock_gemini and self.settings.gemini_api_key:
            return await self._call_gemini_with_prompt(self._build_merge_prompt(summaries))
        return self._merge_locally(summaries)

    def _merge_locally(self, summaries: list[GeminiSummarySchema]) -> GeminiSummarySchema:
        merged = GeminiSummarySchema(
            actors=[],
            concluded_discussions=[],
            open_action_items=[],
        )
        actor_seen: set[tuple[str, str | None, str, str | None]] = set()
        concluded_seen: set[tuple[str, str]] = set()
        action_seen: set[tuple[str, str, str]] = set()

        for summary in summaries:
            for actor in summary.actors:
                actor_key = (actor.name.lower(), actor.email, actor.source, actor.role)
                if actor_key not in actor_seen:
                    merged.actors.append(actor)
                    actor_seen.add(actor_key)
            for discussion in summary.concluded_discussions:
                concluded_key = (discussion.topic.lower(), discussion.resolution.lower())
                if concluded_key not in concluded_seen:
                    merged.concluded_discussions.append(discussion)
                    concluded_seen.add(concluded_key)
            for item in summary.open_action_items:
                action_key = (item.item.lower(), item.owner.lower(), item.context.lower())
                if action_key not in action_seen:
                    merged.open_action_items.append(item)
                    action_seen.add(action_key)
        return merged

    @retry(
        reraise=True,
        retry=retry_if_exception_type((httpx.HTTPError, ExternalServiceError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=6),
    )
    async def _call_gemini(self, emails: list[EmailMessage]) -> GeminiSummarySchema:
        return await self._call_gemini_with_prompt(self._build_prompt(emails))

    async def _call_gemini_with_prompt(self, prompt: str) -> GeminiSummarySchema:
        GEMINI_CALLS_TOTAL.inc()
        start = perf_counter()
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.settings.gemini_model}:generateContent"
        )
        try:
            async with httpx.AsyncClient(timeout=self.settings.gemini_timeout_seconds) as client:
                response = await client.post(
                    url,
                    params={"key": self.settings.gemini_api_key},
                    json={"contents": [{"parts": [{"text": prompt}]}]},
                )
                response.raise_for_status()
        except httpx.HTTPError:
            GEMINI_FAILURES_TOTAL.inc()
            raise
        finally:
            GEMINI_LATENCY_SECONDS.observe(perf_counter() - start)

        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        try:
            payload = json.loads(text.strip().removeprefix("```json").removesuffix("```").strip())
        except json.JSONDecodeError as exc:
            GEMINI_FAILURES_TOTAL.inc()
            raise ExternalServiceError("Gemini returned invalid JSON") from exc
        return GeminiSummarySchema.model_validate(payload)

    def _mock_summary(self, emails: list[EmailMessage]) -> GeminiSummarySchema:
        actors: list[Actor] = []
        concluded: list[ConcludedDiscussion] = []
        open_items: list[OpenActionItem] = []
        actor_seen: set[tuple[str, str | None, str, str | None]] = set()

        def add_actor(
            name: str,
            email: str | None,
            source: Literal["header", "body"],
            role: Literal["sender", "recipient", "cc", "mentioned"] | None,
        ) -> None:
            normalized_email = email.lower() if email else None
            key = (name.lower(), normalized_email, source, role)
            if key not in actor_seen:
                actors.append(
                    Actor(
                        name=name,
                        email=normalized_email,
                        source=source,
                        role=role,
                    )
                )
                actor_seen.add(key)

        for email in emails:
            add_actor(self._name_from_email(email.sender_email), email.sender_email, "header", "sender")
            for recipient in email.recipients:
                add_actor(self._name_from_email(recipient), recipient, "header", "recipient")
            for cc in email.cc:
                add_actor(self._name_from_email(cc), cc, "header", "cc")

            known_emails = {match.group(0).lower() for match in EMAIL_RE.finditer(email.body)}
            for mentioned_email in known_emails:
                add_actor(self._name_from_email(mentioned_email), mentioned_email, "body", "mentioned")

            for name in NAME_RE.findall(email.body):
                if name.lower() not in {"Please", "Thanks", "Regards", "Hi", "Hello"}:
                    add_actor(name, None, "body", "mentioned")

            for sentence in self._sentences(email.body):
                lowered = sentence.lower()
                if any(word in lowered for word in ("resolved", "approved", "complete", "confirmed", "closed")):
                    concluded.append(
                        ConcludedDiscussion(
                            topic=email.subject,
                            resolution=sentence[:500],
                            resolved_at=email.sent_at,
                            resolved_in_thread_id=email.thread_id,
                        )
                    )
                if any(
                    phrase in lowered
                    for phrase in ("please", "need", "send", "provide", "follow up", "waiting")
                ):
                    owner = self._infer_owner(sentence)
                    open_items.append(
                        OpenActionItem(
                            item=sentence[:300],
                            owner=owner,
                            context=f"{email.subject} ({email.thread_id})",
                            raised_at=email.sent_at,
                        )
                    )

        return GeminiSummarySchema(
            actors=actors,
            concluded_discussions=self._dedupe_concluded(concluded),
            open_action_items=self._dedupe_actions(open_items),
        )

    def _build_prompt(self, emails: list[EmailMessage]) -> str:
        serializable: list[dict[str, Any]] = [
            {
                "thread_id": email.thread_id,
                "subject": email.subject,
                "from": email.sender_email,
                "to": email.recipients,
                "cc": email.cc,
                "body": email.body,
                "sent_at": email.sent_at.isoformat(),
                "direction": email.direction,
            }
            for email in emails
        ]
        return (
            "Return strict JSON matching this schema: "
            "{actors:[{name,email,source,role}],"
            "concluded_discussions:[{topic,resolution,resolved_at,resolved_in_thread_id}],"
            "open_action_items:[{item,owner,context,raised_at}]}.\n\n"
            f"Emails:\n{json.dumps(serializable, default=str)}"
        )

    def _build_merge_prompt(self, summaries: list[GeminiSummarySchema]) -> str:
        partials = [summary.model_dump(mode="json") for summary in summaries]
        return (
            f"{REDUCE_PROMPT}\n"
            "Return strict JSON matching this schema: "
            "{actors:[{name,email,source,role}],"
            "concluded_discussions:[{topic,resolution,resolved_at,resolved_in_thread_id}],"
            "open_action_items:[{item,owner,context,raised_at}]}.\n\n"
            f"Partial summaries:\n{json.dumps(partials, default=str)}"
        )

    def _name_from_email(self, email: str) -> str:
        local = email.split("@", 1)[0]
        return " ".join(part.capitalize() for part in re.split(r"[._-]+", local) if part) or email

    def _sentences(self, body: str) -> list[str]:
        return [sentence.strip() for sentence in SENTENCE_RE.split(body.replace("\n", " ")) if sentence.strip()]

    def _infer_owner(self, sentence: str) -> str:
        lowered = sentence.lower()
        if "client" in lowered:
            return "client"
        if "we " in lowered or "our " in lowered:
            return "firm"
        for match in NAME_RE.findall(sentence):
            if match.lower() not in {"Please", "Need"}:
                return str(match)
        return "unassigned"

    def _dedupe_concluded(
        self,
        discussions: list[ConcludedDiscussion],
    ) -> list[ConcludedDiscussion]:
        seen: set[tuple[str, str]] = set()
        output: list[ConcludedDiscussion] = []
        for discussion in discussions:
            key = (discussion.topic.lower(), discussion.resolution.lower())
            if key not in seen:
                output.append(discussion)
                seen.add(key)
        return output

    def _dedupe_actions(self, items: list[OpenActionItem]) -> list[OpenActionItem]:
        seen: set[tuple[str, str, str]] = set()
        output: list[OpenActionItem] = []
        for item in items:
            key = (item.item.lower(), item.owner.lower(), item.context.lower())
            if key not in seen:
                output.append(item)
                seen.add(key)
        return output
