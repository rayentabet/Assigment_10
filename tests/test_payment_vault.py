import pytest

from app.payment_vault import CredentialError, authorize, clear, forget, tokenize


@pytest.fixture(autouse=True)
def empty_vault():
    clear()
    yield
    clear()


def test_tokenization_keeps_only_non_sensitive_metadata() -> None:
    result = tokenize("4242 4242 4242 4242", "12/30", "123")
    credential = authorize(result["credential_id"])

    assert result["credential_id"].startswith("cp_test_")
    assert credential.last4 == "4242"
    assert not hasattr(credential, "card_number")
    assert not hasattr(credential, "cvv")
    assert not hasattr(credential, "expiry")


def test_credential_is_reusable_and_can_be_forgotten() -> None:
    result = tokenize("4242424242424242", "12/30", "123")

    assert authorize(result["credential_id"]).last4 == "4242"
    assert authorize(result["credential_id"]).last4 == "4242"
    assert forget(result["credential_id"]) is True
    with pytest.raises(CredentialError, match="unknown"):
        authorize(result["credential_id"])


def test_only_documented_sandbox_card_is_accepted() -> None:
    with pytest.raises(CredentialError, match="sandbox test card"):
        tokenize("5555 5555 5555 4444", "12/30", "123")
