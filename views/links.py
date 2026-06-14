"""Links -- every site and file that matters, one click away.

Web links are plain anchors: they open in whatever browser hosts the
Scout window, which the launcher makes Chrome on purpose (saved logins
live there). Local shortcuts open in Explorer / Finder.
"""

import os
import subprocess
import sys

import streamlit as st

import config
import ui
import updater


def _open_local(path: str):
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def _render_updates():
    ui.section("Scout updates", "Get the latest version with one press")
    st.caption(f"You're on Scout **{updater.current_version()}**.")

    if st.button("Check for updates", width="stretch"):
        with st.spinner("Looking for a newer version…"):
            st.session_state["_update_check"] = updater.check()

    res = st.session_state.get("_update_check")
    if not res:
        return

    if not res["configured"]:
        st.info("Automatic updates aren't switched on for this copy yet — "
                "you've got the latest your installer gave you.")
    elif res["error"]:
        st.warning(res["error"])
    elif res["available"]:
        st.success(f"A newer Scout is ready: **{res['latest']}** "
                   f"(you have {res['current']}).")
        with st.expander("What's new", expanded=True):
            st.markdown(res["notes"] or "_No notes provided._")
        if st.button("Update now", type="primary", width="stretch"):
            with st.spinner("Updating Scout — this takes a few seconds…"):
                done = updater.apply_update()
            if done["ok"]:
                st.session_state.pop("_update_check", None)
                st.success(f"Updated to **{done['to_version']}**. "
                           "Close this window and open Scout again to finish.")
                st.balloons()
            else:
                st.error(done["error"])
                st.caption("Nothing was changed — your Scout is exactly as it was.")
    else:
        st.success(f"You're already up to date ({res['current']}).")


def render():
    _render_updates()

    for group, links in config.QUICK_LINKS.items():
        ui.section(group)
        ui.link_grid(links)

    if config.LOCAL_SHORTCUTS:
        ui.section("On this computer", "Opens in Explorer / your default app")
        cols = st.columns(4)
        for i, (label, path) in enumerate(config.LOCAL_SHORTCUTS):
            with cols[i % 4]:
                if st.button(label, key=f"local_{i}", width="stretch"):
                    try:
                        _open_local(path)
                    except OSError:
                        st.toast(f"Couldn't open {path}", icon="⚠️")
        st.caption("Edit QUICK_LINKS and LOCAL_SHORTCUTS in config.py to make this page yours.")
