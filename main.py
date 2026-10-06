import os
import sqlite3
import datetime
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="Fuze Payment Gateway Operations Console")

# --- SQLite Database Initialization ---
DB_PATH = "pg_ops_ledger.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
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

# --- Request Models ---
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

# --- Clean Embedded Dashboard UI ---
DASHBOARD_HTML = r"""<!DOCTYPE html>
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
    </style>
</head>
<body class="bg-[#0B0F17] text-slate-100 min-h-screen antialiased flex flex-col">

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

    <main class="flex-1 max-w-7xl w-full mx-auto px-6 py-6 space-y-6">

        <div class="bg-gradient-to-b from-[#111827] to-[#0D131F] border border-slate-800 rounded-2xl p-6 shadow-xl relative overflow-hidden">
            <div class="flex items-center justify-between mb-4">
                <div class="flex items-center gap-2">
                    <span class="text-xs font-semibold uppercase tracking-wider text-indigo-400">Live Dual-Message Switch Topology</span>
                </div>
                <div id="topologyStatus" class="text-xs font-mono text-slate-400">STATUS: IDLE</div>
            </div>

            <div class="grid grid-cols-5 gap-3 relative z-10">
                <div id="node-client" class="bg-slate-900/90 border border-slate-800 rounded-xl p-3.5 text-center transition-all duration-300">
                    <div class="text-[10px] text-slate-400 font-mono mb-1">ORIGIN</div>
                    <div class="text-xs font-bold text-slate-200">Customer App</div>
                    <div class="text-[10px] text-slate-500 mt-0.5">3DS2 SDK / Web</div>
                </div>
                <div id="node-mpgs" class="bg-slate-900/90 border border-slate-800 rounded-xl p-3.5 text-center transition-all duration-300">
                    <div class="text-[10px] text-indigo-400 font-mono mb-1">GATEWAY</div>
                    <div class="text-xs font-bold text-white">MPGS Switch</div>
                    <div class="text-[10px] text-slate-400 mt-0.5">Token / Risk Check</div>
                </div>
                <div id="node-acquirer" class="bg-slate-900/90 border border-slate-800 rounded-xl p-3.5 text-center transition-all duration-300">
                    <div class="text-[10px] text-slate-400 font-mono mb-1">ACQUIRER</div>
                    <div class="text-xs font-bold text-slate-200">Acquirer Bank</div>
                    <div class="text-[10px] text-slate-500 mt-0.5">MID / TID Host</div>
                </div>
                <div id="node-scheme" class="bg-slate-900/90 border border-slate-800 rounded-xl p-3.5 text-center transition-all duration-300">
                    <div class="text-[10px] text-amber-400 font-mono mb-1">SCHEME</div>
                    <div class="text-xs font-bold text-white">Mastercard Rail</div>
                    <div class="text-[10px] text-slate-400 mt-0.5">Dual-Message ISO</div>
                </div>
                <div id="node-issuer" class="bg-slate-900/90 border border-slate-800 rounded-xl p-3.5 text-center transition-all duration-300">
                    <div class="text-[10px] text-slate-400 font-mono mb-1">ISSUER</div>
                    <div class="text-xs font-bold text-slate-200">Issuer Bank</div>
                    <div class="text-[10px] text-slate-500 mt-0.5">Auth / Lien Hold</div>
                </div>
            </div>
        </div>

        <div class="bg-[#111827] border border-slate-800 rounded-2xl shadow-xl overflow-hidden">
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

                    <div class="bg-slate-950/80 border border-slate-800 rounded-xl p-4 flex flex-col justify-between font-mono text-xs">
                        <div>
                            <div class="flex items-center justify-between pb-3 border-b border-slate-800 text-[11px] text-slate-400">
                                <span>SWITCH_RESPONSE_STREAM</span>
                                <span id="authBadge" class="text-slate-500 font-bold">READY</span>
                            </div>
                            <pre id="authResult" class="mt-3 text-slate-400 whitespace-pre-wrap leading-relaxed text-[11px]">Click "Execute Authorisation Request" to send ISO 8583 payload.</pre>
                        </div>
                        <div class="pt-3 border-t border-slate-900 text-[10px] text-slate-500 flex justify-between">
                            <span>ISO 8583 0100 / 0110</span>
                            <span>MPGS API v72</span>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Tab 2: IPM Clearing -->
            <div id="tab-clearing" class="p-6 hidden">
                <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
                    <div class="space-y-4">
                        <h3 class="text-sm font-semibold text-white">Mastercard IPM EOD File Audit</h3>
                        <p class="text-xs text-slate-400">Parse daily clearing presentment records (PDS-0200) and calculate net merchant settlements.</p>
                        
                        <div>
                            <label class="block text-xs font-medium text-slate-400 mb-1">Raw IPM Presentment Data (.DAT)</label>
                            <textarea id="ipmText" rows="4" class="w-full bg-slate-900 border border-slate-800 rounded-xl p-3 text-xs text-slate-200 font-mono leading-relaxed">REC_PDS0200|MC_DUAL_MSG|MID_8849201|AUTH_184.00|USD|ECI_05|RRN_392019481029|MCC_5411</textarea>
                        </div>

                        <button onclick="runIPM()" class="w-full py-2.5 rounded-xl bg-amber-600 hover:bg-amber-500 text-white font-medium text-xs shadow-lg shadow-amber-600/25 transition">
                            Audit & Reconcile IPM Batch
                        </button>
                    </div>

                    <div class="bg-slate-950/80 border border-slate-800 rounded-xl p-4 flex flex-col justify-between text-xs">
                        <div class="space-y-3">
                            <div class="flex items-center justify-between pb-3 border-b border-slate-800 text-[11px] font-mono text-slate-400">
                                <span>SETTLEMENT_BREAKDOWN</span>
                                <span id="ipmBadge" class="text-amber-400 font-bold">UNAUDITED</span>
                            </div>
                            <div id="ipmOutput" class="space-y-2 text-slate-300">
                                <div class="flex justify-between py-1 border-b border-slate-900">
                                    <span class="text-slate-400">Gross Presentment:</span>
                                    <span class="font-mono">$0.00</span>
                                </div>
                                <div class="flex justify-between py-1 border-b border-slate-900">
                                    <span class="text-slate-400">Interchange Fee (Issuer):</span>
                                    <span class="font-mono text-rose-400">$0.00</span>
                                </div>
                                <div class="flex justify-between py-1 border-b border-slate-900">
                                    <span class="text-slate-400">Scheme Assessment (MC):</span>
                                    <span class="font-mono text-rose-400">$0.00</span>
                                </div>
                                <div class="flex justify-between py-1 font-semibold text-white">
                                    <span>Net Merchant Payout:</span>
                                    <span class="font-mono text-emerald-400 text-sm">$0.00</span>
                                </div>
                            </div>
                        </div>
                        <div class="pt-3 border-t border-slate-900 text-[10px] text-slate-500 font-mono">
                            Reconciliation Status: Ready
                        </div>
                    </div>
                </div>
            </div>

            <!-- Tab 3: Dispute Desk -->
            <div id="tab-dispute" class="p-6 hidden">
                <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
                    <div class="space-y-4">
                        <h3 class="text-sm font-semibold text-white">Representment & Arbitration Filing</h3>
                        <p class="text-xs text-slate-400">Execute automated liability shift checks under Mastercard chargeback rules.</p>
                        
                        <div class="grid grid-cols-2 gap-3">
                            <div>
                                <label class="block text-xs font-medium text-slate-400 mb-1">Reason Code</label>
                                <select id="dispReason" class="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-200">
                                    <option value="4837">4837 (Fraud / Unauthorized)</option>
                                    <option value="4853">4853 (Service Not Rendered)</option>
                                </select>
                            </div>
                            <div>
                                <label class="block text-xs font-medium text-slate-400 mb-1">3DS ECI Flag</label>
                                <select id="dispEci" class="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-200">
                                    <option value="05">ECI 05 (Full 3DS Success)</option>
                                    <option value="02">ECI 02 (Scheme Half-Auth)</option>
                                    <option value="07">ECI 07 (No 3DS / Fallback)</option>
                                </select>
                            </div>
                        </div>

                        <div>
                            <label class="block text-xs font-medium text-slate-400 mb-1">Courier POD / Tracking Number</label>
                            <input type="text" id="dispPod" value="BLUEDART_POD_9948201_SIGNED" class="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-200 font-mono">
                        </div>

                        <button onclick="runDispute()" class="w-full py-2.5 rounded-xl bg-rose-600 hover:bg-rose-500 text-white font-medium text-xs shadow-lg shadow-rose-600/25 transition">
                            Dispatch Representment to Scheme
                        </button>
                    </div>

                    <div class="bg-slate-950/80 border border-slate-800 rounded-xl p-5 flex flex-col justify-between text-xs">
                        <div class="space-y-3">
                            <div class="flex items-center justify-between pb-3 border-b border-slate-800 text-[11px] font-mono text-slate-400">
                                <span>ARBITRATION_VERDICT</span>
                                <span id="dispBadge" class="text-slate-500 font-bold">READY</span>
                            </div>
                            <div id="dispDetails" class="text-slate-400 leading-relaxed text-xs">
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
        </div>

        <div class="bg-[#111827] border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
            <div class="flex items-center justify-between">
                <div>
                    <h3 class="text-sm font-semibold text-white">Live Double-Entry Operations Ledger</h3>
                    <p class="text-xs text-slate-400">Real-time lien holds, auth clearances, and settlement balances recorded in SQLite.</p>
                </div>
                <button onclick="loadLedger()" class="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-mono text-slate-300 transition">
                    ↻ Refresh Ledger
                </button>
            </div>

            <div class="overflow-x-auto">
                <table class="w-full text-left text-xs font-mono">
                    <thead class="bg-slate-900/60 text-slate-400 border-b border-slate-800">
                        <tr>
                            <th class="p-3">TXN ID</th>
                            <th class="p-3">TIMESTAMP</th>
                            <th class="p-3">DEBITED</th>
                            <th class="p-3">CREDITED</th>
                            <th class="p-3">AMOUNT</th>
                            <th class="p-3">STAGE</th>
                            <th class="p-3">STATUS</th>
                        </tr>
                    </thead>
                    <tbody id="ledgerRows" class="divide-y divide-slate-800/60 text-slate-300">
                        <tr>
                            <td colspan="7" class="p-4 text-center text-slate-500">Loading ledger state...</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    </main>

    <script>
        function switchTab(tab) {
            ['auth', 'clearing', 'dispute'].forEach(t => {
                document.getElementById('tab-' + t).classList.add('hidden');
                const btn = document.getElementById('tab-btn-' + t);
                btn.className = 'pb-3 text-slate-400 hover:text-slate-200 transition';
            });
            document.getElementById('tab-' + tab).classList.remove('hidden');
            document.getElementById('tab-btn-' + tab).className = 'pb-3 text-indigo-400 border-b-2 border-indigo-500 font-semibold transition';
        }

        function resetNodes() {
            ['client', 'mpgs', 'acquirer', 'scheme', 'issuer'].forEach(id => {
                const el = document.getElementById('node-' + id);
                el.className = 'bg-slate-900/90 border border-slate-800 rounded-xl p-3.5 text-center transition-all duration-300';
            });
        }

        function highlightNodes(nodes, status) {
            resetNodes();
            nodes.forEach(id => {
                const el = document.getElementById('node-' + id);
                if (status === 'APPROVED') {
                    el.className = 'bg-indigo-950/70 border border-indigo-500 rounded-xl p-3.5 text-center shadow-lg shadow-indigo-500/20';
                } else {
                    el.className = 'bg-rose-950/70 border border-rose-500 rounded-xl p-3.5 text-center shadow-lg shadow-rose-500/20';
                }
            });
        }

        async function runAuth() {
            const mode = document.getElementById('authMode').value;
            const amt = parseFloat(document.getElementById('authAmt').value);
            const drop = document.getElementById('authSimDrop').checked;
            const badge = document.getElementById('authBadge');
            const out = document.getElementById('authResult');
            const topo = document.getElementById('topologyStatus');

            badge.innerText = 'SWITCHING...';
            badge.className = 'text-indigo-400 font-bold';
            topo.innerText = 'STATUS: ROUTING ISO PAYLOAD';

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
                const d = await res.json();
                out.innerText = JSON.stringify(d, null, 2);
                badge.innerText = d.status;
                badge.className = d.status === 'APPROVED' ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold';
                topo.innerText = 'STATUS: ' + d.status;
                highlightNodes(d.pipeline_nodes, d.status);
                loadLedger();
            } catch(e) {
                out.innerText = 'Error: ' + e;
            }
        }

        async function runIPM() {
            const raw = document.getElementById('ipmText').value;
            const badge = document.getElementById('ipmBadge');
            const out = document.getElementById('ipmOutput');
            
            try {
                const res = await fetch('/api/v1/clearing/parse-ipm', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ raw_ipm_record: raw })
                });
                const d = await res.json();
                badge.innerText = 'AUDITED (MATCHED)';
                badge.className = 'text-emerald-400 font-bold';
                out.innerHTML = `
                    <div class="flex justify-between py-1 border-b border-slate-900">
                        <span class="text-slate-400">Gross Presentment:</span>
                        <span class="font-mono text-white">${d.gross_amount}</span>
                    </div>
                    <div class="flex justify-between py-1 border-b border-slate-900">
                        <span class="text-slate-400">Interchange Fee (Issuer):</span>
                        <span class="font-mono text-rose-400">${d.interchange}</span>
                    </div>
                    <div class="flex justify-between py-1 border-b border-slate-900">
                        <span class="text-slate-400">Scheme Assessment (MC):</span>
                        <span class="font-mono text-rose-400">${d.scheme_fee}</span>
                    </div>
                    <div class="flex justify-between py-1 font-semibold text-white">
                        <span>Net Merchant Payout:</span>
                        <span class="font-mono text-emerald-400 text-sm">${d.net_payout}</span>
                    </div>
                `;
            } catch(e) {
                alert('Error parsing IPM: ' + e);
            }
        }

        async function runDispute() {
            const reason = document.getElementById('dispReason').value;
            const eci = document.getElementById('dispEci').value;
            const pod = document.getElementById('dispPod').value;
            const badge = document.getElementById('dispBadge');
            const det = document.getElementById('dispDetails');

            try {
                const res = await fetch('/api/v1/dispute/representment', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        dispute_id: 'DSP_881920',
                        reason_code: reason,
                        eci_flag: eci,
                        pod_reference: pod,
                        merchant_notes: 'Proof attached'
                    })
                });
                const d = await res.json();
                badge.innerText = d.outcome;
                badge.className = d.badge + ' px-2 py-0.5 rounded font-bold';
                det.innerText = d.details;
            } catch(e) {
                alert('Error: ' + e);
            }
        }

        async function loadLedger() {
            const tbody = document.getElementById('ledgerRows');
            try {
                const res = await fetch('/api/v1/ledger/recent');
                const rows = await res.json();
                if (rows.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="7" class="p-4 text-center text-slate-500">No transactions recorded yet.</td></tr>';
                    return;
                }
                tbody.innerHTML = rows.map(r => `
                    <tr class="hover:bg-slate-900/40 transition">
                        <td class="p-3 text-indigo-400 font-semibold">${r.txn_id}</td>
                        <td class="p-3 text-slate-400 text-[11px]">${r.timestamp}</td>
                        <td class="p-3 text-slate-300">${r.debited}</td>
                        <td class="p-3 text-slate-300">${r.credited}</td>
                        <td class="p-3 font-semibold text-emerald-400">$${r.amount.toFixed(2)}</td>
                        <td class="p-3"><span class="px-2 py-0.5 rounded bg-slate-800 text-[10px] text-slate-300">${r.stage}</span></td>
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

# --- Endpoints ---
@app.get("/", response_class=HTMLResponse)
def index():
    return DASHBOARD_HTML

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
    
    conn = sqlite3.connect(DB_PATH)
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
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT txn_id, timestamp, account_debited, account_credited, amount, currency, lifecycle_stage, status FROM ledger_entries ORDER BY id DESC LIMIT 5")
    rows = cursor.fetchall()
    conn.close()
    return [{"txn_id": r[0], "timestamp": r[1], "debited": r[2], "credited": r[3], "amount": r[4], "currency": r[5], "stage": r[6], "status": r[7]} for r in rows]
