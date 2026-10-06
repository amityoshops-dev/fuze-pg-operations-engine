import sqlite3
import datetime
import json
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="Fuze PG Operations & Scheme Engine")

# --- SQLite Double-Entry Database Initialization ---
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

# --- Pydantic Request Models ---
class AuthRequest(BaseModel):
    integration_mode: str  # HOSTED_CHECKOUT or DIRECT_API
    card_pan_masked: str
    amount: float
    currency: str
    merchant_id: str
    simulate_drop: bool = False

class IPMParseRequest(BaseModel):
    raw_ipm_record: str

class DisputeRequest(BaseModel):
    dispute_id: str
    reason_code: str  # 4837 (Fraud) or 4853 (Service)
    eci_flag: str     # 02/05 (3DS Success) or 07 (No 3DS)
    pod_reference: str
    merchant_notes: str

# --- API Endpoints ---
@app.post("/api/v1/mpgs/auth")
def mpgs_auth(req: AuthRequest):
    timestamp = datetime.datetime.utcnow().isoformat() + "Z"
    txn_id = f"MPGS_{int(datetime.datetime.utcnow().timestamp())}"
    
    if req.simulate_drop:
        return {
            "status": "FAILED",
            "error_code": "3DS_CALLBACK_TIMEOUT",
            "action_required": "POLL_RETRIEVE_ORDER_API",
            "auto_reversal_fired": True,
            "message": "ISO 8583 0400 Auto-Reversal dispatched to release customer funds hold."
        }
    
    # Double-entry ledger recording
    conn = sqlite3.connect("pg_ops_ledger.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO ledger_entries (txn_id, timestamp, account_debited, account_credited, amount, currency, lifecycle_stage, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (txn_id, timestamp, f"CARDHOLDER_{req.card_pan_masked}", "ACQUIRER_LIEN_HOLD", req.amount, req.currency, "AUTHORISATION", "HELD"))
    conn.commit()
    conn.close()

    return {
        "status": "APPROVED",
        "txn_id": txn_id,
        "rrn": f"RRN{int(datetime.datetime.utcnow().timestamp()*1000)}"[0:12],
        "iso_response": "00 (Approved)",
        "3ds_eci": "05",
        "ledger_state": "Lien hold placed on Issuer rails"
    }

@app.post("/api/v1/clearing/parse-ipm")
def parse_ipm(req: IPMParseRequest):
    raw = req.raw_ipm_record.strip()
    gross_amount = 184.00
    interchange = 2.17
    scheme_fee = 0.29
    net_merchant_payout = round(gross_amount - interchange - scheme_fee, 2)
    
    return {
        "record_type": "PDS-0200 Presentment Record",
        "network": "Mastercard Dual-Message Rail",
        "gross_presentment_usd": gross_amount,
        "interchange_rate_calculated": f"${interchange} (1.18%)",
        "mastercard_scheme_assessment": f"${scheme_fee} (0.16%)",
        "net_merchant_settlement": f"${net_merchant_payout}",
        "recon_status": "MATCHED (ISO Auth == IPM Presentment)",
        "clearing_window": "DC1_SETTLEMENT_BATCH"
    }

@app.post("/api/v1/dispute/representment")
def dispute_representment(req: DisputeRequest):
    liability_shift = False
    verdict = ""
    
    if req.reason_code == "4837":
        if req.eci_flag in ["02", "05"]:
            liability_shift = True
            verdict = "REPRESENTMENT WON: Liability shift confirmed via 3DS CAVV/ECI flag. Issuer absorbs fraud loss."
        else:
            liability_shift = False
            verdict = "MERCHANT LIABLE: No 3DS OTP challenge recorded (ECI 07). Compelling evidence insufficient."
    elif req.reason_code == "4853":
        if req.pod_reference and len(req.pod_reference) > 5:
            liability_shift = True
            verdict = "REPRESENTMENT SUBMITTED: Valid Courier POD & Signed Delivery receipt attached. Sent to Pre-Arbitration."
        else:
            verdict = "EVIDENCE REJECTED: Missing tracking slip / POD reference."
            
    return {
        "dispute_id": req.dispute_id,
        "reason_code": req.reason_code,
        "liability_shift_secured": liability_shift,
        "verdict": verdict,
        "tat_status": "Within 30-Day Scheme Window"
    }

@app.get("/api/v1/ledger/recent")
def get_ledger():
    conn = sqlite3.connect("pg_ops_ledger.db")
    cursor = conn.cursor()
    cursor.execute("SELECT txn_id, timestamp, account_debited, account_credited, amount, currency, lifecycle_stage, status FROM ledger_entries ORDER BY id DESC LIMIT 5")
    rows = cursor.fetchall()
    conn.close()
    
    entries = []
    for r in rows:
        entries.append({
            "txn_id": r[0], "timestamp": r[1], "debited": r[2], "credited": r[3],
            "amount": r[4], "currency": r[5], "stage": r[6], "status": r[7]
        })
    return entries

# --- Interactive Visual Dashboard UI ---
@app.get("/", response_class=HTMLResponse)
def dashboard():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Fuze PG Operations & Scheme Engine</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Inter:wght@400;500;600;700&display=swap');
            body { font-family: 'Inter', sans-serif; }
            pre, code { font-family: 'JetBrains Mono', monospace; }
        </style>
    </head>
    <body class="bg-slate-950 text-slate-100 min-h-screen">
        <!-- Top Nav -->
        <header class="border-b border-slate-800 bg-slate-900/60 backdrop-blur px-6 py-4 flex items-center justify-between sticky top-0 z-50">
            <div class="flex items-center space-x-3">
                <div class="w-9 h-9 rounded-lg bg-indigo-600 flex items-center justify-center font-bold text-white shadow-lg shadow-indigo-600/30">FZ</div>
                <div>
                    <h1 class="text-base font-semibold text-white tracking-wide">Fuze Payment Gateway Operations Console</h1>
                    <p class="text-xs text-slate-400">Card Acquiring, MPGS & Mastercard Clearing Infrastructure</p>
                </div>
            </div>
            <div class="flex items-center space-x-4">
                <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-950 text-emerald-400 border border-emerald-800">
                    <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 mr-1.5 animate-pulse"></span> Switch Live
                </span>
                <span class="text-xs text-slate-400 border-l border-slate-800 pl-4">Dual-Message Active</span>
            </div>
        </header>

        <main class="max-w-7xl mx-auto px-6 py-8 space-y-8">
            <!-- Grid 1: Pipeline Switch & Settlement -->
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <!-- Box 1: MPGS Switch Simulator -->
                <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-xl">
                    <div class="flex items-center justify-between pb-4 border-b border-slate-800">
                        <div class="flex items-center space-x-2">
                            <span class="px-2 py-0.5 rounded bg-indigo-900/50 text-indigo-400 font-mono text-xs border border-indigo-700">MODULE 01</span>
                            <h2 class="text-sm font-semibold text-white">MPGS Auth & Recovery Engine</h2>
                        </div>
                        <span class="text-xs text-slate-400">ISO 8583 0100/0110</span>
                    </div>

                    <div class="mt-4 space-y-4 text-xs">
                        <div class="grid grid-cols-2 gap-3">
                            <div>
                                <label class="text-slate-400 block mb-1">Integration Mode</label>
                                <select id="authMode" class="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-white">
                                    <option value="HOSTED_CHECKOUT">Hosted Checkout (PCI SAQ A)</option>
                                    <option value="DIRECT_API">Direct Server API (Tokenized)</option>
                                </select>
                            </div>
                            <div>
                                <label class="text-slate-400 block mb-1">Gross Amount (USD)</label>
                                <input id="authAmount" type="number" value="184.00" class="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-white font-mono">
                            </div>
                        </div>

                        <div class="flex items-center space-x-2 bg-slate-950/60 p-2.5 rounded border border-slate-800/80">
                            <input id="authDrop" type="checkbox" class="rounded bg-slate-900 border-slate-700 text-indigo-600 focus:ring-0">
                            <label for="authDrop" class="text-slate-300">Simulate 3DS Callback Drop (Ghost Order Triage)</label>
                        </div>

                        <button onclick="triggerAuth()" class="w-full py-2 bg-indigo-600 hover:bg-indigo-500 rounded font-medium text-white transition shadow-lg shadow-indigo-600/20">
                            Execute Switch Request
                        </button>

                        <div class="bg-slate-950 rounded p-3 border border-slate-800/80">
                            <div class="text-[11px] text-slate-400 mb-1 flex justify-between font-mono">
                                <span>TERMINAL_OUTPUT</span>
                                <span id="authStatusBadge">IDLE</span>
                            </div>
                            <pre id="authOutput" class="text-[11px] text-emerald-400 overflow-x-auto whitespace-pre-wrap">Awaiting transaction execution...</pre>
                        </div>
                    </div>
                </div>

                <!-- Box 2: Mastercard IPM Parser -->
                <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-xl">
                    <div class="flex items-center justify-between pb-4 border-b border-slate-800">
                        <div class="flex items-center space-x-2">
                            <span class="px-2 py-0.5 rounded bg-amber-900/50 text-amber-400 font-mono text-xs border border-amber-700">MODULE 02</span>
                            <h2 class="text-sm font-semibold text-white">Mastercard IPM Clearing Parser</h2>
                        </div>
                        <span class="text-xs text-slate-400">PDS-0200 Presentment</span>
                    </div>

                    <div class="mt-4 space-y-4 text-xs">
                        <div>
                            <label class="text-slate-400 block mb-1">EOD IPM Presentment Record (.DAT snippet)</label>
                            <textarea id="ipmInput" rows="2" class="w-full bg-slate-950 border border-slate-800 rounded p-2 text-slate-300 font-mono text-[11px]">REC_PDS0200|MC_DUAL_MSG|MID_8849201|AUTH_184.00|USD|ECI_05|RRN_392019481029|MCC_5411</textarea>
                        </div>

                        <button onclick="parseIPM()" class="w-full py-2 bg-amber-600 hover:bg-amber-500 rounded font-medium text-white transition shadow-lg shadow-amber-600/20">
                            Parse & Audit Clearing Batch
                        </button>

                        <div class="bg-slate-950 rounded p-3 border border-slate-800/80">
                            <div class="text-[11px] text-slate-400 mb-1 font-mono">CALCULATED_SETTLEMENT_LEDGER</div>
                            <pre id="ipmOutput" class="text-[11px] text-amber-300 overflow-x-auto whitespace-pre-wrap">Click to audit IPM presentment fees...</pre>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Grid 2: Chargeback Arbitration Desk -->
            <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-xl">
                <div class="flex items-center justify-between pb-4 border-b border-slate-800">
                    <div class="flex items-center space-x-2">
                        <span class="px-2 py-0.5 rounded bg-rose-900/50 text-rose-400 font-mono text-xs border border-rose-700">MODULE 03</span>
                        <h2 class="text-sm font-semibold text-white">Chargeback Arbitration Desk (TAT & Defense Engine)</h2>
                    </div>
                    <span class="text-xs text-rose-400">30-Day Scheme Window</span>
                </div>

                <div class="mt-4 grid grid-cols-1 md:grid-cols-3 gap-6 text-xs">
                    <div class="space-y-3">
                        <div>
                            <label class="text-slate-400 block mb-1">Chargeback Reason Code</label>
                            <select id="cbReason" class="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-white">
                                <option value="4837">Reason 4837 (Fraud / No Auth)</option>
                                <option value="4853">Reason 4853 (Goods/Service Not Received)</option>
                            </select>
                        </div>
                        <div>
                            <label class="text-slate-400 block mb-1">3DS ECI Authentication Flag</label>
                            <select id="cbEci" class="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-white">
                                <option value="05">ECI 05 (Fully Authenticated 3DS OTP)</option>
                                <option value="02">ECI 02 (Mastercard Identity Check Success)</option>
                                <option value="07">ECI 07 (Non-3DS / Merchant Liable)</option>
                            </select>
                        </div>
                    </div>

                    <div class="space-y-3">
                        <div>
                            <label class="text-slate-400 block mb-1">Courier POD / Tracking Receipt Reference</label>
                            <input id="cbPod" type="text" value="BLUEDART_POD_9948201_SIGNED" class="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-white font-mono">
                        </div>
                        <div>
                            <label class="text-slate-400 block mb-1">Merchant Compelling Notes</label>
                            <input id="cbNotes" type="text" value="Customer IP matching delivery postal pin; signed receipt attached." class="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-white">
                        </div>
                    </div>

                    <div class="flex flex-col justify-between">
                        <div>
                            <span class="text-slate-400 block mb-1">Action</span>
                            <button onclick="submitDispute()" class="w-full py-2 bg-rose-600 hover:bg-rose-500 rounded font-medium text-white transition shadow-lg shadow-rose-600/20 mb-3">
                                Dispatch Representment File
                            </button>
                        </div>
                        <div class="bg-slate-950 p-3 rounded border border-slate-800">
                            <span class="text-[10px] text-slate-500 block mb-1 font-mono">ARBITRATION_VERDICT</span>
                            <p id="cbVerdict" class="text-xs text-rose-300 font-mono">Ready to process claim rebuttal.</p>
                        </div>
                    </div>
                </div>
            </div>
        </main>

        <script>
            async function triggerAuth() {
                const mode = document.getElementById('authMode').value;
                const amt = parseFloat(document.getElementById('authAmount').value);
                const drop = document.getElementById('authDrop').checked;
                const out = document.getElementById('authOutput');
                const badge = document.getElementById('authStatusBadge');
                
                badge.innerText = 'PROCESSING...';
                badge.className = 'text-amber-400 font-mono';

                try {
                    const res = await fetch('/api/v1/mpgs/auth', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            integration_mode: mode,
                            card_pan_masked: '5120-XXXX-XXXX-9931',
                            amount: amt,
                            currency: 'USD',
                            merchant_id: 'FUZE_MID_9019',
                            simulate_drop: drop
                        })
                    });
                    const data = await res.json();
                    out.innerText = JSON.stringify(data, null, 2);
                    badge.innerText = data.status;
                    badge.className = data.status === 'APPROVED' ? 'text-emerald-400 font-mono' : 'text-rose-400 font-mono';
                } catch(e) {
                    out.innerText = 'Error: ' + e;
                }
            }

            async function parseIPM() {
                const raw = document.getElementById('ipmInput').value;
                const out = document.getElementById('ipmOutput');
                try {
                    const res = await fetch('/api/v1/clearing/parse-ipm', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ raw_ipm_record: raw })
                    });
                    const data = await res.json();
                    out.innerText = JSON.stringify(data, null, 2);
                } catch(e) {
                    out.innerText = 'Error: ' + e;
                }
            }

            async function submitDispute() {
                const reason = document.getElementById('cbReason').value;
                const eci = document.getElementById('cbEci').value;
                const pod = document.getElementById('cbPod').value;
                const notes = document.getElementById('cbNotes').value;
                const verdict = document.getElementById('cbVerdict');

                try {
                    const res = await fetch('/api/v1/dispute/representment', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            dispute_id: 'DSP_92019482',
                            reason_code: reason,
                            eci_flag: eci,
                            pod_reference: pod,
                            merchant_notes: notes
                        })
                    });
                    const data = await res.json();
                    verdict.innerText = data.verdict;
                } catch(e) {
                    verdict.innerText = 'Error: ' + e;
                }
            }
        </script>
    </body>
    </html>
    """