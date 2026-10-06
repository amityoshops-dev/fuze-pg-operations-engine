import sqlite3
import datetime
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="Fuze Payment Gateway Operations Console")

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

# --- APIs ---
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

# --- Live UI ---
@app.get("/", response_class=HTMLResponse)
def index():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Fuze Payment Gateway Operations Console</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
        <style>
            body { font-family: 'Plus Jakarta Sans', sans-serif; }
            code, pre, .font-mono { font-family: 'JetBrains Mono', monospace; }
            .glow-emerald { box-shadow: 0 0 25px -5px rgba(16, 185, 129, 0.3); }
            .glow-indigo { box-shadow: 0 0 25px -5px rgba(99, 102, 241, 0.3); }
        </style>
    </head>
    <body class="bg-[#0B0F17] text-slate-100 min-h-screen antialiased flex flex-col">

        <!-- Top Header -->
        <header class="border-b border-slate-800/80 bg-[#0F172A]/80 backdrop-blur-md px-6 py-3.5 sticky top-0 z-50 flex items-center justify-between">
            <div class="flex items-center gap-4">
                <div class="h-9 w-9 rounded-xl bg-gradient-to-tr from-indigo-600 to-violet-500 flex items-center justify-center font-bold text-white shadow-lg shadow-indigo-500/25">
                    FZ
                </div>
                <div>
                    <div class="flex items-center gap-2">
                        <span class="text-sm font-semibold tracking-wide text-white">Fuze PG Operations & Scheme Engine</span>
                        <span class="text-[10px] px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 font-medium">Enterprise Core</span>
                    </div>
                    <p class="text-xs text-slate-400">Card Acquiring, MPGS Switching & Mastercard Clearing Rails</p>
                </div>
            </div>
            
            <div class="flex items-center gap-3">
                <div class="flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-medium">
                    <span class="h-2 w-2 rounded-full bg-emerald-400 animate-ping"></span>
                    Production Rails Live
                </div>
            </div>
        </header>

        <!-- Main Body -->
        <main class="flex-1 max-w-7xl w-full mx-auto px-6 py-6 space-y-6">

            <!-- Interactive Visual Pipeline Tracker -->
            <div class="bg-gradient-to-b from-[#111827] to-[#0D131F] border border-slate-800 rounded-2xl p-6 shadow-xl relative overflow-hidden">
                <div class="flex items-center justify-between mb-4">
                    <div class="flex items-center gap-2">
                        <span class="text-xs font-semibold uppercase tracking-wider text-indigo-400">Live Dual-Message Switch Topology</span>
                    </div>
                    <div id="topologyStatus" class="text-xs font-mono text-slate-400">STATUS: IDLE</div>
                </div>

                <div class="grid grid-cols-5 gap-3 relative z-10">
                    <!-- Node 1 -->
                    <div id="node-client" class="bg-slate-900/90 border border-slate-800 rounded-xl p-3.5 text-center transition-all duration-300">
                        <div class="text-[10px] text-slate-400 font-mono mb-1">ORIGIN</div>
                        <div class="text-xs font-bold text-slate-200">Customer App</div>
                        <div class="text-[10px] text-slate-500 mt-0.5">3DS2 SDK / Web</div>
                    </div>
                    <!-- Node 2 -->
                    <div id="node-mpgs" class="bg-slate-900/90 border border-slate-800 rounded-xl p-3.5 text-center transition-all duration-300">
                        <div class="text-[10px] text-indigo-400 font-mono mb-1">GATEWAY</div>
                        <div class="text-xs font-bold text-white">MPGS Switch</div>
                        <div class="text-[10px] text-slate-400 mt-0.5">Token / Risk Check</div>
                    </div>
                    <!-- Node 3 -->
                    <div id="node-acquirer" class="bg-slate-900/90 border border-slate-800 rounded-xl p-3.5 text-center transition-all duration-300">
                        <div class="text-[10px] text-slate-400 font-mono mb-1">ACQUIRER</div>
                        <div class="text-xs font-bold text-slate-200">Acquirer Bank</div>
                        <div class="text-[10px] text-slate-500 mt-0.5">MID / TID Host</div>
                    </div>
                    <!-- Node 4 -->
                    <div id="node-scheme" class="bg-slate-900/90 border border-slate-800 rounded-xl p-3.5 text-center transition-all duration-300">
                        <div class="text-[10px] text-amber-400 font-mono mb-1">SCHEME</div>
                        <div class="text-xs font-bold text-white">Mastercard Rail</div>
                        <div class="text-[10px] text-slate-400 mt-0.5">Dual-Message ISO</div>
                    </div>
                    <!-- Node 5 -->
                    <div id="node-issuer" class="bg-slate-900/90 border border-slate-800 rounded-xl p-3.5 text-center transition-all duration-300">
                        <div class="text-[10px] text-slate-400 font-mono mb-1">ISSUER</div>
                        <div class="text-xs font-bold text-slate-200">Issuer Bank</div>
                        <div class="text-[10px] text-slate-500 mt-0.5">Auth / Lien Hold</div>
                    </div>
                </div>
            </div>

            <!-- Tabbed Operation Workbench -->
            <div class="bg-[#111827] border border-slate-800 rounded-2xl shadow-xl overflow-hidden">
                <!-- Nav Tabs -->
                <div class="flex border-b border-slate-800 bg-slate-950/60 px-6 pt-3 gap-6 text-xs font-medium">
                    <button onclick="switchTab('auth')" id="tab-btn-auth" class="pb-3 text-indigo-400 border-b-2 border-indigo-500 font-semibold transition">
                        1. MPGS Authorization Switch
                    </button>
                    <button onclick="switchTab('clearing')" id="tab-btn-clearing" class="pb-3 text-slate-400 hover:text-slate-200 transition">
                        2. Mastercard IPM Clearing Parser
                    </button>
                    <button onclick="switchTab('dispute')" id="tab-btn-dispute" class="pb-3 text-slate-400 hover:text-slate-200 transition">
                        3. Chargeback Arbitration Desk
                    </button>
                </div>

                <!-- Tab 1: MPGS Switch -->
                <div id="tab-auth" class="p-6">
                    <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
                        <div class="space-y-4">
                            <h3 class="text-sm font-semibold text-white">Trigger Switch Authorisation</h3>
                            <p class="text-xs text-slate-400">Simulate incoming customer payment payloads and 3DS failure triage.</p>
                            
                            <div class="space-y-3">
                                <div>
                                    <label class="block text-xs font-medium text-slate-400 mb-1">Integration Flow</label>
                                    <select id="authMode" class="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500">
                                        <option value="HOSTED_CHECKOUT">Hosted Checkout Session (PCI SAQ A)</option>
                                        <option value="DIRECT_API">Direct Server API (Network Tokenized)</option>
                                    </select>
                                </div>
                                <div class="grid grid-cols-2 gap-3">
                                    <div>
                                        <label class="block text-xs font-medium text-slate-400 mb-1">Amount (USD)</label>
                                        <input type="number" id="authAmt" value="184.00" class="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-200 font-mono">
                                    </div>
                                    <div>
                                        <label class="block text-xs font-medium text-slate-400 mb-1">Masked Card</label>
                                        <input type="text" id="authCard" value="5120-XXXX-XXXX-9931" class="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-200 font-mono" readonly>
                                    </div>
                                </div>

                                <div class="p-3 bg-slate-900/60 border border-slate-800 rounded-xl flex items-center justify-between">
                                    <div>
                                        <div class="text-xs font-medium text-slate-200">Simulate 3DS Drop</div>
                                        <div class="text-[11px] text-slate-500">Injects ISO 8583 0400 auto-reversal</div>
                                    </div>
                                    <input type="checkbox" id="authSimDrop" class="h-4 w-4 rounded bg-slate-950 border-slate-700 text-indigo-600 focus:ring-0">
                                </div>

                                <button onclick="runAuth()" class="w-full py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-xs shadow-lg shadow-indigo-600/25 transition">
                                    Execute Authorisation Request
                                </button>
                            </div>
                        </div>

                        <!-- Switch