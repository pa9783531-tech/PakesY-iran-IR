# PakesY v6 — online signup edition

**Online accounts (not GitHub Pages-only).** This repository contains a full FastAPI backend and a Dockerfile for Railway deployment. The public HTTPS URL is provided by your cloud host after deployment. GitHub Pages cannot run registration, authentication, uploads or FFmpeg.

**Features:** email/password signup on hosted URL, login sessions, creator-only featured feed priority for `pa9783531@gmail.com` protected by a hosting setup code, visitor uploads, comments, staged simulated reactions for owner uploads, 8-language UI, actual FFmpeg-based Auto Edit, and persistent SQLite+media using Railway Volume. The homepage CSS/JS remain inlined in `index.html` to avoid broken asset paths.

**Deploy:** Follow `ONLINE-راهنما.md` (Persian). Configure `PAKESY_OWNER_SETUP_CODE` and `PAKESY_SESSION_SECRET` as host variables. Create a Railway Volume at `/data` attached to the app service. Deploy from GitHub repository and generate a Railway domain. Upload videos on **that domain**.

**Security note:** Email addresses are not verified, and password resets are not yet available; add email verification, password recovery, moderation and abuse protection before broad public access. The featured account requires the private setup code to prevent email impersonation. SQLite needs a single app instance and the Volume must be backed up. Reactions and rupee totals are modeled, not real audience or revenue.

**Local dev:** `pip install -r requirements.txt && PAKESY_OWNER_SETUP_CODE=my-secure-code uvicorn app:app --port 8765`. No Windows batch file is needed for online use.

**Do not use GitHub Pages for live signup:** Use the Railway-generated HTTPS domain, not `github.io`. `index.html` is self-contained for styling, but cannot replace a backend.
