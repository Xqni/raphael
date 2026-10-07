"""Self-evolution infrastructure (Wave 4 design: docs/evolution/01-self-evolution-infra.md).

This package is the *controller side*: zone classification, journal, and the
Core Guard verify / last-known-good rollback helpers. The Core Guard hash
manifest itself lives in qa-security's tests/core_guard_manifest.json — this
package verifies THROUGH that tool and never maintains a second copy
(AGENT_RULES §8: the guard is never weakened, only checked).
"""
