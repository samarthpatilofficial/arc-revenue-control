# ARC Demo Runbook

This runbook prepares the persisted, read-only ARC demonstration on Windows. The presentation uses one evidence-backed Razorpay Test Mode recovery plus three controlled offline scenarios. It does not require Razorpay or OpenAI network access during the walkthrough.

## 1. Open the project and activate Python

In Windows PowerShell:

```powershell
Set-Location "<path-to>\arc-revenue-control"
.\.venv\Scripts\Activate.ps1
```

Keep the private root `.env` configured for the ARC development database. Do not display its contents during recording.

## 2. Ensure PostgreSQL is running

For a native PostgreSQL installation:

```powershell
$postgres = Get-Service -Name "postgresql*" | Select-Object -First 1
if ($null -eq $postgres) { throw "PostgreSQL service was not found" }
if ($postgres.Status -ne "Running") { Start-Service -InputObject $postgres }
$postgres | Select-Object Name, Status
```

If this machine uses the optional Compose service instead:

```powershell
docker compose up -d postgres
```

## 3. Seed controlled scenarios only if necessary

The seeder is idempotent and creates only the three reserved synthetic scenarios. It does not create a Payment Link or call Razorpay/OpenAI.

```powershell
$env:ARC_DEMO_MODE = "true"
python -m scripts.seed_demo
Remove-Item Env:ARC_DEMO_MODE
```

## 4. Run the deterministic preflight

```powershell
python -m scripts.demo_preflight
```

Expected final line:

```text
DEMO STATUS: READY
```

Do not start recording while the status is `NOT READY`; the preceding check identifies the missing persisted evidence or scenario.

## 5. Start the backend

```powershell
python -m uvicorn services.api.main:app --reload
```

The backend listens on `http://localhost:8000`. For the frontend development origin, the private root `.env` should contain:

```dotenv
CORS_ALLOWED_ORIGINS=["http://localhost:5173"]
```

## 6. Start the frontend

Open a second PowerShell terminal:

```powershell
Set-Location "<path-to>\arc-revenue-control\frontend"
npm run dev
```

Open:

```text
http://localhost:5173
```

## 7. Five-minute operator click path

### 0:00–0:30 — Overview

Establish the payment-recovery problem, evidence-scoped metrics, and the control loop. Point out that AI appears only in `Decide`, while policy owns authorization and provider evidence owns outcome truth.

### 0:30–1:45 — Genuine Test Mode recovery

Open **Recovery verified** from **Demo recovery stories**. Show:

- the original failure and diagnosis;
- bounded recovery strategy;
- deterministic policy authorization;
- governed execution;
- Razorpay Test Mode provider evidence;
- evidence-backed revenue attribution.

### 1:45–2:40 — High-value approval

Return to Overview and open **Human approval required**. Show:

- the bounded AI proposal;
- `Requires approval` policy result;
- pending human approval;
- the absence of approval or execution controls in this read-only build.

### 2:40–3:20 — Already-captured protection

Open **Duplicate recovery prevented**. Show:

- authoritative reconciliation;
- recovered current truth;
- no strategy, recovery execution, or ARC attribution;
- the avoided unnecessary action.

### 3:20–4:00 — Hard stop

Open **Automation stopped safely**. Show:

- deterministic attempt-limit enforcement;
- terminal exhausted state;
- no external recovery action.

### 4:00–4:35 — Operational controls

Visit **Approvals**, **Recovery Actions**, and **Decision Audit** to show human authority, governed execution records, and traceability.

### 4:35–5:00 — Close on Overview

Return to Overview and close with:

> AI proposes.\
> Policy authorizes.\
> The executor acts.\
> Provider evidence proves recovery.

## Recording safety

- `TEST MODE` is not live money.
- `SYNTHETIC DEMO` is a controlled offline scenario, not provider evidence.
- Do not display `.env`, terminal history containing credentials, Payment Link URLs, or provider/customer identifiers.
- The console is read-only: do not create, capture, refund, approve, reject, or execute payments during the walkthrough.
- No external Razorpay or OpenAI request is needed once the persisted preflight is ready.
