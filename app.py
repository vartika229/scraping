import threading
import uuid
import logging
import time
from flask import Flask, render_template, request, jsonify, Response
from flask_cors import CORS

from google_maps_scraper import (
    validate_google_maps_url,
    run_scrape,
    generate_file_bytes,
)

app = Flask(__name__)
CORS(app)
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# In-memory job store  —  { job_id: { status, results, error } }
jobs = {}
jobs_lock = threading.Lock()
JOB_TTL_SECONDS = 3600


@app.route("/")
def index():
    return render_template("index.html")


# --------------- Scrape API ---------------

def _cleanup_jobs() -> None:
    """Remove stale finished jobs to keep memory bounded."""
    now = time.time()
    stale_ids = []
    with jobs_lock:
        for jid, payload in jobs.items():
            if payload.get("status") in {"done", "error"} and now - payload.get("updated_at", now) > JOB_TTL_SECONDS:
                stale_ids.append(jid)
        for jid in stale_ids:
            jobs.pop(jid, None)


def _run_job(job_id: str, url: str, max_results: int, extract_email: bool):
    """Background worker that runs Playwright and stores results."""
    try:
        results = run_scrape(url, max_results=max_results, extract_email=extract_email)
        with jobs_lock:
            jobs[job_id]["results"] = results
            # Even if there were some internal timeouts, if we got results back, call it done.
            jobs[job_id]["status"] = "done"
            jobs[job_id]["updated_at"] = time.time()
    except Exception as e:
        logger.error(f"Job {job_id} failed catastrophically: {e}")
        # If run_scrape failed completely before getting any results
        with jobs_lock:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = "Scraping failed: " + str(e)
            jobs[job_id]["updated_at"] = time.time()


@app.route("/scrape", methods=["POST"])
def scrape():
    data = request.get_json(force=True)
    url = (data.get("url") or "").strip()

    if not url:
        return jsonify({"error": "URL is required."}), 400
    if not validate_google_maps_url(url):
        return jsonify({"error": "Invalid Google Maps URL."}), 400

    max_raw = data.get("max", 20)
    try:
        max_results = int(max_raw)
    except (TypeError, ValueError):
        return jsonify({"error": "Max results must be an integer."}), 400
    if max_results < 1 or max_results > 200:
        return jsonify({"error": "Max results must be between 1 and 200."}), 400
    extract_email = bool(data.get("emails", False))

    job_id = str(uuid.uuid4())
    _cleanup_jobs()
    with jobs_lock:
        jobs[job_id] = {"status": "running", "results": None, "error": None, "updated_at": time.time()}

    thread = threading.Thread(target=_run_job, args=(job_id, url, max_results, extract_email), daemon=True)
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>")
def job_status(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404
    return jsonify(job)


# --------------- Download API ---------------

@app.route("/download", methods=["POST"])
def download():
    """Generate a downloadable file from the provided results payload."""
    data = request.get_json(force=True)
    results = data.get("results", [])
    fmt = str(data.get("format", "csv")).lower()

    if not results:
        return jsonify({"error": "No data to download."}), 400
    if fmt not in {"csv", "json", "xlsx"}:
        return jsonify({"error": "Invalid format. Use csv, json, or xlsx."}), 400

    file_bytes = generate_file_bytes(results, fmt)

    mime_map = {
        "csv": "text/csv",
        "json": "application/json",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    mime = mime_map.get(fmt, "application/octet-stream")
    filename = f"scraped_data.{fmt}"

    return Response(
        file_bytes,
        mimetype=mime,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


if __name__ == "__main__":
    # Disable debug mode for production (Render) to save memory and prevent process restarts
    app.run(debug=False, host="0.0.0.0", port=5000)
