'''
Author:     Sai Vignesh Golla
License:    MIT License
            https://opensource.org/license/mit
GitHub:     https://github.com/GodsScion/Auto_job_applier_linkedIn

Local "control panel" web app. It lets a non-technical person configure and run
the tool from a browser instead of editing Python files and using a terminal.

IMPORTANT - how configuration works:
  * This app reads/writes ONLY `user_config.json` at the project root.
  * It NEVER edits the config/*.py files.
  * The config/*.py modules load user_config.json over their built-in defaults
    (see config/_overrides.py), so saving here changes the tool's behaviour
    while leaving the classic "edit the .py files" workflow intact. With no
    user_config.json present the tool behaves exactly as it always has.

SECURITY: this app handles LinkedIn credentials, so it binds to 127.0.0.1 only
(never 0.0.0.0) and runs with debug OFF. Do not change these.
'''

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import csv
from datetime import datetime
import os
import sys
import json
import copy
import signal
import subprocess
import threading
import importlib

import config_schema
from config import _overrides

app = Flask(__name__)
CORS(app)

# Project root is the folder this file lives in.
ROOT = os.path.dirname(os.path.abspath(__file__))
import glob
USER_CONFIG_PATH = _overrides.USER_CONFIG_PATH
LOG_PATH = None
PID_PATH = os.path.join(ROOT, ".bot_run.pid")

PATH = 'all excels/'


# ===========================================================================
# Default config values (the pristine config/*.py defaults, ignoring any
# user_config.json). Captured once at startup so /api/config can always show
# "default overlaid with the user's current saved values".
# ===========================================================================
def _load_defaults() -> dict:
    '''
    Import each config module with overrides temporarily disabled, so we read
    the untouched Python defaults regardless of whether user_config.json exists
    right now. Returns {config_module: {key: default_value}}.
    '''
    original_loader = _overrides.load_user_config
    _overrides.load_user_config = lambda: {}
    try:
        import config.secrets as _secrets
        import config.personals as _personals
        import config.questions as _questions
        import config.search as _search
        import config.settings as _settings
        modules = {
            "secrets": _secrets,
            "personals": _personals,
            "questions": _questions,
            "search": _search,
            "settings": _settings,
        }
        # Reload in case they were already imported (with real overrides) earlier.
        for module in modules.values():
            importlib.reload(module)
        defaults = {}
        for field in config_schema.iter_fields():
            module_name = field["config_module"]
            key = field["key"]
            module = modules.get(module_name)
            defaults.setdefault(module_name, {})[key] = getattr(module, key, None)
        return defaults
    finally:
        _overrides.load_user_config = original_loader


DEFAULTS = _load_defaults()


# ===========================================================================
# Config API helpers
# ===========================================================================
def _effective_config() -> dict:
    '''
    Return {config_module: {key: value}} of the pristine defaults overlaid with
    the CURRENT contents of user_config.json (re-read from disk on every call).
    Only keys defined in config_schema are included.
    '''
    effective = copy.deepcopy(DEFAULTS)
    user = _overrides.load_user_config()
    for field in config_schema.iter_fields():
        module_name = field["config_module"]
        key = field["key"]
        section = user.get(module_name)
        if isinstance(section, dict) and key in section:
            effective[module_name][key] = section[key]
    # Expose custom non-schema fields like ai_apis
    if "secrets" in user and "ai_apis" in user["secrets"]:
        effective.setdefault("secrets", {})["ai_apis"] = user["secrets"]["ai_apis"]
    else:
        effective.setdefault("secrets", {})["ai_apis"] = []
    return effective


def _coerce(field_type: str, value):
    '''
    Coerce an incoming JSON value into the type declared for the field in the
    schema. Raises ValueError on invalid numbers so the caller can reject them.
    '''
    if field_type in ("text", "password", "textarea", "select"):
        return "" if value is None else str(value)

    if field_type == "number":
        if isinstance(value, bool):
            raise ValueError("expected a number, got a boolean")
        if isinstance(value, (int, float)):
            number = value
        else:
            text = str(value).strip()
            if text == "":
                raise ValueError("expected a number, got an empty value")
            number = float(text)
        # Keep whole numbers as ints (the config defaults are ints).
        if isinstance(number, float) and number.is_integer():
            return int(number)
        return number

    if field_type == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "yes", "on")

    if field_type == "list":
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip() != ""]
        text = str(value).strip()
        if text == "":
            return []
        return [item.strip() for item in text.split(",") if item.strip() != ""]

    # Unknown type: pass through untouched.
    return value


# ===========================================================================
# Bot subprocess management (run / stop / status / logs)
# ===========================================================================
_bot_proc = None
_bot_lock = threading.Lock()


def _bot_command():
    '''The command used to launch the bot. Isolated so tests can monkeypatch it.'''
    return [sys.executable, os.path.join(ROOT, "runAiBot.py")]


