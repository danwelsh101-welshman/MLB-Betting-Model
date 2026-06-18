# Deploying edgr (free, permanent URL)

The easiest permanent host for a Streamlit app is **Streamlit Community Cloud**.
Your project is already prepared for it (secrets bridge, auto-build on first
load, `.env` kept private). Follow these steps once.

## 1. Put the code on GitHub
The repo is already initialized and committed locally. Create an empty repo on
github.com (e.g. `edgr`), then in this folder run:

```bash
git remote add origin https://github.com/<your-username>/edgr.git
git branch -M main
git push -u origin main
```

> Your `.env` (with your API keys) is git-ignored and will NOT be uploaded. Good.

## 2. Create the app on Streamlit Cloud
1. Go to https://share.streamlit.io and sign in with GitHub.
2. Click **New app** → choose your `edgr` repo, branch `main`.
3. Set **Main file path** to: `app/streamlit_app.py`
4. Open **Advanced settings** → set **Python version to 3.13**
   (Streamlit Cloud does not offer 3.14 yet; the app runs fine on 3.13).

## 3. Add your secrets (keys stay private)
In the app's **Settings → Secrets**, paste (using your real keys):

```toml
ODDS_API_KEY = "your_rest_api_key"
ODDS_WIDGET_URL = "https://widget.the-odds-api.com/v1/sports/baseball_mlb/events/?accessKey=YOUR_WIDGET_KEY&bookmakerKeys=fanduel&oddsFormat=american&markets=h2h%2Cspreads%2Ctotals"
```

## 4. Deploy
Click **Deploy**. In ~2 minutes you get a permanent URL like
`https://edgr.streamlit.app`. It stays up and reloads automatically whenever
you `git push` new changes.

## Things to know
- **Widget odds**: add your `*.streamlit.app` domain to the allowed domains in
  your The Odds API widget settings, or the FanDuel panel may not render.
- **Free odds tier (500 req/mo)** will not survive heavy public traffic — a
  paid odds plan is needed before promoting the site widely.
- **Database is ephemeral** on the cloud (it resets on restart); picks rebuild
  automatically, so this is fine.
