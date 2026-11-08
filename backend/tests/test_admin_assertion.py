"""Unit tests for security.admin_assertion (pure, no AWS)."""

import pytest

from security.admin_assertion import MAX_AGE_SECONDS, AssertionInvalid, sign, verify

KEY = b"k" * 64
NOW = 1_762_548_000
NONCE = "0123456789abcdef0123456789abcdef"


def make(action="REVOKE_AGENT", admin="alice@scu.edu", issued_at=NOW, nonce=NONCE, key=KEY, **override):
    assertion = {
        "admin": admin,
        "action": action,
        "issued_at": issued_at,
        "nonce": nonce,
        "signature": sign(key, action, admin, issued_at, nonce),
    }
    assertion.update(override)
    return assertion


def test_valid_assertion_returns_claims():
    claims = verify(make(), key=KEY, expected_action="REVOKE_AGENT", now=NOW + 10)

    assert claims == {"admin": "alice@scu.edu", "action": "REVOKE_AGENT", "issued_at": NOW, "nonce": NONCE}


@pytest.mark.parametrize(
    "assertion, now",
    [
        pytest.param(None, NOW, id="missing"),
        pytest.param("admin", NOW, id="plain-string"),
        pytest.param({"admin": "alice@scu.edu"}, NOW, id="admin-name-only"),
        pytest.param(make(action="RESET_DEMO"), NOW, id="wrong-action"),
        pytest.param(make(key=b"x" * 64), NOW, id="wrong-key"),
        pytest.param({**make(), "admin": "mallory"}, NOW, id="admin-swapped-after-signing"),
        pytest.param(make(), NOW + MAX_AGE_SECONDS + 1, id="expired"),
        pytest.param(make(issued_at=NOW + 60), NOW, id="from-future"),
        pytest.param({**make(), "extra": 1}, NOW, id="extra-field"),
        pytest.param(make(nonce="short"), NOW, id="bad-nonce"),
        pytest.param({**make(), "signature": "zz"}, NOW, id="bad-signature-format"),
        pytest.param(make(issued_at=float(NOW)), NOW, id="float-timestamp"),
        pytest.param(make(admin="a|b"), NOW, id="pipe-in-admin"),
    ],
)
def test_invalid_assertions_are_rejected(assertion, now):
    with pytest.raises(AssertionInvalid):
        verify(assertion, key=KEY, expected_action="REVOKE_AGENT", now=now)


def test_signature_for_tampered_admin_does_not_verify():
    signed_for_alice = make()
    forged = {**signed_for_alice, "admin": "mallory"}

    with pytest.raises(AssertionInvalid):
        verify(forged, key=KEY, expected_action="REVOKE_AGENT", now=NOW)


@pytest.mark.parametrize("key", [b"", b"short", None, "k" * 64])
def test_unconfigured_or_weak_key_fails_closed(key):
    with pytest.raises(AssertionInvalid):
        verify(make(), key=key, expected_action="REVOKE_AGENT", now=NOW)


def test_unknown_protected_action_fails_closed():
    with pytest.raises(AssertionInvalid):
        verify(make(), key=KEY, expected_action="DELETE_EVERYTHING", now=NOW)