def _is_running() -> bool:
    '''True if the tracked bot subprocess exists and has not exited.'''
    global _bot_proc
    if _bot_proc is None:
        return False
    if _bot_proc.poll() is None:
        return True
    # Process has exited; clean up tracking + PID file.
    _bot_proc = None
    _remove_pid_file()
    return False


def _remove_pid_file():
    try:
        os.remove(PID_PATH)
    except OSError:
        pass


def _terminate(proc) -> None:
    '''Terminate the subprocess and, where feasible, its child processes.'''
    if proc is None or proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            # Kill the whole process tree on Windows.
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            # We launched with start_new_session=True, so the child is its own
            # process-group leader; signal the whole group.
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                proc.terminate()
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass
    # Give it a moment, then force-kill if still alive.
    try:
        proc.wait(timeout=5)
    except Exception:
        try:
            if os.name != "nt":
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
        except Exception:
            pass


@app.route('/')
def home():
    """Serve the control panel single-page app."""
    return render_template('control_panel.html')


@app.route('/history')
def history():
    """Serve the applied-jobs history page."""
    return render_template('index.html')


# The applied-jobs history CSV the bot writes, and how its columns map to the JSON
# keys the history page consumes.
_HISTORY_CSV = 'all_applied_applications_history.csv'
_HISTORY_FIELDS = {
    'Job ID': 'Job_ID',
    'Title': 'Title',
    'Company': 'Company',
    'HR Name': 'HR_Name',
    'HR Link': 'HR_Link',
    'Job Link': 'Job_Link',
    'External Job link': 'External_Job_link',
    'Date Applied': 'Date_Applied',
    'Search Term': 'Search_Term',
    'Search Location': 'Search_Location',
}


