from collections.abc import Callable

import streamlit.components.v1 as components


def build_reload_guard_html(is_dirty: bool) -> str:
    """Build the small parent-window script used for reload protection."""
    dirty_literal = "true" if is_dirty else "false"
    return f"""
<script>
(() => {{
  const parentWindow = window.parent;
  const existing = parentWindow.__syllasiftBeforeUnload;
  if (existing) {{
    parentWindow.removeEventListener("beforeunload", existing);
    delete parentWindow.__syllasiftBeforeUnload;
  }}
  if ({dirty_literal}) {{
    const handler = (event) => {{
      event.preventDefault();
      event.returnValue = "";
    }};
    parentWindow.__syllasiftBeforeUnload = handler;
    parentWindow.addEventListener("beforeunload", handler);
  }}
}})();
</script>
""".strip()


def render_reload_guard(
    is_dirty: bool,
    renderer: Callable[..., object] = components.html,
) -> None:
    renderer(
        build_reload_guard_html(is_dirty),
        height=0,
        width=0,
    )
