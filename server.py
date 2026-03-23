"""KoeGuide - Municipal FAQ Voice Agent Backend"""

import subprocess
import json
import threading
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import requests as http_requests

from scraper import (
    load_municipalities, add_municipality, scrape_municipality,
    get_cached_data, get_all_cached_data, save_municipalities,
)
from prompt_builder import deploy_prompt

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)


def get_api_key():
    """Retrieve Vocal Bridge API key from macOS Keychain."""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", "vocal-bridge", "-a", "api-key", "-w"],
            capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        raise RuntimeError("API key not found in Keychain.")


# ===========================================
# Main App Routes
# ===========================================

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/admin")
def admin():
    return send_from_directory(".", "admin.html")


@app.route("/api/voice-token", methods=["POST"])
def voice_token():
    """Generate a LiveKit access token via Vocal Bridge API."""
    try:
        api_key = get_api_key()
        participant_name = request.json.get("participant_name", "住民") if request.json else "住民"

        resp = http_requests.post(
            "https://vocalbridgeai.com/api/v1/token",
            headers={
                "X-API-Key": api_key,
                "Content-Type": "application/json",
            },
            json={"participant_name": participant_name},
            timeout=10,
        )
        resp.raise_for_status()
        return jsonify(resp.json())
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500
    except http_requests.RequestException as e:
        return jsonify({"error": f"Vocal Bridge API error: {e}"}), 502


@app.route("/api/faq", methods=["GET"])
def get_faq():
    """Return FAQ data."""
    with open("faq-data.json", "r", encoding="utf-8") as f:
        return jsonify(json.load(f))


# ===========================================
# Municipality Management Routes
# ===========================================

@app.route("/api/municipalities", methods=["GET"])
def list_municipalities():
    """List all registered municipalities."""
    data = load_municipalities()
    # Enrich with cache status
    for m in data["municipalities"]:
        cached = get_cached_data(m["id"])
        m["has_cache"] = cached is not None
        if cached:
            m["cache_chars"] = len(cached.get("raw_text", ""))
            m["has_structured"] = cached.get("structured") is not None
    return jsonify(data["municipalities"])


@app.route("/api/municipalities", methods=["POST"])
def create_municipality():
    """Add a municipality and trigger scraping."""
    body = request.json
    if not body or not body.get("name") or not body.get("garbage_url"):
        return jsonify({"error": "name and garbage_url are required"}), 400

    name = body["name"]
    url = body["garbage_url"]
    name_en = body.get("name_en", "")

    municipality_id = add_municipality(name, url, name_en)

    # Scrape in background
    def do_scrape():
        try:
            scrape_municipality(municipality_id)
        except Exception as e:
            print(f"Background scrape failed: {e}")

    thread = threading.Thread(target=do_scrape)
    thread.start()

    return jsonify({
        "id": municipality_id,
        "name": name,
        "status": "scraping",
        "message": f"Added {name}. Scraping started in background.",
    }), 201


@app.route("/api/municipalities/<municipality_id>", methods=["DELETE"])
def delete_municipality(municipality_id):
    """Remove a municipality."""
    data = load_municipalities()
    data["municipalities"] = [
        m for m in data["municipalities"] if m["id"] != municipality_id
    ]
    save_municipalities(data)
    return jsonify({"status": "deleted"})


@app.route("/api/municipalities/<municipality_id>/scrape", methods=["POST"])
def rescrape_municipality(municipality_id):
    """Re-scrape a municipality."""
    def do_scrape():
        try:
            scrape_municipality(municipality_id)
        except Exception as e:
            print(f"Re-scrape failed: {e}")

    thread = threading.Thread(target=do_scrape)
    thread.start()

    return jsonify({"status": "scraping", "message": "Re-scrape started in background."})


@app.route("/api/municipalities/<municipality_id>/data", methods=["GET"])
def get_municipality_data(municipality_id):
    """Get cached scrape data for a municipality."""
    cached = get_cached_data(municipality_id)
    if not cached:
        return jsonify({"error": "No cached data. Scrape first."}), 404
    return jsonify(cached)


