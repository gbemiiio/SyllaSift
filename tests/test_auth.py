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
