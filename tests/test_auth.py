import pytest

from syllasift import auth


def test_logged_out_identity_resolves_to_guest():
    user = auth.resolve_current_user({"is_logged_in": False})

    assert not user.is_authenticated
    assert user.user_id is None


def test_logged_in_identity_maps_subject_to_internal_user(monkeypatch):
    calls = []

    def fake_get_or_create(subject, email):
        calls.append((subject, email))
        return "internal-uuid"

    monkeypatch.setattr(auth, "get_or_create_user", fake_get_or_create)

    user = auth.resolve_current_user({
        "is_logged_in": True,
        "sub": "google-subject",
        "email": "student@example.com",
        "name": "Student",
    })

    assert user.is_authenticated
    assert user.user_id == "internal-uuid"
    assert user.auth_subject == "google-subject"
    assert calls == [("google-subject", "student@example.com")]


def test_logged_in_identity_requires_stable_subject():
    with pytest.raises(RuntimeError, match="subject ID"):
        auth.resolve_current_user({
            "is_logged_in": True,
            "email": "student@example.com",
        })


def test_display_authentication_recovers_missing_subject_as_guest(monkeypatch):
    errors = []
    logout_calls = []
    monkeypatch.setattr(
        auth,
        "resolve_current_user",
        lambda: (_ for _ in ()).throw(RuntimeError("missing subject")),
    )
    monkeypatch.setattr(auth.st, "error", errors.append)
    monkeypatch.setattr(
        auth.st, "button", lambda label, **kwargs: label == "Sign out and retry"
    )
    monkeypatch.setattr(auth.st, "logout", lambda: logout_calls.append(True))

    user = auth.display_authentication()

    assert user == auth.GUEST_USER
    assert "identity provider" in errors[0]
    assert logout_calls == [True]


def test_guest_choice_and_dialog_request_update_session_state(monkeypatch):
    state = {}
    monkeypatch.setattr(auth.st, "session_state", state)

    auth.request_sign_in_dialog()
    assert state[auth.AUTH_DIALOG_REQUESTED_KEY]

    auth.continue_as_guest()
    assert state[auth.AUTH_CHOICE_RESOLVED_KEY]
    assert not state[auth.AUTH_DIALOG_REQUESTED_KEY]


def test_auth_configuration_requires_every_google_setting(monkeypatch):
    configured = {
        "redirect_uri": "http://localhost:8501/oauth2callback",
        "cookie_secret": "secret",
        "client_id": "client",
        "client_secret": "client-secret",
        "server_metadata_url": "https://accounts.google.com/metadata",
    }
    monkeypatch.setattr(auth.st, "secrets", {"auth": configured})
    assert auth.auth_is_configured()

    incomplete = dict(configured)
    incomplete.pop("client_secret")
    monkeypatch.setattr(auth.st, "secrets", {"auth": incomplete})
    assert not auth.auth_is_configured()