# ===========================================
# Garbage Info API (for Vocal Bridge API Tool)
# ===========================================

@app.route("/api/garbage-info", methods=["GET"])
def garbage_info():
    """Return garbage collection info for a municipality.
    This endpoint is designed to be registered as a Vocal Bridge API Tool.
    """
    municipality = request.args.get("municipality", "")
    category = request.args.get("category", "")

    if not municipality:
        # Return list of available municipalities
        data = load_municipalities()
        available = [
            {"id": m["id"], "name": m["name"], "name_en": m.get("name_en", "")}
            for m in data["municipalities"] if m.get("enabled", True)
        ]
        return jsonify({
            "available_municipalities": available,
            "message": "Please specify a municipality name.",
        })

    # Search by ID or name (partial match)
    data = load_municipalities()
    match = None
    for m in data["municipalities"]:
        if (municipality.lower() in m["id"].lower()
                or municipality in m["name"]
                or municipality.lower() in m.get("name_en", "").lower()):
            match = m
            break

    if not match:
        return jsonify({"error": f"Municipality not found: {municipality}"}), 404

    cached = get_cached_data(match["id"])
    if not cached:
        return jsonify({"error": f"No data available for {match['name']}. Please scrape first."}), 404

    # Return structured data if available, otherwise raw text
    if cached.get("structured"):
        result = cached["structured"]
        result["source_url"] = cached["source_url"]
        result["scraped_at"] = cached["scraped_at"]

        # Filter by category if specified
        if category and result.get("categories"):
            result["categories"] = [
                c for c in result["categories"]
                if category.lower() in c.get("name", "").lower()
                or category.lower() in c.get("name_en", "").lower()
            ]

        return jsonify(result)
    else:
        return jsonify({
            "municipality": cached["municipality"],
            "source_url": cached["source_url"],
            "scraped_at": cached["scraped_at"],
            "data_format": "raw_text",
            "content": cached.get("raw_text", "")[:5000],
        })


# ===========================================
# STT Language Setting
# ===========================================

@app.route("/api/stt-language", methods=["GET"])
def get_stt_language():
    """Get current STT language setting."""
    try:
        result = subprocess.run(
            ["vb", "config", "show"], capture_output=True, text=True, check=True
        )
        # Parse language from output
        for line in result.stdout.split("\n"):
            if "'language'" in line:
                import re
                match = re.search(r"'language':\s*'([^']+)'", line)
                if match:
                    return jsonify({"language": match.group(1)})
        return jsonify({"language": "multi"})
    except Exception:
        return jsonify({"language": "multi"})


@app.route("/api/stt-language", methods=["POST"])
def set_stt_language():
    """Update STT language setting. Requires reconnect to take effect."""
    body = request.json
    lang = body.get("language", "multi") if body else "multi"
    allowed = {"ja": "Japanese", "en": "English", "multi": "Multilingual"}
    if lang not in allowed:
        return jsonify({"error": f"Unsupported language. Use: {list(allowed.keys())}"}), 400

    import tempfile, os
    settings = {"stt": {"language": lang}}
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(settings, tmp)
    tmp.close()
    try:
        result = subprocess.run(
            ["vb", "config", "set", "--model-settings-file", tmp.name],
            capture_output=True, text=True, check=True,
        )
        return jsonify({"language": lang, "label": allowed[lang], "message": result.stdout.strip()})
    except subprocess.CalledProcessError as e:
        return jsonify({"error": e.stderr or "Failed to update STT language"}), 500
    finally:
        os.unlink(tmp.name)


# ===========================================
# Prompt Deployment
# ===========================================

@app.route("/api/deploy-prompt", methods=["POST"])
def deploy_prompt_route():
    """Rebuild and deploy the agent prompt with current scraped data."""
    try:
        prompt = deploy_prompt()
        return jsonify({
            "status": "deployed",
            "prompt_length": len(prompt),
            "message": "Agent prompt updated with scraped municipality data.",
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("🎤 KoeGuide server starting on http://localhost:5555")
    print("   Main app: http://localhost:5555")
    print("   Admin:    http://localhost:5555/admin")
    app.run(host="0.0.0.0", port=5555, debug=True)
