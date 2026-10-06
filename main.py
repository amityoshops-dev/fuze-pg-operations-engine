import os
import hmac
import hashlib
import sqlite3
import datetime
import json
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

app = FastAPI(
    title="Fuze Payments Gateway Operations & Scheme Engine",
    description="Neumorphic Gateway Switch, Digital Wallets, Hosted Tokenization v0.3, Mastercard IPM Clearing & Scheme Arbitration",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

DB_PATH = "fuze_gateway_ledger.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference_number INTEGER UNIQUE,
            timestamp TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_token TEXT,
            amount REAL NOT NULL,
            surcharge REAL DEFAULT 0.0,
            card_last4 TEXT,
            auth_code TEXT,
            status TEXT NOT NULL,
            eci TEXT,
            cavv TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ledger_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_no INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            debit_account TEXT NOT NULL,
            credit_account TEXT NOT NULL,
            amount REAL NOT NULL,
            description TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()

# --- Request Models ---
class ThreeDSecurePayload(BaseModel):
    eci: Optional[str] = "05"
    cavv: Optional[str] = "AAABBIIFmQAAAAAJUGFmAAAAAAA="

class ChargeRequest(BaseModel):
    amount: float
    source: Optional[str] = "nonce-HT_9920194820194"
    bin_type: Optional[str] = "C"
    three_d_secure: Optional[ThreeDSecurePayload] = Field(default=None, alias="3d_secure")
    simulate_failure: Optional[bool] = False

class DisputeRebuttalRequest(BaseModel):
    dispute_id: str
    reference_number: int
    reason_code: str
    eci_flag: str
    pod_tracking_number: str

# --- Endpoints ---
@app.post("/api/v2/transactions/charge")
def charge_transaction(req: ChargeRequest):
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    ref_no = int(datetime.datetime.utcnow().timestamp() * 1000) % 1000000000
    auth_code = f"AUTH{ref_no % 1000000:06d}"

    if req.simulate_failure:
        return {
            "status": "Declined",
            "status_code": "D",
            "error_code": "3DS_CHALLENGE_TIMEOUT",
            "error_message": "3D Secure 2.0 Challenge session expired. ISO 8583 0400 auto-reversal dispatched.",
            "auth_amount": 0,
            "reference_number": ref_no,
            "active_node_index": 2
        }

    surcharge = round(req.amount * 0.0215, 2) if req.bin_type == "C" else 0.0
    final_amount = req.amount + surcharge

    src_label = "Hosted Token (v0.3)"
    last4 = "6668"
    if req.source == "googlepay":
        src_label = "Google Pay (Cryptogram_3DS)"
        last4 = "4111"
    elif req.source == "applepay":
        src_label = "Apple Pay (TSYS Encrypted)"
        last4 = "8892"

    eci = req.three_d_secure.eci if req.three_d_secure else "05"
    cavv = req.three_d_secure.cavv if req.three_d_secure else "AAABBIIFmQAAAAAJUGFmAAAAAAA="

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO transactions (reference_number, timestamp, source_type, source_token, amount, surcharge, card_last4, auth_code, status, eci, cavv)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (ref_no, timestamp, src_label, req.source, final_amount, surcharge, last4, auth_code, "Captured", eci, cavv))

    cur.execute("""
        INSERT INTO ledger_journal (ref_no, timestamp, debit_account, credit_account, amount, description)
        VALUES (?, ?, 'CARDHOLDER_ISSUER_HOLD', 'FUZE_ACQUIRER_SETTLEMENT_POOL', ?, ?)
    """, (ref_no, timestamp, final_amount, f"Auth & Capture via {src_label}"))
    conn.commit()
    conn.close()

    return {
        "status": "Approved",
        "status_code": "A",
        "auth_amount": final_amount,
        "base_amount": req.amount,
        "surcharge": surcharge,
        "auth_code": auth_code,
        "reference_number": ref_no,
        "card_type": "Mastercard Corporate",
        "last_4": last4,
        "3d_secure": {
            "eci": eci,
            "cavv": cavv,
            "liability_shift": "Issuer (Liability Protected)" if eci in ["02", "05"] else "Merchant Liable"
        },
        "active_node_index": 5
    }

@app.post("/api/v2/dispute/rebuttal")
def submit_rebuttal(req: DisputeRebuttalRequest):
    if req.reason_code == "4837":
        if req.eci_flag in ["02", "05"]:
            return {
                "verdict": "REPRESENTMENT WON",
                "liability_shift": True,
                "badge": "badge-success",
                "details": "Liability shift secured via 3DS CAVV/ECI flag. Issuer absorbs fraud loss under Mastercard Scheme rules. $500 arbitration fee saved."
            }
        else:
            return {
                "verdict": "MERCHANT LIABLE",
                "liability_shift": False,
                "badge": "badge-danger",
                "details": "Non-3DS transaction (ECI 07). Compelling evidence insufficient. Merchant absorbs transaction write-off."
            }
    else:
        return {
            "verdict": "PRE-ARBITRATION DISPATCHED",
            "liability_shift": True,
            "badge": "badge-warning",
            "details": f"Signed Courier POD '{req.pod_tracking_number}' and invoice dispatched to Mastercard Claims Portal within 30-day TAT."
        }

@app.post("/api/v2/webhooks/dispatch")
def webhook_dispatch():
    secret_key = "fuze_sec_9948201"
    payload = {
        "type": "succeeded",
        "subType": "charge",
        "event": "transaction",
        "id": f"evt_{int(datetime.datetime.utcnow().timestamp())}",
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "data": {
            "status": "Approved",
            "auth_code": "AUTH994812",
            "card_type": "Mastercard Corporate",
            "amount": 2617.14
        }
    }
    payload_str = json.dumps(payload)
    sig = hmac.new(secret_key.encode(), payload_str.encode(), hashlib.sha256).hexdigest()
    return {
        "webhook_url": "https://api.merchant.com/fuze-webhook",
        "x_signature": sig,
        "payload": payload
    }

@app.get("/api/v2/ledger/stream")
def get_ledger_stream():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT reference_number, timestamp, source_type, amount, surcharge, card_last4, auth_code, status, eci FROM transactions ORDER BY id DESC LIMIT 8")
    rows = cur.fetchall()
    conn.close()
    return [{
        "ref_no": r[0], "timestamp": r[1], "source": r[2], "amount": r[3],
        "surcharge": r[4], "last4": r[5], "auth_code": r[6], "status": r[7], "eci": r[8]
    } for r in rows]

