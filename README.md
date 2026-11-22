# ClipForge — Public Beta (upload + YouTube link -> clips)

## What this code does

ClipForge is a FastAPI + FFmpeg video clipping **public beta**. Any visitor to the deployed app can choose **Upload video** or **Paste a public YouTube URL**, select clips and aspect ratio, generate and download their own MP4 clips. The project remains a **beta**, not an OpusClip-equivalent AI system: clip selection uses *audio energy heuristics*, not semantic viral prediction, and auto-captions require the optional Whisper installation.

A video engine **must** run on a cloud host. GitHub Pages alone cannot process videos. The simplest setup is to host **both frontend and backend together in one Docker web service**. Its root URL will display ClipForge automatically.

## Tested locally

- Python FastAPI app boots and returns `/api/health` with FFmpeg ready.
- Uploaded sample video -> short MP4 -> preview/download and edited MP4.
- Requests without the project's secret token are denied: listing all projects and opening someone else's project or media does not work.
- Invalid/unrecognized URL is rejected.
- **Not tested online:** real YouTube import (`yt-dlp`) from this environment; it depends on the provider and network. YouTube livestreams, sign-in requirements, limits and terms may prevent importing. Only import content you own or have permission to use.

## Files

- `app.py` — FastAPI backend and video rendering
- `static/` — interactive website and pricing (`$5/month`, `$50/year`, sample only)
- `assets/demo.mp4` — original demo video
- `Dockerfile` — container with FFmpeg + Python + yt-dlp
- `requirements.txt` — server packages
- `start_windows.bat` — local Windows setup
- `github-pages/index.html` — standalone, static website for an optional old GitHub Pages preview; configure its backend URL only after deploying a real server
- `DEPLOY_ROMAN_URDU.txt` — simple hosting setup instructions

## Deploy to Railway (simple public beta)

1. Extract the zip. Make a **new GitHub repository** for the contents of `ClipForge_public_beta/` — not just `index.html`, and not the ZIP itself. The `Dockerfile` should be in the repo root.
2. In Railway, create a new project and select **Deploy from GitHub Repo** -> select the new backend repository. Railway discovers the included Dockerfile and runs a Python/FFmpeg server. https://docs.railway.com/services
3. In Railway, attach a **Volume** to the service, mount path **`/app/storage`**. Then set variables:
   - `CLIPFORGE_STORAGE_DIR=/app/storage`
   - `MAX_UPLOAD_MB=150`
   - `MAX_ACTIVE_JOBS=2`
   - `MAX_JOBS_HOURLY=8`
   - `PROJECT_TTL_HOURS=24`
   - `CLIPFORGE_CORS_ORIGINS=https://jawadsdt786-blip.github.io`
4. Use Railway **Networking -> Generate Domain** to get a public `https://...` domain. Open `https://YOUR-DOMAIN/api/health`; `ffmpeg` and `link_import` should both say `true` if `yt-dlp` is installed and the build succeeded.
5. Open `https://YOUR-DOMAIN/` — this is **the working website and engine in one place**, so visitors do not need to configure any engine URL.
6. Test one small video you own, upload -> Generate -> Preview -> Download. Test a public regular (not live) YouTube URL you own or have permission to use.
7. If you want visitors on your **existing GitHub Pages design** rather than using the Railway domain, set this field in `github-pages/index.html` once: `<meta name="clipforge-backend" content="https://YOUR-DOMAIN">`, replace your old GitHub Pages `index.html` with the updated one, and publish. Note that **GitHub Pages is not allowed as hosting for a commercial SaaS/ecommerce service** (see official terms); use the Railway domain or a domain hosted by your app host for any paid business.

Railway volume details: https://docs.railway.com/volumes/reference . Hosting, compute, bandwidth and volume storage can incur fees. Video processing is resource-intensive; choose a plan with enough disk, RAM, CPU, request limits and bandwidth. Do not promise large files or rapid processing until load-tested.

## Run locally

Install Python 3.11+ and FFmpeg (including ffprobe) on PATH. On Windows run `start_windows.bat`, then open http://127.0.0.1:8000/ . For link import, `yt-dlp` must be installed (included in requirements.txt).

### Current safety / privacy properties

- A project is created with a random access token stored only in the creator's browser `localStorage`. Tokens are sent as `X-Project-Token` headers for APIs, and in private MP4 URL query parameters for playback. Someone with a project token can access that project; this is **not a full login system**.
- General project listing is disabled. Clip files and source videos are **not publicly mounted** as static files.
- Stored project access expires after `PROJECT_TTL_HOURS` (default 24h). The cleanup sweep is run when new jobs are submitted (up to every 5 minutes), so physical deletion can occur later if idle.
- Source uploads capped at 150 MB and 60-minute duration; 2 simultaneous jobs and 8/hour per client address are simple abuse-control defaults; at most 5 clips per job and 45 seconds each.
- CORS restricts browser access but **is not security**. There is no sign-up, billing enforcement, content moderation, durable database, robust shared rate limits, malware scanning, separate job workers, proper user data export or production scaling. Cookie-based auth/OAuth, storage lifecycle, abuse controls and proper queues are recommended **before a wide public paid launch**.
- The current memory-based per-client limiter may not accurately identify clients behind shared proxies. It isn't production-grade. Only deploy publicly as a controlled beta with monitoring and limits.

## Pricing

The `#pricing` page displays the user's proposed Creator price ($5 monthly / $50 annually, ~17% annual discount) as a **preview**. No payment gateway or recurring billing is connected. Never accept paid orders with this code as-is.
