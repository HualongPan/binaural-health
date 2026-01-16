# Frequency Shift Processor (PWA + TWA)

This project deploys your Hilbert-based frequency shifting tool as a **PWA** that can be wrapped into an Android **Trusted Web Activity (TWA)** and published on Google Play.

## 1) Run locally

```bash
python -m venv .venv
source .venv/bin/activate   # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt
python app.py
```
Open:
- http://127.0.0.1:5000

## 2) Deploy (Render recommended)

1. Create a new **Web Service** on Render
2. Connect your GitHub repo (push this folder)
3. Build command:
   ```
   pip install -r requirements.txt
   ```
4. Start command (Render will use Procfile automatically, but you can paste):
   ```
   gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120
   ```
5. After deploy, you'll get an HTTPS URL like:
   - https://your-app.onrender.com

## 3) Confirm PWA installability

In Chrome:
- Open your Render URL
- You should see an **Install** icon in the address bar (desktop) or **Add to Home Screen** (Android)

## 4) Wrap into an Android app (TWA / Bubblewrap)

### Prereqs
- Node.js + npm
- Java 17+
- Android Studio (for SDK)

### Install bubblewrap
```bash
npm i -g @bubblewrap/cli
```

### Init project
```bash
bubblewrap init --manifest=https://YOUR_DOMAIN/manifest.webmanifest
```

Bubblewrap will ask questions and generate an Android project.

### Build an Android App Bundle (AAB)
```bash
bubblewrap build
```

The output **.aab** is what you upload to Google Play Console.

## 5) Digital Asset Links (required!)

For TWA, your site must host:
- `https://YOUR_DOMAIN/.well-known/assetlinks.json`

After `bubblewrap init`, you'll know:
- **package_name**
- **SHA-256 fingerprint**

Replace the placeholder fields in:
- `static/.well-known/assetlinks.json`

Re-deploy the site.

## 6) Google Play Console upload

- Create app → set **Free**
- Upload the generated **.aab**
- Add:
  - App icon + screenshots
  - Privacy policy URL: `https://YOUR_DOMAIN/privacy`
  - Data Safety form (audio files are user-provided and processed only)

---

### Notes
- Output audio is stored temporarily and auto-deleted within ~1 hour.
- Only `.wav` is supported.

