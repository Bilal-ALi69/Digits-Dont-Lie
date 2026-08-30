# Digits Dont Lie

A Researchathon project combining statistical analysis (Benford's Law), credit card validation (Luhn + network detection), OCR document ingestion, financial arithmetic verification, and AI-powered classification into a full-stack fraud detection application.

## What It Does

| Capability | Engine | Description |
|---|---|---|
| **Benford's Law analysis** | `benford.py` | Chi-square goodness-of-fit test on leading-digit distributions (1-digit and 2-digit). Correct p-value via regularized incomplete gamma function. Detects statistical anomalies that suggest fabricated or manipulated data. |
| **Credit card validation** | `engines/card.py` | Luhn checksum, card network detection (Visa, Mastercard, Amex, Discover, Diners, JCB, UnionPay, Maestro), format/length checks. |
| **Input classification** | `engines/classifier.py` | Dual-layer classification: determines both the **value type** (card number, financial amount, date, ID, invoice number, etc.) and the **document type** (credit card, invoice, bank statement, passport, etc.). |
| **OCR ingestion** | `ocr.py` | Multi-variant Tesseract OCR with image preprocessing. Extracts card numbers from images with variant consensus scoring. |
| **File ingestion** | `ingestion/` | Reads CSV, XLSX, and PDF (including OCR fallback for scanned PDFs). Detects numeric columns and date columns. |
| **Financial arithmetic** | `engines/financial.py` | Verifies invoice subtotal/total consistency and bank balance arithmetic. |
| **Document arithmetic verification** | `engines/invoice.py` | Reads labeled amounts (subtotal, tax, discount, total, opening/closing balance, credits, debits) off an invoice, receipt or bank statement and checks that the document's own figures reconcile. Works on a single document, where Benford's Law cannot apply. |
| **Risk assessment** | `engines/risk.py` | Aggregates evidence from all checks into a 0-100 risk score with confidence and level. |
| **AI explanations** | `engines/groq_client.py` | Optional Groq-powered natural-language explanations. Falls back gracefully if Groq is unavailable. |

---

## Project Structure

```
Digits_Dont_Lie/
├── README.md
├── .gitignore
├── scripts/                     ← cross-platform setup (see Quick Start)
├── Backend/
│   ├── .env                     ← secrets (git-ignored)
│   ├── .env.example             ← template for .env
│   ├── DEPLOYMENT.md            ← production deployment guide
│   ├── requirements.txt         ← Python dependencies
│   ├── app/
│   │   ├── api/server.py        ← FastAPI app, all endpoints
│   │   ├── engines/             ← card, classifier, financial, risk, groq
│   │   ├── ingestion/           ← CSV, XLSX, PDF readers
│   │   ├── benford.py           ← Benford's Law core statistics
│   │   ├── models.py            ← Pydantic models & enums
│   │   ├── orchestrator.py      ← unified analysis router
│   │   └── ...
│   └── tests/                   ← 521 passing tests
└── Frontend/
    ├── app/                     ← Next.js App Router
    │   └── api/                 ← Server-side proxy routes (hold BACKEND_API_KEY)
    ├── components/verifier/     ← UI components
    ├── lib/
    │   ├── api.ts               ← Calls this app's own /api/* routes
    │   ├── backend.ts           ← Server-only: real backend URL + API key
    │   └── verifier.ts          ← Client-side fallback engine
    └── package.json
```

---

## Quick Start

### Automatic setup (recommended)

One command on any supported OS. It detects the operating system and package
manager, installs Python, Node and Tesseract if they are missing, builds the
virtualenv, installs both dependency trees, and generates matching API keys
for the backend and the frontend proxy.

```bash
python3 scripts/setup.py             # Linux, macOS
```

```bat
scripts\setup.bat                    :: Windows (or double-click it)
```

| Flag | Effect |
|---|---|
| `--check` | Report what is missing and change nothing |
| `--update` | Upgrade an existing install instead of creating one |
| `--skip-system` | Skip system packages, so no sudo or admin prompt |
| `--verbose` | Show the full output of every command |
| `--yes` | Do not pause for confirmation |

`setup.py` uses only the Python standard library, because it is the program
that runs before anything has been installed. It dispatches to the script for
the detected platform:

```
scripts/
├── setup.py            entry point: detection, terminal UI, dispatch
├── setup_linux.sh      pacman / apt / dnf / zypper / apk
├── setup_macos.sh      Homebrew
├── setup_windows.ps1   winget / Chocolatey
├── setup.bat           Windows double-click wrapper
├── lib_unix.sh         steps shared by Linux and macOS
└── init_env.py         creates .env files, keeps the two API keys matched
```

The platform scripts print a small marker protocol (`::step`, `::ok`, `::fail`,
`::warn`) that `setup.py` renders as a live progress view. They also run
standalone, if you would rather see the raw output:

```bash
bash scripts/setup_linux.sh install
```

Nothing here overwrites a value you have already set. Re-running setup on a
machine with a working `GROQ_API_KEY` leaves it alone.

### Manual setup

#### Backend

```bash
cd Backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # edit and set API_KEY
uvicorn app.api.server:app --reload --host 0.0.0.0 --port 8000
```

#### Frontend

```bash
cd Frontend
npm install          # or pnpm install
cp .env.local.example .env.local   # set BACKEND_URL and BACKEND_API_KEY
npm run dev          # http://localhost:3000
```

The frontend never talks to the FastAPI backend directly from the browser — `lib/api.ts` calls this app's own `/api/*` route handlers (`app/api/**/route.ts`), which hold `BACKEND_URL`/`BACKEND_API_KEY` server-side and proxy the request through. This keeps the shared API key out of the client JS bundle.

The frontend auto-detects whether the backend is running. When the backend is offline, it falls back to client-side analysis. When connected, it uses the full FastAPI engine with OCR, Benford chi-square tests, and Groq-powered explanations.

---

## API Endpoints

All endpoints except `/api/health` require an `X-API-Key` header.

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Server status, version, available engines |
| `POST` | `/api/classify` | Classify a value (returns candidates + `classification_id`) |
| `POST` | `/api/analyze` | Full analysis of a value, dataset, or text |
| `POST` | `/api/analyze/upload` | Upload a file (.csv, .xlsx, .pdf, .jpg, .png) for analysis |

---

## How It Works

### Benford's Law
In naturally occurring datasets, the leading digit **1 appears ~30.1%** of the time, while 9 appears less than 5%. This follows P(d) = log₁₀(1 + 1/d). Fabricated numbers tend toward uniform digit distribution. A chi-square goodness-of-fit test flags datasets that deviate significantly from the expected Benford distribution.

### Luhn Algorithm (Mod-10)
Developed by IBM in 1954, the Luhn algorithm is a checksum that validates credit card numbers, IMEI numbers, and other identification schemes. Every major card network (Visa, Mastercard, Amex, Discover) uses Luhn as the final digit check. A failing Luhn checksum means the number is mathematically invalid.

### Document Arithmetic Verification

An invoice or bank statement carries its own proof: the line items must sum to
the subtotal, and the subtotal plus tax minus discount must equal the total. A
document that contradicts itself is fraudulent regardless of how it looks. This
check needs no external database and no sample size, so it works on a single
photographed receipt - the case Benford's Law cannot address.

Because a photograph is read by OCR, a mismatch has two possible causes: the
document is inconsistent, or the camera reading was wrong. The system separates
them by OCR **corroboration** - the same page is read several times through
different preprocessing, and a mismatch may only produce a fraud verdict when
every figure it depends on was read identically by independent passes. An
unreliable reading is reported as `REQUIRES_REVIEW` in both directions: it may
neither accuse a document nor clear one.

Corroboration guards against misreading, not against misparsing. A figure that
every pass reads the same way but the parser interprets wrongly (an invoice's
`Tax (10%)  65.00` yielding the rate instead of the amount) passes corroboration
while being wrong, so parsing rules carry their own regression tests.

### Card Network Detection
The first 6–8 digits (IIN/BIN) identify the issuing network: Visa (4*), Mastercard (51–55, 2221–2720), Amex (34/37), Discover (6011, 644–649, 65). Combined with expected length, this creates a structural fingerprint.

---

## Development History

`docs/DEVELOPMENT_LOG.md` is the engineering record of how this system was
built: what was added in each phase, which bugs were found and why their causes
were non-obvious, and the reasoning behind the core design decisions.

Two sections are worth reading before changing anything substantial:

- **Decision Record** — why the system can prove invalid but never authentic,
  why AI extracts but never judges, why Benford is scoped rather than removed,
  and why risk and confidence are separate measurements.
- **Bugs Worth Remembering** — failures that a well-meaning cleanup would
  reintroduce, including two CSS rules whose *correct* form looks wrong.

---

## Running Tests

```bash
cd Backend
pytest tests/ -v            # full suite (521 tests)
pytest tests/test_benford.py # Benford-specific tests
pytest -x                   # stop on first failure
```

---

## Tech Stack

- **Backend**: Python 3.11+, FastAPI, Pydantic, Tesseract OCR, PyMuPDF
- **Frontend**: Next.js 16, React 19, TypeScript, Tailwind CSS, shadcn/ui
- **AI** (optional): Groq API (Llama 3)

---

## License

Researchathon project — for educational and research purposes.