# --- Neumorphic Interactive Dashboard ---
NEUMORPHIC_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FlowCase · Neumorphic Fuze Payment Gateway Engine</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #E2E8F0;
            --neu-flat: 6px 6px 14px #c2c8d2, -6px -6px 14px #ffffff;
            --neu-flat-sm: 4px 4px 8px #c2c8d2, -4px -4px 8px #ffffff;
            --neu-pressed: inset 4px 4px 8px #c2c8d2, inset -4px -4px 8px #ffffff;
            --neu-card: 10px 10px 22px #c2c8d2, -10px -10px 22px #ffffff;
        }
        body {
            background-color: var(--bg-color);
            font-family: 'Plus Jakarta Sans', sans-serif;
            color: #334155;
        }
        .neu-panel {
            background: #E2E8F0;
            box-shadow: var(--neu-card);
            border-radius: 20px;
        }
        .neu-btn {
            background: #E2E8F0;
            box-shadow: var(--neu-flat);
            border-radius: 12px;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .neu-btn:hover {
            box-shadow: 4px 4px 10px #c2c8d2, -4px -4px 10px #ffffff;
            transform: translateY(-1px);
        }
        .neu-btn:active, .neu-btn-active {
            background: #E2E8F0;
            box-shadow: var(--neu-pressed);
            color: #2563EB;
        }
        .neu-input {
            background: #E2E8F0;
            box-shadow: var(--neu-pressed);
            border-radius: 12px;
            border: 1px solid rgba(255, 255, 255, 0.4);
            color: #1E293B;
        }
        .neu-inset {
            background: #E2E8F0;
            box-shadow: var(--neu-pressed);
            border-radius: 14px;
        }
        .font-mono { font-family: 'JetBrains Mono', monospace; }
        .badge-success { background: #DCFCE7; color: #166534; }
        .badge-danger { background: #FEE2E2; color: #991B1B; }
        .badge-warning { background: #FEF3C7; color: #92400E; }
    </style>
</head>
<body class="min-h-screen p-6 md:p-8 flex flex-col items-center">

    <div class="max-w-7xl w-full space-y-6">

        <!-- Top Header Card (FlowCase Style) -->
        <header class="neu-panel px-6 py-4 flex flex-col md:flex-row items-center justify-between gap-4">
            <div class="flex items-center gap-4">
                <div class="w-12 h-12 neu-btn flex items-center justify-center font-bold text-blue-600 text-xl">
                    F
                </div>
                <div>
                    <h1 class="text-xl font-bold tracking-tight text-slate-800">FlowCase · Fuze Payments Console</h1>
                    <p class="text-xs text-slate-500 font-medium">B2B Payment Acceleration Platform • API v2.0 • MPGS & Mastercard Rails</p>
                </div>
            </div>

            <div class="flex items-center gap-3">
                <a href="/docs" target="_blank" class="neu-btn px-4 py-2 text-xs font-semibold text-slate-700 flex items-center gap-2">
                    <span>Swagger API</span>
                </a>
                <div class="neu-btn px-4 py-2 text-xs font-semibold text-emerald-600 flex items-center gap-2">
                    <span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
                    <span>Switch Active</span>
                </div>
            </div>
        </header>

        <!-- KPI Metrics Ribbon (FlowCase Cards) -->
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div class="neu-panel p-4">
                <div class="text-[11px] font-bold tracking-wider text-slate-400 uppercase">LATENCY</div>
                <div class="text-2xl font-extrabold text-slate-800 mt-1">~0.8 s</div>
                <div class="text-[10px] text-emerald-600 mt-0.5">Dual-message ISO 8583</div>
            </div>
            <div class="neu-panel p-4">
                <div class="text-[11px] font-bold tracking-wider text-slate-400 uppercase">VOLUME (SIM.)</div>
                <div id="statVolume" class="text-2xl font-extrabold text-blue-600 mt-1">$2.61M</div>
                <div class="text-[10px] text-slate-500 mt-0.5">B2B Accelerated Rails</div>
            </div>
            <div class="neu-panel p-4">
                <div class="text-[11px] font-bold tracking-wider text-slate-400 uppercase">LIABILITY SHIFT</div>
                <div class="text-2xl font-extrabold text-slate-800 mt-1">100%</div>
                <div class="text-[10px] text-emerald-600 mt-0.5">3DS ECI 05 Authenticated</div>
            </div>
            <div class="neu-panel p-4">
                <div class="text-[11px] font-bold tracking-wider text-slate-400 uppercase">TSYS SURCHARGE</div>
                <div class="text-2xl font-extrabold text-slate-800 mt-1">2.15%</div>
                <div class="text-[10px] text-slate-500 mt-0.5">Credit BIN Rule Applied</div>
            </div>
        </div>

        <!-- Interactive Live Node Topology (Neumorphic FlowCase Steps) -->
        <div class="neu-panel p-6 space-y-4">
            <div class="flex items-center justify-between">
                <div>
                    <h2 class="text-sm font-bold text-slate-800">Payment Acceleration: Live Node Topology</h2>
                    <p class="text-xs text-slate-500">End-to-end tokenization, authorization hold, and scheme clearing pipeline.</p>
                </div>
                <div id="pipelineStatus" class="neu-btn px-3 py-1 text-xs font-mono text-blue-600 font-semibold">
                    STATUS: READY
                </div>
            </div>

            <div class="grid grid-cols-2 md:grid-cols-5 gap-3">
                <div id="step-1" class="neu-btn p-3.5 text-center">
                    <div class="w-6 h-6 neu-btn mx-auto flex items-center justify-center text-xs font-bold text-blue-600 mb-1">1</div>
                    <div class="text-xs font-bold text-slate-800">Hosted Lib v0.3</div>
                    <div class="text-[10px] text-slate-500">nonce-xxxx Token</div>
                </div>
                <div id="step-2" class="neu-btn p-3.5 text-center">
                    <div class="w-6 h-6 neu-btn mx-auto flex items-center justify-center text-xs font-bold text-blue-600 mb-1">2</div>
                    <div class="text-xs font-bold text-slate-800">Fuze Switch</div>
                    <div class="text-[10px] text-slate-500">Surcharge & 3DS2</div>
                </div>
                <div id="step-3" class="neu-btn p-3.5 text-center">
                    <div class="w-6 h-6 neu-btn mx-auto flex items-center justify-center text-xs font-bold text-blue-600 mb-1">3</div>
                    <div class="text-xs font-bold text-slate-800">TSYS Processor</div>
                    <div class="text-[10px] text-slate-500">MID/TID Validation</div>
                </div>
                <div id="step-4" class="neu-btn p-3.5 text-center">
                    <div class="w-6 h-6 neu-btn mx-auto flex items-center justify-center text-xs font-bold text-blue-600 mb-1">4</div>
                    <div class="text-xs font-bold text-slate-800">Mastercard Rail</div>
                    <div class="text-[10px] text-slate-500">Dual-Message / IPM</div>
                </div>
                <div id="step-5" class="neu-btn p-3.5 text-center col-span-2 md:col-span-1">
                    <div class="w-6 h-6 neu-btn mx-auto flex items-center justify-center text-xs font-bold text-blue-600 mb-1">5</div>
                    <div class="text-xs font-bold text-slate-800">Issuer Core</div>
                    <div class="text-[10px] text-slate-500">Auth & Lien Placed</div>
                </div>
            </div>
        </div>

        <!-- Pill Nav Filters -->
        <div class="neu-panel p-2 flex flex-wrap gap-2">
            <button onclick="changeTab('tab-charge', this)" class="neu-btn neu-btn-active px-5 py-2 text-xs font-bold">
                1. Charge & Tokenization
            </button>
            <button onclick="changeTab('tab-clearing', this)" class="neu-btn px-5 py-2 text-xs font-bold text-slate-600">
                2. Dual-Message IPM Clearing
            </button>
            <button onclick="changeTab('tab-dispute', this)" class="neu-btn px-5 py-2 text-xs font-bold text-slate-600">
                3. Chargeback Arbitration Desk
            </button>
            <button onclick="changeTab('tab-webhook', this)" class="neu-btn px-5 py-2 text-xs font-bold text-slate-600">
                4. Webhooks & HMAC SHA-256
            </button>
        </div>

        <!-- Tab 1: Charge & Tokenization -->
        <div id="tab-charge" class="neu-panel p-6">
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
                <div class="space-y-4 text-xs">
                    <div class="flex justify-between items-center pb-2 border-b border-slate-300">
                        <span class="font-bold text-slate-800">Trigger /api/v2/transactions/charge</span>
                        <span class="font-mono text-slate-500">POST /charge</span>
                    </div>

                    <div>
                        <label class="block font-semibold text-slate-600 mb-1">Payment Method Source</label>
                        <select id="sourceSelect" class="w-full neu-input p-2.5 text-xs font-medium outline-none">
                            <option value="nonce-HT_9920194820194">Hosted Tokenization (nonce-HT_9920194820194)</option>
                            <option value="googlepay">Google Pay (Cryptogram_3DS)</option>
                            <option value="applepay">Apple Pay (TSYS Encrypted)</option>
                        </select>
                    </div>

                    <div class="grid grid-cols-2 gap-3">
                        <div>
                            <label class="block font-semibold text-slate-600 mb-1">Gross Amount (USD)</label>
                            <input id="chargeAmt" type="number" value="2617.14" class="w-full neu-input p-2.5 text-xs font-mono font-bold">
                        </div>
                        <div>
                            <label class="block font-semibold text-slate-600 mb-1">BIN Surcharge</label>
                            <select id="binSelect" class="w-full neu-input p-2.5 text-xs font-medium outline-none">
                                <option value="C">Credit Card (+2.15% Surcharge)</option>
                                <option value="D">Debit Card (Exempt)</option>
                            </select>
                        </div>
                    </div>

                    <div class="neu-inset p-3 flex items-center justify-between">
                        <div>
                            <div class="font-bold text-slate-700">Simulate 3DS2 Challenge Timeout</div>
                            <div class="text-[11px] text-slate-500">Triggers Paay Challenge fail & auto-reversal 0400</div>
                        </div>
                        <input id="simFail" type="checkbox" class="w-4 h-4 accent-blue-600">
                    </div>

                    <button onclick="runCharge()" class="w-full neu-btn py-3 font-bold text-blue-600 hover:text-blue-700">
                        Execute Charge Request
                    </button>
                </div>

                <!-- Response Console -->
                <div class="neu-inset p-4 flex flex-col justify-between font-mono text-xs">
                    <div>
                        <div class="flex justify-between items-center pb-2 border-b border-slate-300 text-[11px] text-slate-500 font-bold">
                            <span>RESPONSE_STREAM</span>
                            <span id="chargeBadge" class="text-blue-600">READY</span>
                        </div>
                        <pre id="chargeOutput" class="mt-3 text-slate-700 whitespace-pre-wrap leading-relaxed text-[11px]">Click "Execute Charge Request" to send real payload to Fuze API v2...</pre>
                    </div>
                    <div class="pt-2 border-t border-slate-300 text-[10px] text-slate-400 flex justify-between">
                        <span>HTTP 200 OK</span>
                        <span>Fuze Engine v2.0.0</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- Tab 2: Dual-Message IPM Clearing -->
        <div id="tab-clearing" class="neu-panel p-6 hidden">
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
                <div class="space-y-4 text-xs">
                    <h3 class="font-bold text-slate-800">Mastercard Dual-Message Clearing Engine</h3>
                    <p class="text-slate-600 leading-relaxed">
                        Card transactions real-time mein sirf limit hold karte hain. Din ke ant mein acquirer bank daily batch IPM (Integrated Processing Module) file Mastercard ko bhejta hai, jisse net settlement calculate hoti hai.
                    </p>

                    <div>
                        <label class="block font-semibold text-slate-600 mb-1">EOD IPM Presentment Record (.DAT)</label>
                        <textarea id="ipmText" rows="3" class="w-full neu-input p-3 font-mono text-[11px]">REC_PDS0200|FUZE_MID_88410|GROSS_2617.14|USD|ECI_05|RRN_994820194810|TSYS_NORTH</textarea>
                    </div>

                    <button onclick="runIPM()" class="w-full neu-btn py-3 font-bold text-amber-600">
                        Audit IPM Presentment & Calculate Net Payout
                    </button>
                </div>

                <div class="neu-inset p-4 flex flex-col justify-between text-xs">
                    <div class="space-y-2.5">
                        <div class="flex justify-between pb-2 border-b border-slate-300 font-bold font-mono">
                            <span class="text-slate-600">SETTLEMENT_BREAKDOWN</span>
                            <span id="ipmBadge" class="text-amber-600">READY</span>
                        </div>
                        <div class="flex justify-between py-1 border-b border-slate-200">
                            <span class="text-slate-500">Gross Authorized:</span>
                            <span class="font-mono font-bold">$2,617.14</span>
                        </div>
                        <div class="flex justify-between py-1 border-b border-slate-200">
                            <span class="text-slate-500">Interchange Fee (Issuer):</span>
                            <span class="font-mono text-rose-600 font-bold">-$31.40 (1.20%)</span>
                        </div>
                        <div class="flex justify-between py-1 border-b border-slate-200">
                            <span class="text-slate-500">Mastercard Scheme Assessment:</span>
                            <span class="font-mono text-rose-600 font-bold">-$4.18 (0.16%)</span>
                        </div>
                        <div class="flex justify-between py-1 font-bold">
                            <span class="text-slate-800">Net Merchant Settlement Payout:</span>
                            <span class="font-mono text-emerald-600 text-sm font-extrabold">$2,581.56</span>
                        </div>
                    </div>
                    <div class="pt-2 border-t border-slate-300 text-[10px] text-slate-400 font-mono">
                        Recon: Matched against Scheme Settlement Batch
                    </div>
                </div>
            </div>
        </div>

        <!-- Tab 3: Chargeback Arbitration Desk -->
        <div id="tab-dispute" class="neu-panel p-6 hidden">
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
                <div class="space-y-4 text-xs">
                    <h3 class="font-bold text-slate-800">Chargeback Arbitration & Liability Shift Desk</h3>
                    
                    <div class="grid grid-cols-2 gap-3">
                        <div>
                            <label class="block font-semibold text-slate-600 mb-1">Reason Code</label>
                            <select id="dispReason" class="w-full neu-input p-2.5 text-xs font-medium outline-none">
                                <option value="4837">4837 (Fraud / No Auth)</option>
                                <option value="4853">4853 (Service Not Received)</option>
                            </select>
                        </div>
                        <div>
                            <label class="block font-semibold text-slate-600 mb-1">3DS ECI Flag</label>
                            <select id="dispEci" class="w-full neu-input p-2.5 text-xs font-medium outline-none">
                                <option value="05">ECI 05 (Full 3DS Success)</option>
                                <option value="02">ECI 02 (Identity Check Pass)</option>
                                <option value="07">ECI 07 (Non-3DS / Merchant Liable)</option>
                            </select>
                        </div>
                    </div>

                    <div>
                        <label class="block font-semibold text-slate-600 mb-1">Proof of Delivery (POD) / Tracking Ref</label>
                        <input id="dispPod" type="text" value="FEDEX_POD_994820184_SIGNED" class="w-full neu-input p-2.5 font-mono text-xs">
                    </div>

                    <button onclick="runDispute()" class="w-full neu-btn py-3 font-bold text-rose-600">
                        Dispatch Rebuttal Claim to Scheme
                    </button>
                </div>

                <div class="neu-inset p-4 flex flex-col justify-between text-xs">
                    <div class="space-y-3">
                        <div class="flex justify-between pb-2 border-b border-slate-300 font-bold font-mono">
                            <span class="text-slate-600">ARBITRATION_VERDICT</span>
                            <span id="dispVerdictBadge" class="text-slate-400">READY</span>
                        </div>
                        <p id="dispDetails" class="text-slate-600 leading-relaxed font-mono">
                            Awaiting evidence submission to execute liability shift algorithm...
                        </p>
                    </div>
                    <div class="pt-2 border-t border-slate-300 text-[10px] text-slate-400 font-mono flex justify-between">
                        <span>Mastercard Claims Portal</span>
                        <span>TAT: 30-Day Window</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- Tab 4: Webhooks & HMAC -->
        <div id="tab-webhook" class="neu-panel p-6 hidden">
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
                <div class="space-y-4 text-xs">
                    <h3 class="font-bold text-slate-800">Webhook HMAC-SHA256 Signature Generator</h3>
                    <p class="text-slate-600 leading-relaxed">
                        Fuze har transaction event par merchant ke endpoint par webhook fire karta hai. Integrity verify karne ke liye <code class="bg-slate-200 px-1 py-0.5 rounded font-mono text-blue-600">X-Signature</code> header attach hota hai.
                    </p>
                    <button onclick="runWebhook()" class="w-full neu-btn py-3 font-bold text-indigo-600">
                        Simulate Event & Verify X-Signature
                    </button>
                </div>

                <div class="neu-inset p-4 font-mono text-xs">
                    <div class="text-[11px] text-slate-500 pb-2 border-b border-slate-300 font-bold">
                        DISPATCHED_EVENT_STREAM
                    </div>
                    <pre id="webhookOutput" class="mt-3 text-slate-700 whitespace-pre-wrap leading-relaxed text-[11px]">Click to generate and verify HMAC SHA-256 signature...</pre>
                </div>
            </div>
        </div>

        <!-- Live Double-Entry Ledger Stream -->
        <div class="neu-panel p-6 space-y-4">
            <div class="flex items-center justify-between">
                <div>
                    <h3 class="text-sm font-bold text-slate-800">Persistent Double-Entry Operations Ledger</h3>
                    <p class="text-xs text-slate-500">Live journal recording SQLite authorizations, surcharges, and ECI liability states.</p>
                </div>
                <button onclick="loadLedger()" class="neu-btn px-4 py-2 text-xs font-mono font-bold text-slate-700">
                    ↻ Refresh Stream
                </button>
            </div>

            <div class="overflow-x-auto neu-inset p-2">
                <table class="w-full text-left text-xs font-mono">
                    <thead class="text-slate-500 border-b border-slate-300">
                        <tr>
                            <th class="p-3">REF NUMBER</th>
                            <th class="p-3">TIMESTAMP</th>
                            <th class="p-3">METHOD</th>
                            <th class="p-3">BASE AMT</th>
                            <th class="p-3">SURCHARGE</th>
                            <th class="p-3">CARD</th>
                            <th class="p-3">AUTH CODE</th>
                            <th class="p-3">ECI</th>
                            <th class="p-3">STATUS</th>
                        </tr>
                    </thead>
                    <tbody id="ledgerRows" class="divide-y divide-slate-300/60 text-slate-700">
                        <tr>
                            <td colspan="9" class="p-4 text-center text-slate-400">Loading live ledger stream...</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>

    </div>

    <script>
        function changeTab(tabId, btn) {
            ['tab-charge', 'tab-clearing', 'tab-dispute', 'tab-webhook'].forEach(id => {
                document.getElementById(id).classList.add('hidden');
            });
            document.querySelectorAll('header ~ .neu-panel:nth-of-type(3) button').forEach(b => {
                b.classList.remove('neu-btn-active');
            });
            document.getElementById(tabId).classList.remove('hidden');
            btn.classList.add('neu-btn-active');
        }

        function highlightSteps(upToStep, isApproved) {
            for (let i = 1; i <= 5; i++) {
                const el = document.getElementById('step-' + i);
                if (i <= upToStep) {
                    el.className = isApproved 
                        ? 'neu-btn neu-btn-active p-3.5 text-center text-blue-600' 
                        : 'neu-btn p-3.5 text-center text-rose-600 bg-rose-50 border border-rose-300';
                } else {
                    el.className = 'neu-btn p-3.5 text-center text-slate-400';
                }
            }
        }

        async function runCharge() {
            const src = document.getElementById('sourceSelect').value;
            const amt = parseFloat(document.getElementById('chargeAmt').value);
            const bin = document.getElementById('binSelect').value;
            const fail = document.getElementById('simFail').checked;
            const out = document.getElementById('chargeOutput');
            const badge = document.getElementById('chargeBadge');
            const pStat = document.getElementById('pipelineStatus');

            badge.innerText = 'SWITCHING...';
            pStat.innerText = 'STATUS: ROUTING PAYLOAD';

            try {
                const res = await fetch('/api/v2/transactions/charge', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        amount: amt,
                        source: src,
                        bin_type: bin,
                        simulate_failure: fail,
                        '3d_secure': { eci: '05', cavv: 'AAABBIIFmQAAAAAJUGFmAAAAAAA=' }
                    })
                });
                const d = await res.json();
                out.innerText = JSON.stringify(d, null, 2);
                badge.innerText = d.status;
                badge.className = d.status === 'Approved' ? 'text-emerald-600 font-bold' : 'text-rose-600 font-bold';
                pStat.innerText = 'STATUS: ' + d.status;

                highlightSteps(d.active_node_index, d.status === 'Approved');
                loadLedger();
            } catch(e) {
                out.innerText = 'Error: ' + e;
            }
        }

        async function runIPM() {
            const badge = document.getElementById('ipmBadge');
            badge.innerText = 'AUDITED (MATCHED)';
            badge.className = 'text-emerald-600 font-bold font-mono';
            highlightSteps(5, true);
        }

        async function runDispute() {
            const reason = document.getElementById('dispReason').value;
            const eci = document.getElementById('dispEci').value;
            const pod = document.getElementById('dispPod').value;
            const badge = document.getElementById('dispVerdictBadge');
            const det = document.getElementById('dispDetails');

            try {
                const res = await fetch('/api/v2/dispute/rebuttal', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        dispute_id: 'DISP_9948201',
                        reference_number: 994820194,
                        reason_code: reason,
                        eci_flag: eci,
                        pod_tracking_number: pod
                    })
                });
                const d = await res.json();
                badge.innerText = d.verdict;
                badge.className = d.badge + ' px-2 py-0.5 rounded text-xs font-bold';
                det.innerText = d.details;
            } catch(e) {
                det.innerText = 'Error: ' + e;
            }
        }

        async function runWebhook() {
            const out = document.getElementById('webhookOutput');
            try {
                const res = await fetch('/api/v2/webhooks/dispatch', { method: 'POST' });
                const d = await res.json();
                out.innerText = JSON.stringify(d, null, 2);
            } catch(e) {
                out.innerText = 'Error: ' + e;
            }
        }

        async function loadLedger() {
            const tbody = document.getElementById('ledgerRows');
            try {
                const res = await fetch('/api/v2/ledger/stream');
                const rows = await res.json();
                if (rows.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="9" class="p-4 text-center text-slate-400">No transactions recorded yet.</td></tr>';
                    return;
                }
                tbody.innerHTML = rows.map(r => `
                    <tr class="hover:bg-slate-200/50 transition">
                        <td class="p-3 text-blue-600 font-bold">${r.ref_no}</td>
                        <td class="p-3 text-slate-500 text-[11px]">${r.timestamp}</td>
                        <td class="p-3">${r.source}</td>
                        <td class="p-3 font-bold">$${(r.amount - r.surcharge).toFixed(2)}</td>
                        <td class="p-3 text-slate-500">+$${r.surcharge.toFixed(2)}</td>
                        <td class="p-3 font-mono">•••• ${r.last4}</td>
                        <td class="p-3 font-mono">${r.auth_code}</td>
                        <td class="p-3"><span class="px-2 py-0.5 rounded bg-blue-100 text-blue-700 text-[10px] font-bold">ECI ${r.eci}</span></td>
                        <td class="p-3"><span class="text-emerald-600 font-bold">${r.status}</span></td>
                    </tr>
                `).join('');
            } catch(e) {
                console.error(e);
            }
        }

        window.onload = loadLedger;
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def root():
    return NEUMORPHIC_DASHBOARD_HTMLimport os
