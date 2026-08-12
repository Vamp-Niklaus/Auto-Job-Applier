'''
LLM-powered stuck detection with a persistent JSON cache.

When the bot gets stuck (repeated exceptions, unexpected page states), call
`handle_stuck(driver, aiClient, situation_key, context)`.

  - First checks the JSON cache for a known solution to this situation.
  - If no cache hit, asks the LLM what to do and stores the result.
  - Returns a plain-English action string the caller can log/act on.

Cache lives at: logs/stuck_cache.json
'''

import json
import os
import re
import time

_CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "stuck_cache.json")

_STUCK_PROMPT = """
You are helping an automated LinkedIn job application bot that got stuck.

Situation:
{context}

Page URL: {url}

Visible page text (first 1000 chars):
{page_text}

What is the most likely reason the bot is stuck, and what single action should it take to recover?
Reply ONLY in this JSON format (no markdown, no code block):
{{"reason": "<short reason>", "action": "<one concrete action: click_escape | refresh_page | close_modal | wait_5s | skip_job | dismiss_dialog>", "cache_key": "<short slug for this situation type, e.g. modal_stuck_no_close_button>"}}
"""


def _load_cache() -> dict:
    try:
        if os.path.exists(_CACHE_PATH):
            with open(_CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_cache(cache: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def handle_stuck(driver, ai_client, situation_key: str, context: str = "", print_fn=print) -> str:
    '''
    Called when the bot is stuck.
    Returns an action string like "click_escape", "refresh_page", "skip_job", etc.
    Also logs the situation to the stuck cache for future runs.
    '''
    cache = _load_cache()

    # --- Cache hit: use stored solution ---
    if situation_key in cache:
        entry = cache[situation_key]
        action = entry.get("action", "skip_job")
        print_fn(f"[STUCK CACHE HIT] Situation '{situation_key}' -> action: '{action}' (hit #{entry.get('hits', 1)})")
        entry["hits"] = entry.get("hits", 1) + 1
        entry["last_seen"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save_cache(cache)
        return action

    # --- No cache: ask LLM ---
    action = "skip_job"
    try:
        url = "unknown"
        page_text = ""
        try:
            url = driver.current_url
            page_text = driver.find_element("xpath", "//body").text[:1000]
        except Exception:
            pass

        if ai_client is not None:
            from modules.helpers import convert_to_json
            from modules.ai.connections import _msg_text
            prompt = _STUCK_PROMPT.format(
                context=context or situation_key,
                url=url,
                page_text=page_text,
            )
            raw = _msg_text(ai_client.model.invoke(prompt)).strip()
            raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.IGNORECASE)
            raw = re.sub(r"\n?```$", "", raw)
            print_fn(f"[STUCK LLM] Raw response: {raw}")
            data = convert_to_json(raw)
            action = str(data.get("action", "skip_job"))
            reason = str(data.get("reason", ""))
            cache_key = str(data.get("cache_key", situation_key))
            print_fn(f"[STUCK LLM] '{situation_key}' -> reason: '{reason}' -> action: '{action}'")

            cache[cache_key] = {
                "situation_key": situation_key,
                "reason": reason,
                "action": action,
                "hits": 1,
                "first_seen": time.strftime("%Y-%m-%d %H:%M:%S"),
                "last_seen": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            _save_cache(cache)
        else:
            print_fn(f"[STUCK] AI off. Defaulting to 'skip_job' for: {situation_key}")
    except Exception as e:
        print_fn(f"[STUCK] LLM error: {e}. Defaulting to 'skip_job'.")

    return action


def execute_stuck_action(driver, action: str, actions_obj=None, print_fn=print) -> None:
    '''Execute the recovery action returned by handle_stuck().'''
    print_fn(f"[STUCK] Executing recovery: '{action}'")
    try:
        if action == "click_escape":
            from selenium.webdriver.common.keys import Keys
            if actions_obj:
                actions_obj.send_keys(Keys.ESCAPE).perform()
            else:
                driver.find_element("xpath", "//body").send_keys(Keys.ESCAPE)
        elif action == "refresh_page":
            driver.refresh()
            time.sleep(3)
        elif action in ("close_modal", "dismiss_dialog"):
            from selenium.webdriver.common.keys import Keys
            for xpath in [
                "//button[@aria-label='Dismiss']",
                "//button[contains(@class,'artdeco-modal__dismiss')]",
                "//button[normalize-space()='Discard']",
                "//button[normalize-space()='Cancel']",
                "//button[@aria-label='Cancel']",
            ]:
                try:
                    driver.find_element("xpath", xpath).click()
                    return
                except Exception:
                    pass
            if actions_obj:
                actions_obj.send_keys(Keys.ESCAPE).perform()
        elif action == "wait_5s":
            time.sleep(5)
        # "skip_job" = caller continues to next job
    except Exception as e:
        print_fn(f"[STUCK] Recovery '{action}' failed: {e}")
