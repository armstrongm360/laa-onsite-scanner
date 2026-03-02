import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import hashlib

st.set_page_config(layout="wide")
st.title("LAA On-Site Chromebook Scanner")

# ---------------- AUTH (PIN) ----------------
def hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.encode("utf-8")).hexdigest()

def require_pin():
    if "authed" not in st.session_state:
        st.session_state.authed = False

    if st.session_state.authed:
        return

    st.subheader("Enter PIN")
    pin = st.text_input("PIN", type="password")

    if st.button("Login"):
        entered = hash_pin(pin.strip())
        expected = st.secrets["auth"]["pin_hash"].strip()
        if entered == expected:
            st.session_state.authed = True
            st.success("Logged in.")
            st.rerun()
        else:
            st.error("Wrong PIN.")

require_pin()
if not st.session_state.authed:
    st.stop()

# ---------------- GOOGLE SHEETS ----------------
SHEET_ID = st.secrets["sheet"]["id"]          # ✅ use ID now
WORKSHEET = st.secrets["sheet"]["worksheet"]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

creds = Credentials.from_service_account_info(
    st.secrets["gcp_service_account"],
    scopes=SCOPES
)
gc = gspread.authorize(creds)

# ✅ open by key (ID), not by name
ws = gc.open_by_key(SHEET_ID).worksheet(WORKSHEET)

# ---------------- STATE ----------------
for k, v in {
    "scan_input": "",
    "pending_asset": "",
    "pending_kind": "",
    "pending_message": "",
    "last_scanned": "",
    "last_result": "",
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

def load_df() -> pd.DataFrame:
    records = ws.get_all_records()
    df = pd.DataFrame(records).fillna("")
    # Ensure expected columns exist
    for col in ["AssetID", "Category", "Collected"]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].astype(str).str.strip()
    return df

def set_collected_yes(asset_id: str) -> bool:
    # Find exact match in column A (AssetID) and set Collected (col C) = YES
    asset_id = str(asset_id).strip()
    colA = ws.col_values(1)
    for i, val in enumerate(colA, start=1):
        if str(val).strip() == asset_id:
            ws.update_cell(i, 3, "YES")
            return True
    return False

def handle_scan_change():
    df = load_df()
    raw = st.session_state.scan_input.strip()
    if not raw:
        return

    st.session_state.last_scanned = raw

    if raw in df["AssetID"].astype(str).values:
        current = df.loc[df["AssetID"].astype(str) == raw, "Collected"].astype(str).values[0].strip().upper()
        st.session_state.pending_asset = raw

        if current == "YES":
            st.session_state.pending_kind = "success"
            st.session_state.pending_message = f"{raw} is already marked as COLLECTED."
        else:
            st.session_state.pending_kind = "warn"
            st.session_state.pending_message = f"{raw} found. Not yet collected — confirm to mark as collected."
    else:
        st.session_state.pending_asset = ""
        st.session_state.pending_kind = "error"
        st.session_state.pending_message = f"{raw} NOT FOUND in On-Site list."

    st.session_state.scan_input = ""  # safe in callback

# ---------------- UI ----------------
st.header("Scanner")

left, right = st.columns([2, 1], vertical_alignment="top")

with left:
    st.caption("Scan one computer at a time. The box clears automatically after each scan.")
    st.text_input("Scan AssetID", key="scan_input", on_change=handle_scan_change, placeholder="Scan now…")

with right:
    st.subheader("Last scan")
    st.write(f"**{st.session_state.last_scanned or '—'}**")
    if st.session_state.last_result:
        st.write(st.session_state.last_result)

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
                asset = st.session_state.pending_asset
                ok = set_collected_yes(asset)
                if ok:
                    st.session_state.last_result = "✅ Marked collected"
                    st.session_state.pending_message = ""
                    st.session_state.pending_kind = ""
                    st.session_state.pending_asset = ""
                    st.success("Saved. Ready for next computer.")
                else:
                    st.error("Could not find AssetID in column A of the Google Sheet.")
        with c2:
            if st.button("Cancel ❌"):
                st.session_state.last_result = "❌ Cancelled (no change)"
                st.session_state.pending_message = ""
                st.session_state.pending_kind = ""
                st.session_state.pending_asset = ""
                st.session_state.last_scanned = ""
                st.rerun()
    else:
        st.error(st.session_state.pending_message)
        if st.button("OK (next computer)"):
            st.session_state.last_result = "❌ Not found"
            st.session_state.pending_message = ""
            st.session_state.pending_kind = ""
            st.session_state.pending_asset = ""

st.divider()

with st.expander("Admin: View table"):
    sheet_url = st.secrets["sheet"].get(
        "url",
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
    )

    st.link_button("📄 Open Google Sheet", sheet_url)
    st.dataframe(load_df(), use_container_width=True)