@app.route('/applied-jobs', methods=['GET'])
def get_applied_jobs():
    """Return the applied-jobs history as JSON for the history page."""
    csv_path = os.path.join(PATH, _HISTORY_CSV)
    if not os.path.exists(csv_path):
        return jsonify([]), 200
    try:
        jobs = []
        with open(csv_path, 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                jobs.append({key: row.get(col, '') for col, key in _HISTORY_FIELDS.items()})
        return jsonify(jobs)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


_FAILED_CSV = 'all_failed_applications_history.csv'
_FAILED_FIELDS = {
    'Job ID': 'Job_ID',
    'Title': 'Title',
    'Company': 'Company',
    'Job Link': 'Job_Link',
    'Date Tried': 'Date_Applied',
    'Assumed Reason': 'Reason',
    'Search Term': 'Search_Term',
    'Search Location': 'Search_Location',
}

@app.route('/failed-jobs', methods=['GET'])
def get_failed_jobs():
    """Return the failed/skipped-jobs history as JSON."""
    csv_path = os.path.join(PATH, _FAILED_CSV)
    if not os.path.exists(csv_path):
        return jsonify([]), 200
    try:
        jobs = []
        with open(csv_path, 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                jobs.append({key: row.get(col, '') for col, key in _FAILED_FIELDS.items()})
        return jsonify(jobs)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- Custom Jobs Endpoints ---
_CUSTOM_JOBS_FILE = os.path.join(PATH, 'config', 'custom_jobs.json')

def _load_custom_jobs():
    if not os.path.exists(_CUSTOM_JOBS_FILE):
        return []
    try:
        with open(_CUSTOM_JOBS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f).get("jobs", [])
    except:
        return []

def _save_custom_jobs(jobs):
    try:
        os.makedirs(os.path.dirname(_CUSTOM_JOBS_FILE), exist_ok=True)
        with open(_CUSTOM_JOBS_FILE, 'w', encoding='utf-8') as f:
            json.dump({"jobs": jobs}, f, indent=2)
    except Exception as e:
        print(f"Error saving custom jobs: {e}")

@app.route('/api/custom-jobs', methods=['GET'])
def get_custom_jobs():
    return jsonify(_load_custom_jobs())

@app.route('/api/custom-jobs/add', methods=['POST'])
def add_custom_job():
    data = request.json or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL cannot be empty"}), 400
    
    jobs = _load_custom_jobs()
    if any(j["url"] == url for j in jobs):
        return jsonify({"error": "Job URL already exists"}), 400
        
    import uuid
    new_job = {
        "id": str(uuid.uuid4()),
        "url": url,
        "status": "Pending",
        "reason": ""
    }
    jobs.append(new_job)
    _save_custom_jobs(jobs)
    return jsonify(new_job), 200

@app.route('/api/custom-jobs/delete', methods=['POST'])
def delete_custom_job():
    data = request.json or {}
    job_id = data.get("id", "")
    jobs = _load_custom_jobs()
    updated = [j for j in jobs if j["id"] != job_id]
    _save_custom_jobs(updated)
    return jsonify({"success": True}), 200

@app.route('/api/custom-jobs/retry-all', methods=['POST'])
def retry_all_custom_jobs():
    jobs = _load_custom_jobs()
    for j in jobs:
        j["status"] = "Pending"
        j["reason"] = ""
    _save_custom_jobs(jobs)
    return jsonify({"success": True}), 200


@app.route('/applied-jobs/<job_id>', methods=['PUT'])
def mark_job_applied(job_id):
    """Stamp one job's 'Date Applied' (matched by Job ID) with the current time."""
    csv_path = os.path.join(PATH, _HISTORY_CSV)
    if not os.path.exists(csv_path):
        return jsonify({"error": f"History file not found at {csv_path}"}), 404
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            columns = reader.fieldnames
            rows = list(reader)
        matched = False
        for row in rows:
            if row.get('Job ID') == job_id:
                row['Date Applied'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                matched = True
        if not matched:
            return jsonify({"error": f"Job ID {job_id} not found"}), 404
        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        return jsonify({"message": "Date Applied updated."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===========================================================================
# Control-panel API
# ===========================================================================
@app.route('/api/schema', methods=['GET'])
def api_schema():
    '''Returns the field schema the UI renders its forms from.'''
    return jsonify(config_schema.SCHEMA)


@app.route('/api/config', methods=['GET'])
def api_get_config():
    '''
    Returns the effective config: pristine defaults overlaid with the current
    user_config.json, grouped by config module (secrets, personals, questions,
    search, settings).
    '''
    return jsonify(_effective_config())


@app.route('/api/config', methods=['POST'])
def api_save_config():
    '''
    Accepts {config_module: {key: value}}, validates against the schema, coerces
    each value to its declared type, rejects unknown modules/keys, merges into
    user_config.json (read-modify-write) and returns the full saved config.
    '''
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Expected a JSON object of {section: {key: value}}"}), 400

    valid = config_schema.valid_keys()
    unknown = []
    coerced = {}

    for section, values in payload.items():
        if not isinstance(values, dict):
            return jsonify({"error": f"Section '{section}' must be an object"}), 400
        if section not in valid:
            unknown.append(section)
            continue
        for key, value in values.items():
            if section == "secrets" and key == "ai_apis":
                if not isinstance(value, list):
                    return jsonify({"error": "ai_apis must be a list"}), 400
                coerced.setdefault(section, {})[key] = value
                continue
            field = valid[section].get(key)
            if field is None:
                unknown.append(f"{section}.{key}")
                continue
            try:
                coerced.setdefault(section, {})[key] = _coerce(field["type"], value)
            except ValueError as err:
                return jsonify({"error": f"Invalid value for '{section}.{key}': {err}"}), 400

    if unknown:
        return jsonify({"error": "Unknown settings rejected", "unknown": unknown}), 400

    # Read-modify-write user_config.json.
    current = _overrides.load_user_config()
    for section, values in coerced.items():
        target = current.get(section)
        if not isinstance(target, dict):
            target = {}
        target.update(values)
        current[section] = target

    try:
        with open(USER_CONFIG_PATH, "w", encoding="utf-8") as file:
            json.dump(current, file, indent=2, ensure_ascii=False)
    except OSError as err:
        return jsonify({"error": f"Could not save settings: {err}"}), 500

    return jsonify(current)


@app.route('/api/ai-apis/test', methods=['POST'])
def api_test_ai_api():
    payload = request.get_json(silent=True) or {}
    provider = payload.get("provider", "openai")
    model_name = payload.get("model", "")
    api_key = payload.get("api_key", "").strip()
    api_url = payload.get("api_url", "").strip()
    
    if not model_name:
        return jsonify({"success": False, "error": "Model name is required."})

    try:
        from langchain.chat_models import init_chat_model
        
        if provider == "gemini":
            if api_key and api_key.lower() != "not-needed":
                os.environ["GOOGLE_API_KEY"] = api_key
            model = init_chat_model(model_name, model_provider="google_genai", temperature=0.1)
        else:
            kwargs = {
                "api_key": api_key or "not-needed"
            }
            if api_url:
                kwargs["base_url"] = api_url
            model = init_chat_model(model_name, model_provider="openai", temperature=0.1, **kwargs)
        
        test_prompt = payload.get("prompt", "").strip()
        if not test_prompt:
            test_prompt = """You must answer all of the following three tasks.
1. Explain the concept of "quantum entanglement" to a high school student, including its potential applications.
2. Discuss the primary ethical challenges posed by the rapid development of autonomous vehicles.
3. Write a short story about a sentient AI that discovers a hidden message within the internet's oldest data archives."""

        response = model.invoke(test_prompt)
        from modules.ai.connections import _msg_text
        text = _msg_text(response).strip()
        if not text:
            return jsonify({"success": False, "error": "Model returned an empty response."})
            
        return jsonify({"success": True, "response": text})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/run', methods=['POST'])
def api_run():
    '''Starts the bot as a subprocess if it isn't already running.'''
    global _bot_proc
    with _bot_lock:
        if _is_running():
            return jsonify({"running": True, "pid": _bot_proc.pid,
                            "message": "The tool is already running."})
        try:
            global LOG_PATH
            # yy mm dd_AM/PM hh-mm-ss
            ts_filename = datetime.now().strftime("%y %m %d_%p %I-%M-%S")
            LOG_PATH = os.path.join(ROOT, "logs", f"{ts_filename}.log")
            
            # Touch the file immediately to avoid race conditions with the UI polling
            with open(LOG_PATH, "w", encoding="utf-8") as f:
                pass

            popen_kwargs = {
                "cwd": ROOT,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                popen_kwargs["start_new_session"] = True
            _bot_proc = subprocess.Popen(_bot_command(), **popen_kwargs)
            
            def pipe_stream(proc, path):
                with open(path, "w", encoding="utf-8") as f:
                    for line in iter(proc.stdout.readline, b''):
                        decoded = line.decode("utf-8", "replace")
                        # timestamp format yy mm dd : AM/PM hh:mm:ss
                        ts = datetime.now().strftime("[%y %m %d : %p %I:%M:%S]")
                        f.write(f"{ts} {decoded}")
                        f.flush()
            threading.Thread(target=pipe_stream, args=(_bot_proc, LOG_PATH), daemon=True).start()
        except Exception as err:
            return jsonify({"running": False, "error": str(err)}), 500
        try:
            with open(PID_PATH, "w", encoding="utf-8") as pid_file:
                pid_file.write(str(_bot_proc.pid))
        except OSError:
            pass
        return jsonify({"running": True, "pid": _bot_proc.pid})


@app.route('/api/stop', methods=['POST'])
def api_stop():
    '''Stops the running bot subprocess (and its children where possible).'''
    global _bot_proc
    with _bot_lock:
        if _bot_proc is not None:
            _terminate(_bot_proc)
            _bot_proc = None
        _remove_pid_file()
        return jsonify({"running": False})


@app.route('/api/status', methods=['GET'])
def api_status():
    '''Reports whether the bot subprocess is currently running.'''
    with _bot_lock:
        running = _is_running()
        pid = _bot_proc.pid if (running and _bot_proc is not None) else None
        return jsonify({"running": running, "pid": pid})


@app.route('/api/logs', methods=['GET'])
def api_logs():
    '''
    Returns the run log starting from byte offset ?offset=N, plus the byte
    offset to read from next time. The UI polls this while the bot runs.
    '''
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if offset < 0:
        offset = 0
    if LOG_PATH is None or not os.path.exists(LOG_PATH):
        return jsonify({"content": "", "next_offset": 0})
    try:
        import re
        with open(LOG_PATH, "rb") as log_file:
            log_file.seek(0, os.SEEK_END)
            size = log_file.tell()
            if offset > size:
                offset = 0
            log_file.seek(offset)
            data = log_file.read()
            next_offset = log_file.tell()
            decoded = data.decode("utf-8", "replace")
            # Strip the timestamp [yy mm dd : AM/PM hh:mm:ss] for the UI
            decoded = re.sub(r'^\[\d{2} \d{2} \d{2} : (?:AM|PM) \d{2}:\d{2}:\d{2}\] ', '', decoded, flags=re.MULTILINE)
        return jsonify({"content": decoded, "next_offset": next_offset})
    except Exception as e:
        return jsonify({"content": f"\nError reading log: {e}\n", "next_offset": offset})


def _resolve_port(preferred: int = 5000) -> int:
    '''
    Pick a port to serve on. Honors the PORT environment variable (the launcher
    scripts set it). Otherwise tries `preferred`, and if that's taken - e.g. port
    5000 is used by AirPlay Receiver on macOS - asks the OS for any free port so
    the panel always starts instead of crashing with "address already in use".
    '''
    import socket
    requested = os.environ.get("PORT", "").strip()
    if requested.isdigit():
        return int(requested)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


if __name__ == '__main__':
    # SECURITY: localhost only, debug OFF. This app handles credentials.
    port = _resolve_port(5000)
    url = "http://127.0.0.1:%d" % port
    print(
        "\n  Control panel ready at:  %s\n"
        "  Keep this window open while you use the tool; close it to stop.\n" % url,
        flush=True,
    )
    # The launcher scripts set PANEL_OPEN_BROWSER=1 so the browser opens itself,
    # to the right port, cross-platform. Running `python app.py` by hand won't.
    if os.environ.get("PANEL_OPEN_BROWSER", "").strip() not in ("", "0", "false", "False"):
        import threading
        import webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False)
