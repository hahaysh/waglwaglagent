import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from app.routing import Candidate, Failure, eligible_candidates, may_fallback


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(UTC)
        self.candidate = Candidate(
            credential_id="key-1",
            owner_id="alice",
            provider="openrouter",
            model="vendor/model:free",
            approved=True,
            free_verified_until=self.now + timedelta(minutes=5),
            upstreams=("approved-provider",),
        )

    def test_only_own_approved_verified_free_candidates(self):
        rejected = [
            replace(self.candidate, owner_id="bob"),
            replace(self.candidate, approved=False),
            replace(self.candidate, free_verified_until=None),
            replace(self.candidate, free_verified_until=self.now),
            replace(self.candidate, model="vendor/paid"),
            replace(self.candidate, upstreams=()),
            replace(self.candidate, available=False),
            replace(self.candidate, provider="unknown"),
        ]
        self.assertEqual(eligible_candidates(rejected, "alice", self.now), [])
        self.assertEqual(
            eligible_candidates([self.candidate], "alice", self.now),
            [self.candidate],
        )

    def test_gemini_requires_free_tier_evidence(self):
        candidate = replace(
            self.candidate,
            provider="gemini",
            model="gemini-reviewed-model",
            free_verified_until=None,
        )
        self.assertEqual(eligible_candidates([candidate], "alice", self.now), [])

    def test_priority_does_not_override_ownership(self):
        other = replace(self.candidate, owner_id="bob", priority=-100)
        second = replace(self.candidate, credential_id="key-2", priority=5)
        self.assertEqual(
            eligible_candidates([second, other, self.candidate], "alice", self.now),
            [self.candidate, second],
        )

    def test_copilot_requires_auto_and_explicit_github_upstream_consent(self):
        candidate = replace(
            self.candidate, provider="copilot", model="auto", upstreams=("github-copilot",),
        )
        self.assertEqual(eligible_candidates([candidate], "alice", self.now), [candidate])
        rejected = [
            replace(candidate, model="paid-model"),
            replace(candidate, upstreams=()),
            replace(candidate, free_verified_until=None),
        ]
        self.assertEqual(eligible_candidates(rejected, "alice", self.now), [])

    def test_no_fallback_after_partial_output_or_refusal(self):
        for failure in Failure:
            self.assertFalse(may_fallback(failure, True, 1))
        for failure in [Failure.AUTH, Failure.REFUSAL, Failure.INVALID]:
            self.assertFalse(may_fallback(failure, False, 1))
        self.assertTrue(may_fallback(Failure.TRANSIENT, False, 1))
        self.assertTrue(may_fallback(Failure.EXHAUSTED, False, 2))
        self.assertFalse(may_fallback(Failure.TRANSIENT, False, 3))


if __name__ == "__main__":
    unittest.main()
