# Sentimeter

[![Release](https://img.shields.io/badge/release-v1.0.0-blue)](https://github.com/jad-chahin/sentimeter/releases/tag/v1.0.0)

Sentimeter pulls Reddit discussion data, extracts ticker mentions, and produces sentiment/report outputs.

## Prerequisites

- **Python 3.10+** (3.11 works great too)
- `pip` (comes with Python)

## Quickstart (Windows / macOS / Linux)

### 1) Clone and enter the project
```bash
git clone https://github.com/jad-chahin/sentimeter.git
cd sentimeter
```

### 2) Create a virtual environment (recommended)
```bash
python -m venv .venv
```

### 3) Activate the virtual environment

**Windows (Command Prompt):**
```bat
.venv\Scripts\activate.bat
```

**Windows (PowerShell):**
```powershell
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux (bash/zsh):**
```bash
source .venv/bin/activate
```

### 4) Install dependencies
```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 5) Run
```bash
python main.py [--shortcut] [--validate]
```

Options:

- `--shortcut`: identify key financial terms before AI analysis to save time and tokens.
- `--validate`: verify tickers at the end using Yahoo Finance information.

## Credentials

- Create a Reddit client at https://www.reddit.com/prefs/apps.
- OpenAI API access is required as of `v1.0.0`.
