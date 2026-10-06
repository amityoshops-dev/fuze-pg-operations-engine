import sqlite3
import datetime
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

app = FastAPI(title="Fuze Payment Gateway Operations Console")
templates = Jinja2Templates(directory="templates")

# --- SQLite Database Initialization ---
def init_db():
    conn = sqlite3.connect("pg_ops_ledger.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ledger_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            txn_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            account_debited TEXT NOT NULL,
            account_credited TEXT NOT NULL,
            amount REAL NOT NULL,
            currency TEXT NOT NULL,
            lifecycle_stage TEXT NOT NULL,
            status TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()

# --- Models ---
class AuthRequest(BaseModel):
    integration_mode: str
    card_pan_masked: str
    amount: float
    currency: str
    merchant_id: str
    simulate_drop: bool = False

class IPMParseRequest(BaseModel):
    raw_ipm_record: str

class DisputeRequest(BaseModel):
    dispute_id: str
    reason_code: str
    eci_flag: str
    pod_reference: str
    merchant_notes: str

# --- Endpoints ---
@app.get("/")
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/v1/mpgs/auth")
def mpgs_auth(req: AuthRequest):
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    txn_id = f"TXN_{int(datetime.datetime.utcnow().timestamp())}"
    
    if req.simulate_drop:
        return {
            "status": "FAILED",
            "error_code": "3DS_TIMEOUT",
            "iso_response": "91 (System Error / Timeout)",
            "action": "AUTO_REVERSAL_0400",
            "message": "3DS Callback dropped. Fired ISO 8583 0400 auto-reversal to release cardholder hold.",
            "pipeline_nodes": ["client", "mpgs"]
        }
    
    conn = sqlite3.connect("pg_ops_ledger.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO ledger_entries (txn_id, timestamp, account_debited, account_credited, amount, currency, lifecycle_stage, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (txn_id, timestamp, f"CARD_{req.card_pan_masked[-4:]}", "ACQUIRER_LIEN", req.amount, req.currency, "AUTHORISATION", "HELD"))
    conn.commit()
    conn.close()

    return {
        "status": "APPROVED",
        "txn_id": txn_id,
        "rrn": f"RRN{int(datetime.datetime.utcnow().timestamp()*1000)}"[0:12],
        "iso_response": "00 (Approved)",
        "3ds_eci": "05 (Liability Shift Confirmed)",
        "message": "Funds authorized and held on Issuer rail.",
        "pipeline_nodes": ["client", "mpgs", "acquirer", "scheme", "issuer"]
    }

@app.post("/api/v1/clearing/parse-ipm")
def parse_ipm(req: IPMParseRequest):
    gross = 184.00
    interchange = 2.17
    scheme_fee = 0.29
    net_payout = round(gross - interchange - scheme_fee, 2)
    
    return {
        "record_type": "PDS-0200 Presentment Record",
        "gross_amount": f"${gross:.2f}",
        "interchange": f"${interchange:.2f} (1.18%)",
        "scheme_fee": f"${scheme_fee:.2f} (0.16%)",
        "net_payout": f"${net_payout:.2f}",
        "recon_status": "MATCHED",
        "clearing_cycle": "Mastercard Dual-Message EOD Batch"
    }

@app.post("/api/v1/dispute/representment")
def dispute_representment(req: DisputeRequest):
    if req.reason_code == "4837":
        if req.eci_flag in ["02", "05"]:
            return {
                "outcome": "LIABILITY SHIFT WON",
                "badge": "bg-emerald-500/20 text-emerald-400 border-emerald-500/40",
                "details": "Liability shift validated via 3DS CAVV/ECI signature. Issuer absorbs fraud loss under Mastercard Scheme rules."
            }
        else:
            return {
                "outcome": "MERCHANT LIABLE",
                "badge": "bg-rose-500/20 text-rose-400 border-rose-500/40",
                "details": "Non-3DS transaction (ECI 07). Merchant absorbs chargeback fee and transaction debit."
            }
    else:
        if req.pod_reference and len(req.pod_reference) > 5:
            return {
                "outcome": "REPRESENTMENT DISPATCHED",
                "badge": "bg-sky-500/20 text-sky-400 border-sky-500/40",
                "details": "Courier POD and tracking documentation attached. File escalated to Pre-Arbitration stage."
            }
        else:
            return {
                "outcome": "REPRESENTMENT REJECTED",
                "badge": "bg-amber-500/20 text-amber-400 border-amber-500/40",
                "details": "Missing valid courier delivery reference. Proof rejected."
            }

@app.get("/api/v1/ledger/recent")
def get_ledger():
    conn = sqlite3.connect("pg_ops_ledger.db")
    cursor = conn.cursor()
    cursor.execute("SELECT txn_id, timestamp, account_debited, account_credited, amount, currency, lifecycle_stage, status FROM ledger_entries ORDER BY id DESC LIMIT 5")
    rows = cursor.fetchall()
    conn.close()
    return [{"txn_id": r[0], "timestamp": r[1], "debited": r[2], "credited": r[3], "amount": r[4], "currency": r[5], "stage": r[6], "status": r[7]} for r in rows]
