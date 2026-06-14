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

    # Sticky post-update message: survives the reruns that st.balloons() and
    # any later click trigger, so the all-important restart step can't vanish.
    done_ver = st.session_state.get("_update_done")
    if done_ver:
        st.success(f"✅ Updated to **{done_ver}**!")
        st.info("**One last step:** close the Scout window, then open Scout "
                "again from the **Desktop icon**. (That's what loads the new "
                "version — your settings, accounts and data stay exactly as "
                "they are.)")
        if st.button("OK, got it", key="ack_update"):
            st.session_state.pop("_update_done", None)
            st.rerun()
        return  # don't show check/update controls until acknowledged

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
                st.session_state["_update_done"] = done["to_version"]
                # Stop the "newer version ready" banner from nagging now that
                # we've applied it (the cached check is otherwise stale 6h).
                st.cache_data.clear()
                st.balloons()
                st.rerun()
            else:
                st.error(done["error"])
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
