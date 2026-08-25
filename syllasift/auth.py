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
AUTH_CHOICE_RESOLVED_KEY = "auth_choice_resolved"
AUTH_DIALOG_REQUESTED_KEY = "auth_dialog_requested"


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


def continue_as_guest() -> None:
    st.session_state[AUTH_CHOICE_RESOLVED_KEY] = True
    st.session_state[AUTH_DIALOG_REQUESTED_KEY] = False


def request_sign_in_dialog() -> None:
    st.session_state[AUTH_DIALOG_REQUESTED_KEY] = True


@st.dialog(
    "Welcome to SyllaSift",
    dismissible=True,
    on_dismiss=continue_as_guest,
)
def display_sign_in_dialog() -> None:
    st.write(
        "Sign in to save courses and track progress across visits, "
        "or continue without an account."
    )
    configured = auth_is_configured()
    if not configured:
        st.info(
            "Google sign-in isn't set up on this installation. "
            "You can continue as a guest."
        )
    if st.button(
        "Sign in with Google",
        disabled=not configured,
        type="primary",
        key="auth_dialog_google_sign_in",
        width="stretch",
    ):
        st.login()
    if st.button(
        "Continue as guest",
        key="auth_dialog_continue_as_guest",
        width="stretch",
    ):
        continue_as_guest()
        st.rerun()


def display_authentication() -> CurrentUser:
    try:
        user = resolve_current_user()
    except RuntimeError:
        st.error(
            "Sign-in could not be verified because the identity provider "
            "did not return an account ID. Sign out and try again."
        )
        if st.button("Sign out and retry", key="invalid_identity_sign_out"):
            st.logout()
        return GUEST_USER
    if user.is_authenticated:
        st.session_state[AUTH_CHOICE_RESOLVED_KEY] = True
        st.session_state[AUTH_DIALOG_REQUESTED_KEY] = False
        label = user.name or user.email or "Signed-in user"
        auth_row = st.container(
            horizontal=True,
            horizontal_alignment="distribute",
            vertical_alignment="center",
        )
        auth_row.caption(f"Signed in as {label}")
        if auth_row.button("Sign out"):
            st.session_state.pop(AUTH_CHOICE_RESOLVED_KEY, None)
            st.session_state.pop(AUTH_DIALOG_REQUESTED_KEY, None)
            st.logout()
        return user

    should_show_dialog = (
        not st.session_state.get(AUTH_CHOICE_RESOLVED_KEY, False)
        or st.session_state.get(AUTH_DIALOG_REQUESTED_KEY, False)
    )
    if should_show_dialog:
        st.session_state[AUTH_DIALOG_REQUESTED_KEY] = False
        display_sign_in_dialog()

    auth_row = st.container(
        horizontal=True,
        horizontal_alignment="distribute",
        vertical_alignment="center",
    )
    auth_row.caption("Using SyllaSift as a guest")
    auth_row.button(
        "Sign in",
        on_click=request_sign_in_dialog,
        key="guest_header_sign_in",
    )
    return user
