# Contributing to GitHub Insights Agent

Thanks for your interest in contributing! 🎉 This project welcomes issues and pull
requests. This guide gets you set up and explains how to submit changes.

## Getting set up

```bash
# 1. Fork the repo on GitHub, then clone your fork
git clone https://github.com/<your-username>/github-insights-agent.git
cd github-insights-agent

# 2. Create a virtualenv and install dependencies
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 3. Copy the env template and add a free LLM key
cp .env.example .env              # then set GROQ_API_KEY (console.groq.com/keys)
```

See the [README](README.md) for full run instructions.

## Running the tests

All tests run **offline** (GitHub and the LLM are faked), so no API keys or network
are needed:

```bash
pytest
```

Please make sure the full suite passes before opening a pull request. If you add a
feature or fix a bug, **add or update tests** to cover it.

## Submitting a pull request

1. **Create a branch** off `main`: `git checkout -b feat/short-description`
2. **Make your change**, keeping it focused — one feature or fix per PR.
3. **Add tests** and make sure `pytest` is green.
4. **Match the existing style** — type hints, small focused functions, clear docstrings.
5. **Push** to your fork and **open a PR** against `main`, filling in the PR template
   (what changed, why, and how you tested it).

## Good first contributions

- Add a new read-only GitHub tool (e.g. list a repo's contributors or releases) —
  follow the pattern in `app/tools.py` + `app/schemas.py` + register in `app/agent.py`.
- Add more eval cases in `eval/eval_set.py`.
- Improve the React UI in `frontend/`.

## Ground rules

- Keep tools **read-only** — this project intentionally never writes to GitHub.
- Never commit secrets. `.env` is git-ignored; use `.env.example` for new settings.
- Be respectful and constructive in issues and reviews.

Questions? Open an issue — happy to help. 🙌
