# Portable copy — read this first

This archive is the whole project, minus everything a computer has to build for
itself. There is no `.venv`, no `node_modules`, no `.next` build. Those are
compiled for one operating system and one CPU, so copying them from another
machine gives you a broken install, not a portable one. The setup script below
rebuilds them natively in about a minute.

## On the new device

Unzip anywhere — a USB stick, Desktop, wherever — then:

**Linux / macOS**

```bash
cd Digits_Dont_Lie
python3 scripts/setup.py        # installs everything
./scripts/run.sh                # starts both servers
```

**Windows**

```bat
cd Digits_Dont_Lie
scripts\setup.bat               :: installs everything (or double-click it)
scripts\run.bat                 :: starts both servers (or double-click it)
```

Then open <http://localhost:3000>.

`Ctrl+C` stops both servers.

## What setup needs

An internet connection the first time, to download the Python and Node
packages. After that it runs offline, apart from the optional Groq AI
explanations, which call an external API.

`setup.py` installs Python 3.11+, Node 20+ and Tesseract OCR if they are
missing, which needs an administrator password. To skip that and use only what
is already on the machine:

```bash
python3 scripts/setup.py --skip-system
```

Other flags: `--check` (report what is missing, change nothing), `--update`
(upgrade an existing install), `--verbose`, `--yes`.

## Running it

| Command | Use |
|---|---|
| `python3 scripts/run.py` | Production build. **Use this to demo** — pages are compiled ahead of time and open instantly. |
| `python3 scripts/run.py --dev` | Dev server with hot reload, for editing code. |
| `python3 scripts/run.py --rebuild` | Force a fresh production build first, after changing frontend code. |
| `python3 scripts/run.py --backend-only` | FastAPI alone, on `127.0.0.1:8000`. |
| `python3 scripts/run.py --frontend-only` | Next.js alone. The UI falls back to browser-side analysis. |

The footer of the page tells you which mode you are actually in.
**Backend: Connected** means the FastAPI engines produced the result;
**Backend: Offline** means the browser-side fallback did. The interface never
presents fallback output as though it came from the real engine.

## Secrets in this archive

`Backend/.env` and `Frontend/.env.local` travel inside this zip, so the app
works the moment setup finishes — including the Groq-powered explanations.
That also means **anyone who gets this file gets those API keys.** Do not put
it on a public share or hand it to someone you would not hand the keys to.

To rebuild the zip without them:

```bash
python3 scripts/package.py --no-secrets
```

Setup then generates a fresh matching backend/frontend key pair on the new
machine, and you paste a Groq key into `Backend/.env` yourself — or leave it
out, and the app runs without AI explanations.

## Ports already in use

If something else holds port 3000 or 8000, `run.py` reports it and stops rather
than half-starting. Free the port, or set another one:

```bash
PORT=3100 python3 scripts/run.py     # frontend on 3100
```

## Rebuilding this zip

From the project directory, after any change:

```bash
python3 scripts/package.py
```

Everything else — architecture, API reference, the engines, deployment — is in
`README.md`.
