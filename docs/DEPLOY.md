# Redeploying AQUAFORECAST on Render (you already deployed once)

## A. Update the code
1. Unzip this package. Open the folder that contains `Dockerfile`, `render.yaml`, `backend`, `frontend`.
2. Get your existing repo on your computer: `git clone https://github.com/YOUR-USERNAME/aquaforecast.git`
   (or open your existing local copy).
3. Delete everything inside the repo folder EXCEPT the hidden `.git` folder, then copy the new files in.
4. NEVER copy a `.env` file into the repo (it holds phone numbers and keys). `.gitignore` blocks it; check anyway.
5. Publish:
   ```
   git add -A
   git commit -m "v6.1: government-style report, validation fix, sources page fix"
   git push
   ```
   No git? On github.com open the repo, Add file > Upload files, drag the new files in (replace existing), Commit.

## B. Deploy
1. Render dashboard > your `aquaforecast` service. If Auto-Deploy is on it starts by itself;
   otherwise click Manual Deploy > Deploy latest commit. Wait for "Live" (3 to 6 minutes).
2. Environment tab: check these exist (the alert keys are NOT read from your laptop's `.env`):
   - `AQUA_POLL_SECONDS` = 600
   - `ALERT_PROVIDER` = `ntfy` (or `webhook`); empty or `log` is a dry run: nothing is sent
   - `NTFY_TOPIC` = your unguessable topic name; every phone subscribed to it in the ntfy app gets the alert
   - `ALERT_ADMIN_TOKEN` = a long random string (needed for the test button)
   - optional `CWC_BULLETIN_URL`
   After changing variables Render restarts the service.

## C. Verify (2 minutes)
1. Open `https://YOUR-APP.onrender.com/api/cities` : a list of 8 cities.
2. Open the site: header says `LIVE · synced ... ago` within about 2 minutes.
3. Data & Sources tab: the Open-Meteo, NASA and river rows show LIVE.
4. Executive View > Generate municipal report : a 4 to 5 page A4 report. Print > Save as PDF.
5. Open `/api/alerts/status` : check `provider_label`, `live`, `recipients` (see ALERTS_TROUBLESHOOTING.md).
6. Add the UptimeRobot monitor (HTTP, every 5 minutes) on `/api/cities` so the free server does not sleep.

## D. If something breaks
Render > Logs. Copy the last 20 lines. Roll back with Deploy > select the previous deploy > Rollback.
