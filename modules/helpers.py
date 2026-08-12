'''
Author:     Sai Vignesh Golla
LinkedIn:   https://www.linkedin.com/in/saivigneshgolla/

Copyright (c) 2024-2026 Sai Vignesh Golla

License:    MIT License
            https://opensource.org/license/mit
            
GitHub:     https://github.com/GodsScion/Auto_job_applier_linkedIn

Support me: https://github.com/sponsors/GodsScion

version:    26.01.20.5.08
'''


# Imports

import os
import sys
import json
import pathlib

from time import sleep
from random import randint
from datetime import datetime, timedelta
from pprint import pprint

def alert(msg="", title=""):
    print(f"[{title}] {msg}")

from config.settings import logs_folder_path



#### Common functions ####

#< Directories related
def make_directories(paths: list[str]) -> None:
    '''Create any of the given directories that don't yet exist (a path pointing at a file creates its parent folder).'''
    for raw_path in paths:
        target = os.path.expanduser(raw_path).replace("//", "/")
        # If the last segment has an extension it's a file, so keep only its folder.
        if '.' in os.path.basename(target):
            target = os.path.dirname(target)
        if not target:
            continue
        try:
            os.makedirs(target, exist_ok=True)
        except Exception as e:
            print(f'Could not create the directory "{target}":', e)


def get_default_temp_profile() -> str:
    # Thanks to https://github.com/vinodbavage31 for suggestion!
    home = pathlib.Path.home()
    if sys.platform.startswith('win'):
        return "--user-data-dir=C:\\temp\\auto-job-apply-profile"
    elif sys.platform.startswith('linux'):
        return str(home / ".auto-job-apply-profile")
    return str(home / "Library" / "Application Support" / "Google" / "Chrome" / "auto-job-apply-profile")


def find_default_profile_directory() -> str | None:
    '''
    Dynamically finds the default Google Chrome 'User Data' directory path
    across Windows, macOS, and Linux, regardless of OS version.

    Returns the absolute path as a string, or None if the path is not found.
    '''
    
    home = pathlib.Path.home()
    
    # Windows
    if sys.platform.startswith('win'):
        paths = [
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data"),
            os.path.expandvars(r"%USERPROFILE%\AppData\Local\Google\Chrome\User Data"),
            os.path.expandvars(r"%USERPROFILE%\Local Settings\Application Data\Google\Chrome\User Data")
        ]
    # Linux
    elif sys.platform.startswith('linux'):
        paths = [
            str(home / ".config" / "google-chrome"),
            str(home / ".var" / "app" / "com.google.Chrome" / "data" / ".config" / "google-chrome"),
        ]
    # MacOS ## For some reason, opening with profile in MacOS is not creating a session for undetected-chromedriver!
    # elif sys.platform == 'darwin':
    #     paths = [
    #         str(home / "Library" / "Application Support" / "Google" / "Chrome")
    #     ]
    else:
        return None

    # Check each potential path and return the first one that exists
    for path_str in paths:
        if os.path.exists(path_str):
            return path_str
            
    return None
#>


#< Logging related
def critical_error_log(possible_reason: str, stack_trace: Exception) -> None:
    '''
    Function to log and print critical errors along with datetime stamp
    '''
    print_lg(possible_reason, stack_trace, datetime.now(), from_critical=True)


def get_log_path():
    '''
    Function to replace '//' with '/' for logs path
    '''
    try:
        path = logs_folder_path+"/log.txt"
        return path.replace("//","/")
    except Exception as e:
        critical_error_log("Failed getting log path! So assigning default logs path: './logs/log.txt'", e)
        return "logs/log.txt"


__logs_file_path = get_log_path()


def print_lg(*msgs: str | dict, end: str = "\n", pretty: bool = False, flush: bool = True, from_critical: bool = False) -> None:
    '''
    Function to log and print. **Note that, `end` and `flush` parameters are ignored if `pretty = True`**
    '''
    try:
        for message in msgs:
            pprint(message) if pretty else print(message, end=end, flush=flush)
            with open(__logs_file_path, 'a+', encoding="utf-8") as file:
                file.write(str(message) + end)
    except Exception as e:
        trail = f'Skipped saving this message: "{message}" to log.txt!' if from_critical else "We'll try one more time to log..."
        alert(f"log.txt in {logs_folder_path} is open or is occupied by another program! Please close it! {trail}", "Failed Logging")
        if not from_critical:
            critical_error_log("Log.txt is open or is occupied by another program!", e)
#>

__dom_log_path = get_log_path().replace("log.txt", f"dom_session_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log")

def log_dom_action(action: str, details: str = "") -> None:
    '''
    Dedicated logger for tracking what the bot reads and clicks in the DOM.
    '''
    try:
        timestamp = datetime.now().strftime('%H:%M:%S')
        log_line = f"[{timestamp}] [{action}] {details}"
        # Print to stdout so it syncs with the Web UI Activity log
        print(log_line, flush=True)
        # Write to the dedicated DOM log file
        with open(__dom_log_path, 'a+', encoding="utf-8") as file:
            file.write(log_line + "\n")
    except Exception:
        pass


