import streamlit as st
import pandas as pd

FILE = "onsite_testing_master.xlsx"

st.set_page_config(layout="wide")
st.title("LAA On-Site Chromebook Scanner")

def load_df() -> pd.DataFrame:
    return pd.read_excel(FILE, dtype=str).fillna("")

def save_df(d: pd.DataFrame) -> None:
    d.to_excel(FILE, index=False)

# ---- session state defaults ----
for k, v in {
    "scan_input": "",
    "pending_asset": "",
    "pending_kind": "",     # success/warn/error
    "pending_message": "",
    "last_scanned": "",
    "last_result": "",
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

def handle_scan_change():
    """Runs when the scan box changes. Processes scan, then clears the box safely."""
    df = load_df()
    raw = st.session_state.scan_input.strip()

    if not raw:
        return

    st.session_state.last_scanned = raw

    if raw in df["AssetID"].astype(str).values:
        current = df.loc[df["AssetID"].astype(str) == raw, "Collected"].astype(str).values[0].strip()

        st.session_state.pending_asset = raw

        if current.upper() == "YES":
            st.session_state.pending_kind = "success"
            st.session_state.pending_message = f"{raw} is already marked as COLLECTED."
        else:
            st.session_state.pending_kind = "warn"
            st.session_state.pending_message = f"{raw} found. Not yet collected — confirm to mark as collected."

    else:
        st.session_state.pending_asset = ""
        st.session_state.pending_kind = "error"
        st.session_state.pending_message = f"{raw} NOT FOUND in On-Site list."

    # ✅ Safe clear happens inside callback
    st.session_state.scan_input = ""

# ---- UI ----
st.header("Scanner")

left, right = st.columns([2, 1], vertical_alignment="top")

with left:
    st.caption("Scan one computer at a time. The box clears automatically after each scan.")

    st.text_input(
        "Scan AssetID",
        key="scan_input",
        placeholder="Scan now…",
        on_change=handle_scan_change
    )

with right:
    st.subheader("Last scan")
    st.write(f"**{st.session_state.last_scanned or '—'}**")
    if st.session_state.last_result:
        st.write(st.session_state.last_result)

# ---- Pending action area ----
if st.session_state.pending_message:
    kind = st.session_state.pending_kind

    if kind == "success":
        st.success(st.session_state.pending_message)
        if st.button("OK (next computer)"):
            st.session_state.last_result = "✅ Already collected"
            st.session_state.pending_message = ""
            st.session_state.pending_kind = ""
            st.session_state.pending_asset = ""

    elif kind == "warn":
        st.warning(st.session_state.pending_message)
        c1, c2 = st.columns(2)

        with c1:
            if st.button("Confirm Collected ✅"):
                df2 = load_df()
                asset = st.session_state.pending_asset
                df2.loc[df2["AssetID"].astype(str) == asset, "Collected"] = "YES"
                save_df(df2)

                st.session_state.last_result = "✅ Marked collected"
                st.session_state.pending_message = ""
                st.session_state.pending_kind = ""
                st.session_state.pending_asset = ""
                st.success("Saved. Ready for next computer.")

        with c2:
            if st.button("Cancel ❌"):
                st.session_state.last_result = "❌ Cancelled (no change)"
                st.session_state.pending_message = ""
                st.session_state.pending_kind = ""
                st.session_state.pending_asset = ""
                st.info("Cancelled. Ready for next computer.")

    else:
        st.error(st.session_state.pending_message)
        if st.button("OK (next computer)"):
            st.session_state.last_result = "❌ Not found"
            st.session_state.pending_message = ""
            st.session_state.pending_kind = ""
            st.session_state.pending_asset = ""

st.divider()

# ---- Admin table editor ----
st.header("Edit Table (Admin)")
st.caption("Scanning never changes the table unless you press Confirm. Use this section only for corrections.")

df_show = load_df()

edited_df = st.data_editor(
    df_show,
    use_container_width=True,
    num_rows="dynamic",
    hide_index=True
)

if st.button("Save Table Changes 💾"):
    save_df(edited_df.fillna(""))
    st.success("Table saved.")