import hmac
import hashlib
import sqlite3
import datetime
import json
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

app = FastAPI(
    title="Fuze Payments Gateway API v2 & Operations Engine",
    description="Enterprise Gateway Switch, Digital Wallets, Hosted Tokenization v0.3, Mastercard IPM Clearing & Scheme Arbitration",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

DB_PATH = "fuze_gateway_ledger.db"

# --- SQLite Double-Entry Ledger Schema ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference_number INTEGER UNIQUE,
            timestamp TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_token TEXT,
            amount REAL NOT NULL,
            surcharge REAL DEFAULT 0.0,
            currency TEXT DEFAULT 'USD',
            card_last4 TEXT,
            card_type TEXT,
            auth_code TEXT,
            status TEXT NOT NULL,
            eci TEXT,
            cavv TEXT,
            batch_id INTEGER DEFAULT 1
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ledger_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_no INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            debit_account TEXT NOT NULL,
            credit_account TEXT NOT NULL,
            amount REAL NOT NULL,
            description TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()

# --- Pydantic Models (Fuze API v2 Specifications) ---
class ThreeDSecurePayload(BaseModel):
    eci: Optional[str] = "05"
    cavv: Optional[str] = "AAABBIIFmQAAAAAJUGFmAAAAAAA="
    ds_trans_id: Optional[str] = "084f49cd-2a97-4b13-87a7-a1bd8267cb20"
    verification_id: Optional[str] = "PAAY_VERIF_99410"

class AmountDetails(BaseModel):
    tax: Optional[float] = 0.0
    tax_percent: Optional[float] = 0.0
    surcharge: Optional[float] = 0.0
    shipping: Optional[float] = 0.0
    tip: Optional[float] = 0.0
    discount: Optional[float] = 0.0

class ChargeRequest(BaseModel):
    amount: float
    source: Optional[str] = None  # e.g., "nonce-xxxx", "googlepay", "applepay", "card"
    card: Optional[str] = None
    token: Optional[str] = None   # Digital wallet token
    bin_type: Optional[str] = "C" # "C" (Credit) or "D" (Debit)
    expiry_month: Optional[int] = 12
    expiry_year: Optional[int] = 2028
    cvv2: Optional[str] = "123"
    name: Optional[str] = "Corporate Merchant Partner"
    capture: Optional[bool] = True
    three_d_secure: Optional[ThreeDSecurePayload] = Field(default=None, alias="3d_secure")
    amount_details: Optional[AmountDetails] = None
    simulate_failure: Optional[bool] = False

class CaptureRequest(BaseModel):
    reference_number: int

class AdjustRequest(BaseModel):
    reference_number: int
    amount: float

class VoidRequest(BaseModel):
    reference_number: int

class RefundRequest(BaseModel):
    reference_number: int
    amount: Optional[float] = None

class SurchargeCheckRequest(BaseModel):
    source_type: str
    source: str

class DisputeRebuttalRequest(BaseModel):
    dispute_id: str
    reference_number: int
    reason_code: str  # 4837 (Fraud) or 4853 (Service)
    eci_flag: str
    pod_tracking_number: str
    compelling_evidence_notes: str

# --- Fuze API v2 Endpoints ---

@app.post("/api/v2/transactions/charge", tags=["Transactions"])
def charge_transaction(req: ChargeRequest):
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    ref_no = int(datetime.datetime.utcnow().timestamp() * 1000) % 1000000000
    auth_code = f"AUTH{ref_no % 1000000:06d}"

    if req.simulate_failure:
        return {
            "version": "2.0.0",
            "status": "Declined",
            "status_code": "D",
            "error_code": "3DS_CHALLENGE_TIMEOUT",
            "error_message": "3D Secure 2.0 Challenge session expired. Auto-reversal 0400 dispatched.",
            "auth_amount": 0,
            "reference_number": ref_no
        }

    # Surcharge calculation for TSYS B2B credit processing
    surcharge_val = round(req.amount * 0.0215, 2) if req.bin_type == "C" else 0.0
    final_amount = req.amount + surcharge_val

    # Detect Card last4 / Source type
    src_type = "Credit Card"
    last4 = "6668"
    if req.source:
        if "nonce-" in req.source:
            src_type = "Hosted Tokenization (v0.3)"
            last4 = req.source[-4:]
        elif req.source == "googlepay":
            src_type = "Google Pay (Cryptogram_3DS)"
            last4 = "4111"
        elif req.source == "applepay":
            src_type = "Apple Pay (TSYS Encrypted)"
            last4 = "8892"

    eci = req.three_d_secure.eci if req.three_d_secure else "05"
    cavv = req.three_d_secure.cavv if req.three_d_secure else "AAABBIIFmQAAAAAJUGFmAAAAAAA="

    # Record in SQLite Ledger
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO transactions (reference_number, timestamp, source_type, source_token, amount, surcharge, card_last4, card_type, auth_code, status, eci, cavv, batch_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    """, (ref_no, timestamp, src_type, req.source or "RAW_CARD_VAULT", final_amount, surcharge_val, last4, "Mastercard Corporate", auth_code, "Captured" if req.capture else "Approved", eci, cavv))

    cur.execute("""
        INSERT INTO ledger_journal (ref_no, timestamp, debit_account, credit_account, amount, description)
        VALUES (?, ?, 'CARDHOLDER_ISSUER_HOLD', 'FUZE_ACQUIRER_SETTLEMENT_POOL', ?, ?)
    """, (ref_no, timestamp, final_amount, f"Auth & Capture via {src_type}"))
    conn.commit()
    conn.close()

    return {
        "version": "2.0.0",
        "status": "Approved",
        "status_code": "A",
        "auth_amount": final_amount,
        "auth_code": auth_code,
        "reference_number": ref_no,
        "card_type": "Mastercard Corporate",
        "last_4": last4,
        "avs_result_code": "YYY",
        "cvv2_result_code": "M",
        "transaction": {
            "id": ref_no,
            "created_at": timestamp,
            "settled_date": datetime.date.today().isoformat(),
            "amount_details": {
                "base_amount": req.amount,
                "surcharge": surcharge_val,
                "tax": 0.0
            }
        },
        "3d_secure": {
            "eci": eci,
            "cavv": cavv,
            "liability_shift": "Issuer" if eci in ["02", "05"] else "Merchant"
        }
    }

@app.post("/api/v2/transactions/capture", tags=["Transactions"])
def capture_transaction(req: CaptureRequest):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE transactions SET status = 'Captured' WHERE reference_number = ?", (req.reference_number,))
    conn.commit()
    conn.close()
    return {
        "version": "2.0.0",
        "status": "Approved",
        "status_code": "A",
        "reference_number": req.reference_number,
        "message": "Authorization successfully captured into current settlement batch."
    }

@app.post("/api/v2/transactions/void", tags=["Transactions"])
def void_transaction(req: VoidRequest):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE transactions SET status = 'Voided' WHERE reference_number = ?", (req.reference_number,))
    conn.commit()
    conn.close()
    return {
        "version": "2.0.0",
        "status": "Approved",
        "status_code": "A",
        "type": "Void",
        "message": "Unsettled transaction voided and authorization hold released."
    }

@app.post("/api/v2/transactions/refund", tags=["Transactions"])
def refund_transaction(req: RefundRequest):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE transactions SET status = 'Refunded' WHERE reference_number = ?", (req.reference_number,))
    conn.commit()
    conn.close()
    return {
        "version": "2.0.0",
        "status": "Approved",
        "status_code": "A",
        "reference_number": req.reference_number,
        "type": "Refund",
        "message": "Credit refund queued for settlement."
    }

@app.post("/api/v2/surcharge", tags=["Surcharge"])
def calculate_surcharge(req: SurchargeCheckRequest):
    # Compliant TSYS Surcharge calculation
    return {
        "surcharge": {
            "type": "percent",
            "value": 2.15
        },
        "bin_type": "C",
        "payment_type": "card",
        "compliant_tsys_rule": "Surcharge applies only to Credit BINs; Debit cards exempt."
    }

@app.get("/api/v2/batches", tags=["Settlement & Batches"])
def get_batches():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), SUM(amount) FROM transactions WHERE status = 'Captured'")
    count, total = cur.fetchone()
    conn.close()
    return [{
        "id": 1,
        "opened_at": "2026-10-06T00:00:00Z",
        "closed_at": None,
        "platform": "north",
        "charges_sum": total or 0.0,
        "charges_count": count or 0,
        "transactions_count": count or 0,
        "status": "open"
    }]

@app.post("/api/v2/dispute/rebuttal", tags=["Chargeback & Arbitration"])
def submit_chargeback_rebuttal(req: DisputeRebuttalRequest):
    if req.reason_code == "4837":  # Fraud
        if req.eci_flag in ["02", "05"]:
            return {
                "dispute_id": req.dispute_id,
                "status": "REPRESENTMENT_WON",
                "liability_shift": True,
                "arbitration_outcome": "LIABILITY SHIFT CONFIRMED: 3DS CAVV / ECI 05 proof authenticated. Issuer absorbs transaction liability under Mastercard rules.",
                "scheme_fees_saved": "$500 Arbitration Penalty Waived"
            }
        else:
            return {
                "dispute_id": req.dispute_id,
                "status": "MERCHANT_LIABLE",
                "liability_shift": False,
                "arbitration_outcome": "MERCHANT LIABLE: ECI 07 (Non-authenticated transaction). Insufficient compelling evidence to reverse debit."
            }
    else:  # 4853 Service / Goods not received
        return {
            "dispute_id": req.dispute_id,
            "status": "ESCALATED_PRE_ARBITRATION",
            "liability_shift": True,
            "arbitration_outcome": f"POD tracking '{req.pod_tracking_number}' and invoice documentation dispatched to Scheme Claims Portal.",
            "tat_window": "10 Days to Scheme Review"
        }

@app.post("/api/v2/webhooks/dispatch", tags=["Webhooks"])
def dispatch_webhook_test(secret_key: str = "fuze_sec_9948201"):
    event_payload = {
        "type": "succeeded",
        "subType": "charge",
        "event": "transaction",
        "id": f"evt_{int(datetime.datetime.utcnow().timestamp())}",
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "data": {
            "version": "2.0.0",
            "status": "Approved",
            "status_code": "A",
            "auth_code": "AUTH994812",
            "card_type": "Mastercard Corporate",
            "last_4": "6668"
        }
    }
    payload_str = json.dumps(event_payload)
    signature = hmac.new(secret_key.encode(), payload_str.encode(), hashlib.sha256).hexdigest()
    return {
        "webhook_url": "https://api.merchant.com/fuze-webhook",
        "headers": {
            "Content-Type": "application/json",
            "X-Signature": signature
        },
        "payload": event_payload
    }

@app.get("/api/v2/ledger/stream", tags=["Ledger"])
def get_ledger_stream():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT reference_number, timestamp, source_type, amount, card_last4, auth_code, status, eci FROM transactions ORDER BY id DESC LIMIT 10")
    rows = cur.fetchall()
    conn.close()
    return [{
        "ref_no": r[0], "timestamp": r[1], "source": r[2], "amount": r[3],
        "last4": r[4], "auth_code": r[5], "status": r[6], "eci": r[7]
    } for r in rows]

# --- Standalone Sleek Enterprise Dashboard UI ---
DASHBOARD_UI = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Fuze Payments Gateway Operations & Scheme Engine</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Plus Jakarta Sans', sans-serif; }
        .font-mono, pre, code { font-family: 'JetBrains Mono', monospace; }
    </style>
</head>
<body class="bg-[#0A0E17] text-slate-100 min-h-screen antialiased flex flex-col">

    <!-- Header -->
    <header class="border-b border-slate-800 bg-[#0F172A]/90 backdrop-blur px-6 py-3.5 sticky top-0 z-50 flex items-center justify-between">
        <div class="flex items-center gap-4">
            <div class="h-9 w-9 rounded-xl bg-gradient-to-tr from-cyan-500 to-indigo-600 flex items-center justify-center font-bold text-white shadow-lg shadow-cyan-500/20">
                FZ
            </div>
            <div>
                <div class="flex items-center gap-2">
                    <span class="text-sm font-semibold tracking-wide text-white">Fuze Payments Gateway Engine (API v2.0)</span>
                    <span class="text-[10px] px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 font-medium">B2B Production Core</span>
                </div>
                <p class="text-xs text-slate-400">Hosted Tokenization v0.3 • Digital Wallets • Mastercard IPM Clearing & Disputes</p>
            </div>
        </div>
        <div class="flex items-center gap-4">
            <a href="/docs" target="_blank" class="text-xs font-mono text-cyan-400 hover:underline flex items-center gap-1.5 bg-slate-900 border border-slate-800 px-3 py-1.5 rounded-lg">
                <span>📄 OpenAPI Swagger</span>
            </a>
            <div class="flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-medium">
                <span class="h-2 w-2 rounded-full bg-emerald-400 animate-ping"></span>
                TSYS & Switch Online
            </div>
        </div>
    </header>

    <!-- Main Container -->
    <main class="flex-1 max-w-7xl w-full mx-auto px-6 py-6 space-y-6">

        <!-- Live Visual Switch Topology -->
        <div class="bg-gradient-to-b from-[#111827] to-[#0E1522] border border-slate-800 rounded-2xl p-5 shadow-xl">
            <div class="flex items-center justify-between mb-4">
                <div class="text-xs font-semibold uppercase tracking-wider text-cyan-400">Real-Time Fuze Payment Acceleration Topology</div>
                <div id="topoState" class="text-xs font-mono text-slate-400">READY: AWAITING_PAYLOAD</div>
            </div>
            <div class="grid grid-cols-6 gap-3">
                <div id="p-client" class="bg-slate-900/90 border border-slate-800 rounded-xl p-3 text-center transition-all">
                    <div class="text-[10px] text-slate-400 font-mono">1. ORIGIN</div>
                    <div class="text-xs font-bold text-slate-200 mt-1">Client Frontend</div>
                    <div class="text-[10px] text-slate-500">Hosted Lib v0.3</div>
                </div>
                <div id="p-token" class="bg-slate-900/90 border border-slate-800 rounded-xl p-3 text-center transition-all">
                    <div class="text-[10px] text-cyan-400 font-mono">2. VAULT</div>
                    <div class="text-xs font-bold text-white mt-1">Nonce Token</div>
                    <div class="text-[10px] text-slate-500">nonce-xxxx (15m)</div>
                </div>
                <div id="p-switch" class="bg-slate-900/90 border border-slate-800 rounded-xl p-3 text-center transition-all">
                    <div class="text-[10px] text-indigo-400 font-mono">3. GATEWAY</div>
                    <div class="text-xs font-bold text-white mt-1">Fuze API v2</div>
                    <div class="text-[10px] text-slate-500">Surcharge & 3DS</div>
                </div>
                <div id="p-acquirer" class="bg-slate-900/90 border border-slate-800 rounded-xl p-3 text-center transition-all">
                    <div class="text-[10px] text-slate-400 font-mono">4. PROCESSOR</div>
                    <div class="text-xs font-bold text-slate-200 mt-1">TSYS / Acquirer</div>
                    <div class="text-[10px] text-slate-500">MID / TID Host</div>
                </div>
                <div id="p-scheme" class="bg-slate-900/90 border border-slate-800 rounded-xl p-3 text-center transition-all">
                    <div class="text-[10px] text-amber-400 font-mono">5. SCHEME</div>
                    <div class="text-xs font-bold text-white mt-1">Mastercard Rail</div>
                    <div class="text-[10px] text-slate-500">Dual-Message / IPM</div>
                </div>
                <div id="p-issuer" class="bg-slate-900/90 border border-slate-800 rounded-xl p-3 text-center transition-all">
                    <div class="text-[10px] text-slate-400 font-mono">6. ISSUER</div>
                    <div class="text-xs font-bold text-slate-200 mt-1">Issuing Bank</div>
                    <div class="text-[10px] text-slate-500">Auth & Lien Hold</div>
                </div>
            </div>
        </div>

        <!-- Operations Console Tabs -->
        <div class="bg-[#111827] border border-slate-800 rounded-2xl shadow-xl overflow-hidden">
            <div class="flex border-b border-slate-800 bg-slate-950/70 px-6 pt-3 gap-6 text-xs font-medium">
                <button onclick="tabSwitch('charge')" id="btn-charge" class="pb-3 text-cyan-400 border-b-2 border-cyan-500 font-semibold transition">
                    1. Charge & Tokenization Engine
                </button>
                <button onclick="tabSwitch('clearing')" id="btn-clearing" class="pb-3 text-slate-400 hover:text-slate-200 transition">
                    2. Dual-Message & IPM Clearing
                </button>
                <button onclick="tabSwitch('dispute')" id="btn-dispute" class="pb-3 text-slate-400 hover:text-slate-200 transition">
                    3. Chargeback Arbitration & ECI Desk
                </button>
                <button onclick="tabSwitch('webhook')" id="btn-webhook" class="pb-3 text-slate-400 hover:text-slate-200 transition">
                    4. Webhooks & HMAC Signature
                </button>
            </div>

            <!-- Tab 1: Charge & Tokenization -->
            <div id="t-charge" class="p-6">
                <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
                    <div class="space-y-4 text-xs">
                        <div class="flex items-center justify-between pb-2 border-b border-slate-800">
                            <h3 class="text-sm font-semibold text-white">Execute /api/v2/transactions/charge</h3>
                            <span class="text-slate-400 font-mono text-[11px]">POST /transactions/charge</span>
                        </div>

                        <div>
                            <label class="block text-slate-400 mb-1">Payment Method Source</label>
                            <select id="chargeSource" class="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-white">
                                <option value="nonce-HT_9920194820194">Hosted Tokenization (nonce-HT_9920194820194)</option>
                                <option value="googlepay">Google Pay (source: googlepay | Cryptogram_3DS)</option>
                                <option value="applepay">Apple Pay (source: applepay | TSYS Token)</option>
                                <option value="card">Raw Credit Card (Direct API)</option>
                            </select>
                        </div>

                        <div class="grid grid-cols-2 gap-3">
                            <div>
                                <label class="block text-slate-400 mb-1">Transaction Amount ($ USD)</label>
                                <input id="chargeAmt" type="number" value="2617.14" class="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-white font-mono">
                            </div>
                            <div>
                                <label class="block text-slate-400 mb-1">BIN Surcharge Classification</label>
                                <select id="chargeBin" class="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-white">
                                    <option value="C">Credit Card (2.15% Compliant Surcharge)</option>
                                    <option value="D">Debit Card (Exempt / No Surcharge)</option>
                                </select>
                            </div>
                        </div>

                        <div class="p-3 bg-slate-900/60 border border-slate-800 rounded-xl flex items-center justify-between">
                            <div>
                                <div class="text-slate-200 font-medium">Simulate 3DS2 Challenge Timeout</div>
                                <div class="text-[11px] text-slate-500">Triggers Paay Challenge fail & auto-reversal 0400</div>
                            </div>
                            <input id="chargeSimFail" type="checkbox" class="h-4 w-4 rounded bg-slate-950 border-slate-700 text-cyan-500">
                        </div>

                        <button onclick="executeCharge()" class="w-full py-2.5 rounded-xl bg-cyan-600 hover:bg-cyan-500 font-medium text-white transition shadow-lg shadow-cyan-600/25">
                            Submit Charge Request
                        </button>
                    </div>

                    <!-- Output Console -->
                    <div class="bg-slate-950/80 border border-slate-800 rounded-xl p-4 flex flex-col justify-between font-mono text-xs">
                        <div>
                            <div class="flex items-center justify-between pb-3 border-b border-slate-800 text-[11px]">
                                <span class="text-slate-400">RESPONSE_STREAM</span>
                                <span id="chargeStatusBadge" class="text-slate-500 font-bold">READY</span>
                            </div>
                            <pre id="chargeOutput" class="mt-3 text-slate-400 whitespace-pre-wrap text-[11px] leading-relaxed">Execute a transaction to inspect live Fuze API v2 response payload...</pre>
                        </div>
                        <div class="pt-3 border-t border-slate-900 text-[10px] text-slate-500 flex justify-between">
                            <span>HTTP 200 OK</span>
                            <span>Version: 2.0.0</span>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Tab 2: IPM Clearing & Batches -->
            <div id="t-clearing" class="p-6 hidden">
                <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
                    <div class="space-y-4 text-xs">
                        <div class="flex items-center justify-between pb-2 border-b border-slate-800">
                            <h3 class="text-sm font-semibold text-white">Mastercard Dual-Message IPM Clearing Batch</h3>
                            <span class="text-slate-400 font-mono text-[11px]">GET /api/v2/batches</span>
                        </div>

                        <p class="text-slate-400 leading-relaxed">
                            Card transactions require dual-message batch clearing: Real-time authorization holds funds, and EOD batch capture initiates multilateral net settlement.
                        </p>

                        <div>
                            <label class="block text-slate-400 mb-1">EOD IPM Presentment Record (.DAT snippet)</label>
                            <textarea id="ipmText" rows="3" class="w-full bg-slate-900 border border-slate-800 rounded-xl p-3 text-slate-200 font-mono text-[11px]">REC_PDS0200|FUZE_MID_88410|GROSS_2617.14|USD|ECI_05|RRN_994820194810|TSYS_NORTH</textarea>
                        </div>

                        <button onclick="auditIPM()" class="w-full py-2.5 rounded-xl bg-amber-600 hover:bg-amber-500 font-medium text-white transition shadow-lg shadow-amber-600/25">
                            Audit IPM Presentment & Calculate Settlement
                        </button>
                    </div>

                    <div class="bg-slate-950/80 border border-slate-800 rounded-xl p-5 flex flex-col justify-between text-xs">
                        <div class="space-y-3">
                            <div class="flex items-center justify-between pb-3 border-b border-slate-800 text-[11px] font-mono">
                                <span class="text-slate-400">NET_SETTLEMENT_RECONCILIATION</span>
                                <span id="ipmBadge" class="text-amber-400 font-bold">READY</span>
                            </div>
                            <div id="ipmDetails" class="space-y-2 text-slate-300">
                                <div class="flex justify-between py-1 border-b border-slate-900">
                                    <span class="text-slate-400">Gross Captured Volume:</span>
                                    <span class="font-mono text-white">$2,617.14</span>
                                </div>
                                <div class="flex justify-between py-1 border-b border-slate-900">
                                    <span class="text-slate-400">Interchange Deduction (Issuer):</span>
                                    <span class="font-mono text-rose-400">-$31.40 (1.20%)</span>
                                </div>
                                <div class="flex justify-between py-1 border-b border-slate-900">
                                    <span class="text-slate-400">Mastercard Scheme Assessment:</span>
                                    <span class="font-mono text-rose-400">-$4.18 (0.16%)</span>
                                </div>
                                <div class="flex justify-between py-1 font-semibold text-white">
                                    <span>Net B2B Merchant Payout:</span>
                                    <span class="font-mono text-emerald-400 text-sm">$2,581.56</span>
                                </div>
                            </div>
                        </div>
                        <div class="pt-3 border-t border-slate-900 text-[10px] text-slate-500 font-mono">
                            Recon Status: Matched against e-Kuber & Scheme Pools
                        </div>
                    </div>
                </div>
            </div>

            <!-- Tab 3: Dispute Desk -->
            <div id="t-dispute" class="p-6 hidden">
                <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
                    <div class="space-y-4 text-xs">
                        <div class="flex items-center justify-between pb-2 border-b border-slate-800">
                            <h3 class="text-sm font-semibold text-white">Dispute Arbitration Desk (TAT Rebuttal)</h3>
                            <span class="text-slate-400 font-mono text-[11px]">POST /dispute/rebuttal</span>
                        </div>

                        <div class="grid grid-cols-2 gap-3">
                            <div>
                                <label class="block text-slate-400 mb-1">Reason Code</label>
                                <select id="dispReason" class="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-white">
                                    <option value="4837">4837 (Fraud / No Authorization)</option>
                                    <option value="4853">4853 (Goods/Service Not Received)</option>
                                </select>
                            </div>
                            <div>
                                <label class="block text-slate-400 mb-1">3DS ECI Signature</label>
                                <select id="dispEci" class="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-white">
                                    <option value="05">ECI 05 (Fully Authenticated 3DS OTP)</option>
                                    <option value="02">ECI 02 (Mastercard Identity Check)</option>
                                    <option value="07">ECI 07 (Non-3DS / Merchant Liable)</option>
                                </select>
                            </div>
                        </div>

                        <div>
                            <label class="block text-slate-400 mb-1">Courier POD / Tracking Receipt Reference</label>
                            <input id="dispPod" type="text" value="FEDEX_POD_994820184_SIGNED" class="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-white font-mono">
                        </div>

                        <button onclick="submitDispute()" class="w-full py-2.5 rounded-xl bg-rose-600 hover:bg-rose-500 font-medium text-white transition shadow-lg shadow-rose-600/25">
                            Dispatch Representment Claim
                        </button>
                    </div>

                    <div class="bg-slate-950/80 border border-slate-800 rounded-xl p-5 flex flex-col justify-between text-xs">
                        <div class="space-y-3">
                            <div class="flex items-center justify-between pb-3 border-b border-slate-800 text-[11px] font-mono">
                                <span class="text-slate-400">ARBITRATION_VERDICT</span>
                                <span id="dispStatusBadge" class="text-slate-500 font-bold">READY</span>
                            </div>
                            <div id="dispDetails" class="text-slate-400 leading-relaxed">
                                Awaiting evidence submission...
                            </div>
                        </div>
                        <div class="pt-3 border-t border-slate-900 text-[10px] text-slate-500 font-mono flex justify-between">
                            <span>Mastercard Claims Portal</span>
                            <span>TAT: 30-Day Window</span>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Tab 4: Webhooks -->
            <div id="t-webhook" class="p-6 hidden">
                <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
                    <div class="space-y-4 text-xs">
                        <div class="flex items-center justify-between pb-2 border-b border-slate-800">
                            <h3 class="text-sm font-semibold text-white">Webhook HMAC SHA-256 Verifier</h3>
                            <span class="text-slate-400 font-mono text-[11px]">POST /webhooks/dispatch</span>
                        </div>
                        <p class="text-slate-400 leading-relaxed">
                            Fuze webhooks send an <code class="text-cyan-400">X-Signature</code> header generated by HMAC-SHA256 with the endpoint signature key.
                        </p>
                        <button onclick="triggerWebhook()" class="w-full py-2.5 rounded-xl bg-violet-600 hover:bg-violet-500 font-medium text-white transition shadow-lg shadow-violet-600/25">
                            Simulate Webhook Dispatch & Validate X-Signature
                        </button>
                    </div>

                    <div class="bg-slate-950/80 border border-slate-800 rounded-xl p-4 font-mono text-xs">
                        <div class="text-[11px] text-slate-400 pb-2 border-b border-slate-800">DISPATCHED_WEBHOOK_EVENT</div>
                        <pre id="webhookOutput" class="mt-3 text-violet-300 whitespace-pre-wrap text-[11px] overflow-x-auto">Click simulate to inspect HMAC signature and payload...</pre>
                    </div>
                </div>
            </div>
        </div>

        <!-- Live Double-Entry Ledger Stream -->
        <div class="bg-[#111827] border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
            <div class="flex items-center justify-between">
                <div>
                    <h3 class="text-sm font-semibold text-white">Live Double-Entry Transaction Ledger</h3>
                    <p class="text-xs text-slate-400">Persistent SQLite journal recording real-time authorizations, surcharges, and clearing states.</p>
                </div>
                <button onclick="loadLedger()" class="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-mono text-slate-300 transition">
                    ↻ Refresh Stream
                </button>
            </div>

            <div class="overflow-x-auto">
                <table class="w-full text-left text-xs font-mono">
                    <thead class="bg-slate-900/60 text-slate-400 border-b border-slate-800">
                        <tr>
                            <th class="p-3">REF NUMBER</th>
                            <th class="p-3">TIMESTAMP</th>
                            <th class="p-3">SOURCE METHOD</th>
                            <th class="p-3">AMOUNT (USD)</th>
                            <th class="p-3">CARD</th>
                            <th class="p-3">AUTH CODE</th>
                            <th class="p-3">ECI</th>
                            <th class="p-3">STATUS</th>
                        </tr>
                    </thead>
                    <tbody id="ledgerRows" class="divide-y divide-slate-800/60 text-slate-300">
                        <tr>
                            <td colspan="8" class="p-4 text-center text-slate-500">Loading live ledger stream...</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    </main>

    <script>
        function tabSwitch(tab) {
            ['charge', 'clearing', 'dispute', 'webhook'].forEach(t => {
                document.getElementById('t-' + t).classList.add('hidden');
                document.getElementById('btn-' + t).className = 'pb-3 text-slate-400 hover:text-slate-200 transition';
            });
            document.getElementById('t-' + tab).classList.remove('hidden');
            document.getElementById('btn-' + tab).className = 'pb-3 text-cyan-400 border-b-2 border-cyan-500 font-semibold transition';
        }

        function highlightPipeline(nodes, success) {
            ['client', 'token', 'switch', 'acquirer', 'scheme', 'issuer'].forEach(n => {
                document.getElementById('p-' + n).className = 'bg-slate-900/90 border border-slate-800 rounded-xl p-3 text-center transition-all';
            });
            nodes.forEach(n => {
                const el = document.getElementById('p-' + n);
                el.className = success 
                    ? 'bg-cyan-950/70 border border-cyan-500 rounded-xl p-3 text-center shadow-lg shadow-cyan-500/20'
                    : 'bg-rose-950/70 border border-rose-500 rounded-xl p-3 text-center shadow-lg shadow-rose-500/20';
            });
        }

        async function executeCharge() {
            const src = document.getElementById('chargeSource').value;
            const amt = parseFloat(document.getElementById('chargeAmt').value);
            const bin = document.getElementById('chargeBin').value;
            const fail = document.getElementById('chargeSimFail').checked;
            const out = document.getElementById('chargeOutput');
            const badge = document.getElementById('chargeStatusBadge');
            const topo = document.getElementById('topoState');

            badge.innerText = 'SWITCHING...';
            badge.className = 'text-cyan-400 font-bold';
            topo.innerText = 'STATUS: ROUTING API V2 PAYLOAD';

            try {
                const res = await fetch('/api/v2/transactions/charge', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        amount: amt,
                        source: src,
                        bin_type: bin,
                        simulate_failure: fail,
                        '3d_secure': { eci: '05', cavv: 'AAABBIIFmQAAAAAJUGFmAAAAAAA=' }
                    })
                });
                const d = await res.json();
                out.innerText = JSON.stringify(d, null, 2);
                badge.innerText = d.status;
                badge.className = d.status === 'Approved' ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold';
                topo.innerText = 'STATUS: ' + d.status;
                
                if (d.status === 'Approved') {
                    highlightPipeline(['client', 'token', 'switch', 'acquirer', 'scheme', 'issuer'], true);
                } else {
                    highlightPipeline(['client', 'token', 'switch'], false);
                }
                loadLedger();
            } catch(e) {
                out.innerText = 'Error: ' + e;
            }
        }

        async function auditIPM() {
            const badge = document.getElementById('ipmBadge');
            badge.innerText = 'AUDITED (MATCHED)';
            badge.className = 'text-emerald-400 font-bold font-mono';
            highlightPipeline(['acquirer', 'scheme', 'issuer'], true);
        }

        async function submitDispute() {
            const reason = document.getElementById('dispReason').value;
            const eci = document.getElementById('dispEci').value;
            const pod = document.getElementById('dispPod').value;
            const badge = document.getElementById('dispStatusBadge');
            const det = document.getElementById('dispDetails');

            try {
                const res = await fetch('/api/v2/dispute/rebuttal', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        dispute_id: 'DISP_9948201',
                        reference_number: 994820194,
                        reason_code: reason,
                        eci_flag: eci,
                        pod_tracking_number: pod,
                        compelling_evidence_notes: 'Valid signed POD and 3DS authentication cryptogram attached.'
                    })
                });
                const d = await res.json();
                badge.innerText = d.status;
                badge.className = d.liability_shift ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold';
                det.innerText = d.arbitration_outcome;
            } catch(e) {
                det.innerText = 'Error: ' + e;
            }
        }

        async function triggerWebhook() {
            const out = document.getElementById('webhookOutput');
            try {
                const res = await fetch('/api/v2/webhooks/dispatch', { method: 'POST' });
                const d = await res.json();
                out.innerText = JSON.stringify(d, null, 2);
            } catch(e) {
                out.innerText = 'Error: ' + e;
            }
        }

        async function loadLedger() {
            const tbody = document.getElementById('ledgerRows');
            try {
                const res = await fetch('/api/v2/ledger/stream');
                const rows = await res.json();
                if (rows.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="8" class="p-4 text-center text-slate-500">No transactions recorded. Execute a charge request above.</td></tr>';
                    return;
                }
                tbody.innerHTML = rows.map(r => `
                    <tr class="hover:bg-slate-900/50 transition">
                        <td class="p-3 text-cyan-400 font-semibold">${r.ref_no}</td>
                        <td class="p-3 text-slate-400 text-[11px]">${r.timestamp}</td>
                        <td class="p-3 text-slate-300">${r.source}</td>
                        <td class="p-3 font-semibold text-emerald-400">$${r.amount.toFixed(2)}</td>
                        <td class="p-3 text-slate-400 font-mono">•••• ${r.last4}</td>
                        <td class="p-3 text-slate-300 font-mono">${r.auth_code}</td>
                        <td class="p-3"><span class="px-2 py-0.5 rounded bg-cyan-950 text-cyan-400 border border-cyan-800 text-[10px]">ECI ${r.eci}</span></td>
                        <td class="p-3"><span class="text-emerald-400 font-bold">${r.status}</span></td>
                    </tr>
                `).join('');
            } catch(e) {
                console.error(e);
            }
        }

        window.onload = loadLedger;
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def root():
    return DASHBOARD_UI
