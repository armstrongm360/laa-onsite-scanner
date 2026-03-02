import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import hashlib
from datetime import datetime, timezone
import re

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
SHEET_ID = st.secrets["sheet"]["id"]
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
ws = gc.open_by_key(SHEET_ID).worksheet(WORKSHEET)

# ---------------- HELPERS ----------------
RE_NUMERIC = re.compile(r"^\d+$")

def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def get_header_map() -> dict[str, int]:
    """Return mapping header -> 1-based column index."""
    headers = ws.row_values(1)
    # Normalize headers exactly as they appear
    return {h.strip(): i + 1 for i, h in enumerate(headers) if h.strip()}

REQUIRED_COLS = ["AssetID", "Category", "Collected", "CheckedOutTo", "CheckedOutAt", "CheckedInAt", "LastAction"]

def validate_gc_id(s: str) -> bool:
    s = s.strip()
    return bool(RE_NUMERIC.match(s)) and (5 <= len(s) <= 10)

def find_asset_row(asset_id: str) -> int | None:
    """Find row number by exact match in AssetID column."""
    asset_id = str(asset_id).strip()
    col_map = get_header_map()
    if "AssetID" not in col_map:
        return None
    asset_col = col_map["AssetID"]
    col_vals = ws.col_values(asset_col)
    for r, val in enumerate(col_vals, start=1):
        if str(val).strip() == asset_id:
            return r
    return None

def load_df() -> pd.DataFrame:
    records = ws.get_all_records()
    df = pd.DataFrame(records).fillna("")
    for col in REQUIRED_COLS:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].astype(str).str.strip()
    return df

def ensure_columns_exist_or_warn():
    col_map = get_header_map()
    missing = [c for c in REQUIRED_COLS if c not in col_map]
    if missing:
        st.error(
            "Your Google Sheet is missing required columns: "
            + ", ".join(missing)
            + "\n\nFix the header row (row 1) on the 'assets' tab to include:\n"
            + "AssetID | Category | Collected | CheckedOutTo | CheckedOutAt | CheckedInAt | LastAction"
        )
        st.stop()

def update_cells(row: int, updates: dict[str, str]) -> None:
    """Update multiple columns in the same row by header name."""
    col_map = get_header_map()
    for header, value in updates.items():
        if header not in col_map:
            raise KeyError(f"Missing column: {header}")
        ws.update_cell(row, col_map[header], value)

