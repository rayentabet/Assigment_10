import pytest

from app.payment_vault import (
    CredentialError,
    SandboxCredentialProvider,
    authorize,
    clear,
    forget,
    provider,
    public,
    tokenize,
)


@pytest.fixture(autouse=True)
def empty_vault():
    clear()
    yield
    clear()


def test_lithic_handle_keeps_only_non_sensitive_metadata() -> None:
    method = provider.create_payment_method()
    result = public(method)
    credential = authorize(result["payment_method_id"])

    assert result["payment_method_id"].startswith("pm_")
    assert credential.last4 is None
    assert not hasattr(credential, "card_number")
    assert not hasattr(credential, "cvv")
    assert not hasattr(credential, "expiry")
    assert credential.display == "Lithic single-use Virtual Visa"
    assert "provider_reference" not in result


def test_credential_is_reusable_and_can_be_forgotten() -> None:
    result = public(provider.create_payment_method())

    assert authorize(result["payment_method_id"]).last4 is None
    assert authorize(result["payment_method_id"]).last4 is None
    assert forget(result["payment_method_id"]) is True
    with pytest.raises(CredentialError, match="unknown"):
        authorize(result["payment_method_id"])


def test_raw_card_tokenization_is_disabled_for_lithic() -> None:
    with pytest.raises(CredentialError, match="Raw-card tokenization is disabled"):
        tokenize("5555 5555 5555 4444", "12/30", "123")


def test_optional_local_sandbox_provider_remains_isolated() -> None:
    sandbox = SandboxCredentialProvider()
    method = sandbox.tokenize("4242 4242 4242 4242", "12/30", "123")

    assert method.display == "Local test Visa ending 4242"
    assert method.provider_reference.startswith("cp_test_")
    assert not hasattr(method, "card_number")
    assert not hasattr(method, "cvv")
    assert not hasattr(method, "expiry")
