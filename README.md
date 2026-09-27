# Course Completion Automation

Browser automation for processing courses on the BPK Penabur Digital Learning platform. Inspired by [@DaringCuteSeal](https://github.com/DaringCuteSeal).

> For educational purposes only.

## Features

* Uses authenticated browser cookies.
* Searches and enrolls in selected courses.
* Skips completed courses.
* Processes videos, supported quizzes, and static pages.
* Detects pages requiring manual input.
* Saves completed courses and manual-review links.
* Supports concurrent course processing and retries.
* Uses Selenium Manager for browser setup.

## Requirements

* Python 3.10+
* Firefox, Chrome, Chromium, or Brave
* `requests`, `selenium`, and `python-dotenv`
* Authorized account and active browser session

## Installation

### Windows

```powershell
git clone https://github.com/marvelj0/PDLazy.git
cd PDLazy
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install requests selenium python-dotenv
```

### Linux / macOS

```bash
git clone https://github.com/marvelj0/PDLazy.git
cd PDLazy
python3 -m venv .venv
source .venv/bin/activate
pip install requests selenium python-dotenv
```

### UV

```bash
git clone https://github.com/marvelj0/PDLazy.git
cd PDLazy
uv venv
uv pip install selenium requests python-dotenv
uv run pdl.py
```
## Configuration

Copy `.env.example` to `.env` and fill in the required values.

Set `BROWSER=firefox` in `.env` to use Firefox. Selenium Manager locates or downloads the required driver automatically. Use `BROWSER=chromium` for the Chromium-based options.
Get the category IDs from `categorylist.json`.

Get the required cookies from your logged-in browser's Developer Tools → Application/Storage → Cookies.

**Never publish your cookies or tokens.** They provide access to your account.

## Usage

```bash
python pdl.py
``` 
## Output

* `completed_courses.txt` — completed course IDs.
* `input_required_links.txt` — pages requiring manual input.

Failed courses are not marked complete and will be retried.

## Concurrency

`MAX_CONCURRENT_COURSES` controls parallel browser sessions.

Start with `1–2` workers and increase gradually. More workers require more RAM/CPU and may increase the chance of rate limiting.

## Troubleshooting

**Missing modules:**

```bash
pip install requests selenium python-dotenv
```

**Browser won't start:** Make sure the selected browser is installed and update Selenium:

```bash
pip install --upgrade selenium
```

**Authentication fails:** Sign in again and replace the expired cookies.

**No courses found:** Check `CATEGORY_ID` and `SUBCATEGORY_ID` in `categorylist.json`.
