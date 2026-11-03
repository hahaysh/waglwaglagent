from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Failure(StrEnum):
    TRANSIENT = "transient"
    EXHAUSTED = "exhausted"
    AUTH = "auth"
    REFUSAL = "refusal"
    INVALID = "invalid"


@dataclass(frozen=True)
class Candidate:
    credential_id: str
    owner_id: str
    provider: str
    model: str
    approved: bool
    free_verified_until: datetime | None
    upstreams: tuple[str, ...] = ()
    priority: int = 0
    available: bool = True


def eligible_candidates(
    candidates: list[Candidate], owner_id: str, now: datetime
) -> list[Candidate]:
    return sorted(
        [
            candidate
            for candidate in candidates
            if candidate.owner_id == owner_id
            and candidate.approved
            and candidate.available
            and candidate.free_verified_until is not None
            and candidate.free_verified_until > now
            and (
                candidate.provider == "gemini"
                or (
                    candidate.provider == "openrouter"
                    and candidate.model.endswith(":free")
                    and bool(candidate.upstreams)
                )
            )
        ],
        key=lambda candidate: candidate.priority,
    )


def may_fallback(failure: Failure, emitted_text: bool, attempts: int) -> bool:
    return not emitted_text and attempts < 3 and failure in {Failure.TRANSIENT, Failure.EXHAUSTED}