def buffer(speed: int=0) -> None:
    '''
    Function to wait within a period of selected random range.
    * Will not wait if input `speed <= 0`
    * Will wait within a random range of 
      - `0.6 to 1.0 secs` if `1 <= speed < 2`
      - `1.0 to 1.8 secs` if `2 <= speed < 3`
      - `1.8 to speed secs` if `3 <= speed`
    '''
    if speed<=0:
        return
    elif speed <= 1 and speed < 2:
        return sleep(randint(6,10)*0.1)
    elif speed <= 2 and speed < 3:
        return sleep(randint(10,18)*0.1)
    else:
        return sleep(randint(18,round(speed)*10)*0.1)
    

def manual_login_retry(is_logged_in: callable, timeout: int = 60) -> None:
    '''
    Function to wait for manual login automatically.
    '''
    print_lg(f"Waiting up to {timeout} seconds for manual login...")
    for _ in range(timeout):
        if is_logged_in():
            print_lg("Detected successful manual login!")
            return
        sleep(1)
    print_lg("Manual login timeout reached. Proceeding anyway (may fail).")


def calculate_date_posted(time_string: str) -> datetime | None:
    '''
    Turn a LinkedIn "posted" phrase like "3 days ago" into an approximate datetime.
    Returns None when the phrase can't be understood. Months and years are
    approximated as 30 and 365 days respectively.
    '''
    import re
    match = re.search(r'(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago',
                      time_string.strip(), re.IGNORECASE)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    spans = {
        'second': timedelta(seconds=amount),
        'minute': timedelta(minutes=amount),
        'hour': timedelta(hours=amount),
        'day': timedelta(days=amount),
        'week': timedelta(weeks=amount),
        'month': timedelta(days=amount * 30),
        'year': timedelta(days=amount * 365),
    }
    delta = spans.get(unit)
    return datetime.now() - delta if delta else None


def convert_to_lakhs(value: str) -> str:
    '''
    Converts str value to lakhs, no validations are done except for length and stripping.
    Examples:
    * "100000" -> "1.00"
    * "101,000" -> "10.1," Notice ',' is not removed 
    * "50" -> "0.00"
    * "5000" -> "0.05" 
    '''
    value = value.strip()
    l = len(value)
    if l > 0:
        if l > 5:
            value = value[:l-5] + "." + value[l-5:l-3]
        else:
            value = "0." + "0"*(5-l) + value[:2]
    return value


def anonymize_text(text: str) -> str:
    '''
    Replaces sensitive personal details in the resume with dummy placeholder info
    to protect user privacy when sending data to external LLMs.
    '''
    if not text:
        return ""
    import re
    # Replace email
    text = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', 'johndoe@example.com', text)
    # Replace phone numbers
    text = re.sub(r'\+?\d{1,4}[-.\s]?\(?\d{1,3}?\)?[-.\s]?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{1,9}', '+91 9999999999', text)
    # Replace LinkedIn, GitHub, Portfolio URLs
    text = re.sub(r'https?://(?:www\.)?linkedin\.com/in/[\w\.-]+/?', 'https://www.linkedin.com/in/johndoe/', text)
    text = re.sub(r'https?://(?:www\.)?github\.com/[\w\.-]+/?', 'https://github.com/johndoe/', text)
    text = re.sub(r'https?://(?:www\.)?[\w\.-]+\.github\.io/[\w\.-]+/?', 'https://johndoe.github.io/portfolio/', text)
    
    # Replace explicit names and personal values
    text = text.replace("Rakesh Kumar", "John Doe")
    text = text.replace("Rakesh", "John")
    text = text.replace("rakeshkumarjnv7364@gmail.com", "johndoe@example.com")
    text = text.replace("6377003472", "9999999999")
    return text


def convert_to_json(data) -> dict:
    '''
    Convert input string to JSON. Automatically strips markdown code fences
    (e.g., ```json ... ```) and extracts JSON blocks if conversational text is present.
    '''
    import re
    if not isinstance(data, str):
        try:
            data = str(data)
        except Exception:
            return {"error": "Input is not a string and cannot be converted to one.", "data": data}
            
    cleaned = data.strip()
    cleaned = re.sub(r"^```[a-z]*\n?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n?```$", "", cleaned)
    cleaned = cleaned.strip()

    try:
        result_json = json.loads(cleaned)
        return result_json
    except json.JSONDecodeError:
        # Fallback: search for first brace/bracket pattern to isolate JSON from conversational text
        match = re.search(r"(\{.*\}|\[.*\])", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        return {"error": "Unable to parse the response as JSON", "data": data}


def truncate_for_csv(data, max_length: int = 131000, suffix: str = "...[TRUNCATED]") -> str:
    '''
    Coerce any value to a string that's safe to write into a CSV cell, shortening it
    (with a marker suffix) if it would exceed max_length. Never raises.
    '''
    try:
        text = "" if data is None else str(data)
        if len(text) <= max_length:
            return text
        return text[:max_length - len(suffix)] + suffix
    except Exception as e:
        return f"[could not stringify value: {e}]"


