from dataclasses import dataclass
from typing import Optional

import streamlit as st

from syllasift.storage.database import get_or_create_user


@dataclass(frozen=True)
class CurrentUser:
    is_authenticated: bool
    user_id: Optional[str] = None
    auth_subject: Optional[str] = None
    email: Optional[str] = None
    name: Optional[str] = None


GUEST_USER = CurrentUser(is_authenticated=False)


def auth_is_configured() -> bool:
    try:
        auth = st.secrets["auth"]
    except (KeyError, FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return False
    required = {
        "redirect_uri", "cookie_secret", "client_id", "client_secret",
        "server_metadata_url",
    }
    return required.issubset(auth)


def _identity_value(identity, key):
    value = getattr(identity, key, None)
    if value is not None:
        return value
    try:
        return identity.get(key)
    except AttributeError:
        return None


def resolve_current_user(identity=None) -> CurrentUser:
    identity = st.user if identity is None else identity
    if not bool(_identity_value(identity, "is_logged_in")):
        return GUEST_USER

    subject = _identity_value(identity, "sub")
    if not subject:
        raise RuntimeError("The identity provider did not return a subject ID.")
    email = _identity_value(identity, "email")
    name = _identity_value(identity, "name")
    user_id = get_or_create_user(subject, email)
    return CurrentUser(
        is_authenticated=True,
        user_id=user_id,
        auth_subject=str(subject),
        email=str(email) if email else None,
        name=str(name) if name else None,
    )


def display_authentication() -> CurrentUser:
    user = resolve_current_user()
    if user.is_authenticated:
        label = user.name or user.email or "Signed-in user"
        identity_column, action_column = st.columns([5, 1])
        identity_column.caption(f"Signed in as {label}")
        if action_column.button("Sign out"):
            st.logout()
        return user

    if auth_is_configured():
        if st.button("Sign in with Google"):
            st.login()
    else:
        st.caption(
            "Guest mode · Google sign-in is unavailable until OIDC secrets "
            "are configured."
        )
    return user