# ---------------- SESSION STATE ----------------
defaults = {
    "mode": "Check-out (Student takes device)",
    "scan_input": "",
    "step": "await_gc",         # await_gc, await_asset (checkout mode)
    "gc_pending": "",
    "asset_pending": "",
    "pending_kind": "",
    "pending_message": "",
    "last_scanned": "",
    "last_result": "",
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

def reset_checkout_flow():
    st.session_state.step = "await_gc"
    st.session_state.gc_pending = ""
    st.session_state.asset_pending = ""
    st.session_state.pending_kind = ""
    st.session_state.pending_message = ""
    st.session_state.last_scanned = ""
    # do not wipe last_result (useful feedback)



# ---------------- UI: MODE ----------------
ensure_columns_exist_or_warn()

# Track previous mode so we can reset state when it changes
if "prev_mode" not in st.session_state:
    st.session_state.prev_mode = "Check-out (Student takes device)"

st.radio(
    "Mode",
    ["Check-out (Student takes device)", "Check-in (Return device)"],
    key="mode",
    horizontal=True,
)

# If mode changed, reset flow (NO st.rerun needed)
if st.session_state.mode != st.session_state.prev_mode:
    reset_checkout_flow()
    st.session_state.prev_mode = st.session_state.mode

st.header("Scanner")
left, right = st.columns([2, 1], vertical_alignment="top")

with right:
    st.subheader("Status")
    st.write(f"**Last scan:** {st.session_state.last_scanned or '—'}")
    if st.session_state.last_result:
        st.info(st.session_state.last_result)

# ---------------- SCAN HANDLER (STATE MACHINE) ----------------
def handle_scan_change():
    raw = st.session_state.scan_input.strip()
    if not raw:
        return

    st.session_state.last_scanned = raw
    df = load_df()

    # ---------- CHECK-IN MODE: asset only ----------
    if st.session_state.mode.startswith("Check-in"):
        # treat scan as AssetID
        asset_id = raw
        if asset_id not in df["AssetID"].astype(str).values:
            st.session_state.pending_kind = "error"
            st.session_state.pending_message = f"{asset_id} NOT FOUND in On-Site list."
            st.session_state.scan_input = ""
            return

        row = df.loc[df["AssetID"].astype(str) == asset_id].iloc[0]
        checked_out_to = str(row.get("CheckedOutTo", "")).strip()

        st.session_state.asset_pending = asset_id
        if checked_out_to:
            st.session_state.pending_kind = "warn_in"
            st.session_state.pending_message = f"{asset_id} is checked out to GC {checked_out_to}. Mark as returned?"
        else:
            st.session_state.pending_kind = "warn_in"
            st.session_state.pending_message = f"{asset_id} is not currently checked out. Mark as collected anyway?"
        st.session_state.scan_input = ""
        return

    # ---------- CHECK-OUT MODE: GC then asset ----------
    if st.session_state.step == "await_gc":
        # treat scan as GC ID
        if not validate_gc_id(raw):
            st.session_state.pending_kind = "error"
            st.session_state.pending_message = f"{raw} is not a valid GC ID (must be 5–10 digits)."
            st.session_state.scan_input = ""
            return

        st.session_state.gc_pending = raw
        st.session_state.step = "await_asset"
        st.session_state.pending_kind = "info"
        st.session_state.pending_message = f"GC {raw} captured. Now scan the DEVICE AssetID."
        st.session_state.scan_input = ""
        return

    # step == await_asset
    asset_id = raw
    if asset_id not in df["AssetID"].astype(str).values:
        st.session_state.pending_kind = "error"
        st.session_state.pending_message = f"{asset_id} NOT FOUND in On-Site list. (Checkout cancelled — rescan GC ID.)"
        reset_checkout_flow()
        return

    row = df.loc[df["AssetID"].astype(str) == asset_id].iloc[0]
    checked_out_to = str(row.get("CheckedOutTo", "")).strip()

    st.session_state.asset_pending = asset_id

    if checked_out_to:
        # already out
        st.session_state.pending_kind = "error"
        st.session_state.pending_message = f"{asset_id} is already checked out to GC {checked_out_to}. (Checkout cancelled — rescan GC ID.)"
        reset_checkout_flow()
        return

    gc_id = st.session_state.gc_pending
    st.session_state.pending_kind = "warn_out"
    st.session_state.pending_message = f"Assign device {asset_id} to GC {gc_id}?"
    st.session_state.scan_input = ""

# ---------------- SCANNER INPUT + PROMPT ----------------
with left:
    if st.session_state.mode.startswith("Check-out"):
        prompt = "Scan GC ID" if st.session_state.step == "await_gc" else "Scan DEVICE AssetID"
    else:
        prompt = "Scan DEVICE AssetID"

    st.caption(f"Next step: **{prompt}**. The box clears automatically after each scan.")
    st.text_input(prompt, key="scan_input", on_change=handle_scan_change, placeholder="Scan now…")

# ---------------- ACTION PANELS ----------------
if st.session_state.pending_message:
    kind = st.session_state.pending_kind

    if kind == "info":
        st.info(st.session_state.pending_message)
        if st.button("OK"):
            st.session_state.pending_message = ""
            st.session_state.pending_kind = ""
            st.session_state.last_scanned = ""
            

    elif kind == "warn_out":
        st.warning(st.session_state.pending_message)
        c1, c2 = st.columns(2)

        with c1:
            if st.button("Confirm Check-out ✅"):
                asset_id = st.session_state.asset_pending
                gc_id = st.session_state.gc_pending
                row_num = find_asset_row(asset_id)
                if row_num is None:
                    st.error("Could not locate this AssetID row in the sheet.")
                else:
                    ts = now_utc_iso()
                    update_cells(row_num, {
                        "Collected": "NO",
                        "CheckedOutTo": gc_id,
                        "CheckedOutAt": ts,
                        "LastAction": "OUT",
                    })
                    st.session_state.last_result = f"✅ Checked OUT {asset_id} to GC {gc_id}"
                    reset_checkout_flow()
                    

        with c2:
            if st.button("Cancel ❌"):
                st.session_state.last_result = "❌ Cancelled (no change)"
                reset_checkout_flow()
                

    elif kind == "warn_in":
        st.warning(st.session_state.pending_message)
        c1, c2 = st.columns(2)

        with c1:
            if st.button("Confirm Check-in ✅"):
                asset_id = st.session_state.asset_pending
                row_num = find_asset_row(asset_id)
                if row_num is None:
                    st.error("Could not locate this AssetID row in the sheet.")
                else:
                    ts = now_utc_iso()
                    update_cells(row_num, {
                        "Collected": "YES",
                        "CheckedOutTo": "",
                        "CheckedInAt": ts,
                        "LastAction": "IN",
                    })
                    st.session_state.last_result = f"✅ Checked IN {asset_id}"
                    st.session_state.pending_message = ""
                    st.session_state.pending_kind = ""
                    st.session_state.asset_pending = ""
                    st.session_state.last_scanned = ""
                    

        with c2:
            if st.button("Cancel ❌"):
                st.session_state.last_result = "❌ Cancelled (no change)"
                st.session_state.pending_message = ""
                st.session_state.pending_kind = ""
                st.session_state.asset_pending = ""
                st.session_state.last_scanned = ""
                

    else:
        # error
        st.error(st.session_state.pending_message)
        if st.button("OK (next)"):
            st.session_state.last_result = "❌ Not processed"
            st.session_state.pending_message = ""
            st.session_state.pending_kind = ""
            st.session_state.asset_pending = ""
            st.session_state.last_scanned = ""
            # If we were mid-checkout, reset to avoid confusion
            if st.session_state.mode.startswith("Check-out"):
                reset_checkout_flow()
            

st.divider()

with st.expander("Admin: View table"):
    sheet_url = st.secrets["sheet"].get(
        "url",
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
    )
    st.link_button("📄 Open Google Sheet", sheet_url)
    st.dataframe(load_df(), use_container_width=True)





