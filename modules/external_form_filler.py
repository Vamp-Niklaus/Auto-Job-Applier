import os
import time
import json
import re
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import Select

def resolve_field_value(client, user_config: dict, label_text: str, field_type: str, options: list, rules: dict, rules_path: str) -> str:
    '''
    Looks up a cached answer from rules, or queries the AI client to solve the field
    at runtime, then persists the learned rule in config/external_rules.json.
    '''
    label_clean = label_text.strip().lower()
    
    # 1. Lookup cached mapping in rules
    if label_clean in rules:
        return rules[label_clean]
        
    # Also try prefix/fuzzy matching in rules
    for k, v in rules.items():
        if k in label_clean or label_clean in k:
            return v

    # 2. On miss, query the AI Client if available
    if not client:
        return None

    try:
        from modules.ai.prompts import ai_field_resolution_prompt
        from modules.helpers import convert_to_json
        
        personals = user_config.get("personals", {})
        questions = user_config.get("questions", {})
        
        # Prepare applicant profile data
        profile_data = {
            "name": f"{personals.get('first_name', '')} {personals.get('last_name', '')}".strip() or "John Doe",
            "email": user_config.get("secrets", {}).get("username", "") or "johndoe@example.com",
            "phone": personals.get("phone_number", "") or "9999999999",
            "location": f"{personals.get('current_city', '')}, {personals.get('state', '')}, {personals.get('country', '')}".strip(", ") or "Noida, India",
            "sponsorship_needed": "Yes" if "citizen" not in (questions.get("us_citizenship") or "").lower() else "No",
            "desired_salary": str(questions.get("desired_salary", "")),
            "notice_period": str(questions.get("notice_period", "")),
            "resume_highlights": (questions.get("linkedin_headline", "") or "Software Engineer")
        }
        
        prompt = ai_field_resolution_prompt.format(
            name=profile_data["name"],
            email=profile_data["email"],
            phone=profile_data["phone"],
            location=profile_data["location"],
            sponsorship_needed=profile_data["sponsorship_needed"],
            desired_salary=profile_data["desired_salary"],
            notice_period=profile_data["notice_period"],
            resume_highlights=profile_data["resume_highlights"],
            field_label=label_text,
            field_type=field_type,
            field_options=str(options)
        )
        
        active_client = client.get_next() if hasattr(client, "get_next") else client
        if active_client:
            response = active_client.model.invoke(prompt)
            text = response.text if hasattr(response, "text") else getattr(response, "content", str(response))
            result = convert_to_json(text.strip())
            answer = result.get("answer")
            
            if answer:
                # 3. Cache the newly learned rule in memory and save to disk
                rules[label_clean] = answer
                try:
                    os.makedirs(os.path.dirname(rules_path), exist_ok=True)
                    with open(rules_path, "w") as f:
                        json.dump({"field_mappings": rules}, f, indent=2)
                except Exception as err:
                    print(f"Failed to save rules to disk: {err}")
                return answer
    except Exception as e:
        print(f"Runtime AI field resolution failed: {e}")
        
    return None

def fill_external_form(driver: WebDriver, user_config: dict, client=None) -> bool:
    '''
    A smart, self-healing form-filler that scans the active external webpage,
    autofills standard applicant fields, and uses AI at runtime to solve and cache
    rules for unknown fields (dropdowns, inputs, checkboxes).
    '''
    try:
        personals = user_config.get("personals", {})
        questions = user_config.get("questions", {})
        search_cfg = user_config.get("search", {})
        
        # Load local rules database
        rules_path = "config/external_rules.json"
        rules = {}
        if os.path.exists(rules_path):
            try:
                with open(rules_path, "r") as f:
                    rules = json.load(f).get("field_mappings", {})
            except:
                pass

        # Standard field values
        first_name = personals.get("first_name", "")
        last_name = personals.get("last_name", "")
        phone = personals.get("phone_number", "")
        email = user_config.get("secrets", {}).get("username", "")
        linkedin = questions.get("linkedIn", "")
        github = questions.get("website", "")
        password = search_cfg.get("external_apply_password", "")
        resume_path = questions.get("default_resume_path", "")
        
        if resume_path and not os.path.isabs(resume_path):
            resume_path = os.path.abspath(resume_path)

        # 1. Fill Text Inputs & Textareas
        inputs = driver.find_elements(By.XPATH, "//input[@type='text' or @type='email' or @type='tel' or not(@type)] | //textarea")
        for inp in inputs:
            try:
                if not inp.is_displayed() or not inp.is_enabled():
                    continue
                val = inp.get_attribute("value") or ""
                if val.strip():
                    continue
                
                name_attr = (inp.get_attribute("name") or "").lower()
                id_attr = (inp.get_attribute("id") or "").lower()
                placeholder = (inp.get_attribute("placeholder") or "").lower()
                aria_label = (inp.get_attribute("aria-label") or "").lower()
                
                label_text = ""
                try:
                    if id_attr:
                        label_el = driver.find_element(By.XPATH, f"//label[@for='{id_attr}']")
                        label_text = label_el.text or ""
                except:
                    pass
                
                indicators = f"{name_attr} {id_attr} {placeholder} {aria_label} {label_text}".lower()
                
                # Fill standard fields first
                if "first" in indicators and "name" in indicators:
                    inp.send_keys(first_name)
                elif "last" in indicators and "name" in indicators:
                    inp.send_keys(last_name)
                elif "name" in indicators and not ("company" in indicators or "school" in indicators):
                    inp.send_keys(f"{first_name} {last_name}".strip())
                elif "email" in indicators:
                    inp.send_keys(email)
                elif "phone" in indicators or "mobile" in indicators or "contact" in indicators:
                    inp.send_keys(phone)
                elif "linkedin" in indicators:
                    inp.send_keys(linkedin)
                elif "github" in indicators:
                    inp.send_keys(github)
                elif "portfolio" in indicators or "website" in indicators:
                    inp.send_keys(github)
                else:
                    # Self-healing: Resolve unknown input field using AI
                    resolved_val = resolve_field_value(client, user_config, label_text or placeholder or name_attr, "text", [], rules, rules_path)
                    if resolved_val:
                        inp.send_keys(resolved_val)
            except Exception:
                pass

        # 2. Fill Password Fields
        passwords = driver.find_elements(By.XPATH, "//input[@type='password']")
        for pw in passwords:
            try:
                if pw.is_displayed() and pw.is_enabled() and password:
                    pw.send_keys(password)
            except Exception:
                pass

        # 3. Handle File Uploads
        if resume_path and os.path.exists(resume_path):
            file_inputs = driver.find_elements(By.XPATH, "//input[@type='file']")
            for f_inp in file_inputs:
                try:
                    name_attr = (f_inp.get_attribute("name") or "").lower()
                    id_attr = (f_inp.get_attribute("id") or "").lower()
                    indicators = f"{name_attr} {id_attr}"
                    if "resume" in indicators or "cv" in indicators or len(file_inputs) == 1:
                        f_inp.send_keys(resume_path)
                        time.sleep(2)
                except Exception:
                    pass

        # 4. Handle Checkboxes
        checkboxes = driver.find_elements(By.XPATH, "//input[@type='checkbox']")
        for cb in checkboxes:
            try:
                name_attr = (cb.get_attribute("name") or "").lower()
                id_attr = (cb.get_attribute("id") or "").lower()
                indicators = f"{name_attr} {id_attr}"
                if "consent" in indicators or "privacy" in indicators or "terms" in indicators:
                    if not cb.is_selected():
                        cb.click()
            except Exception:
                pass

        # 5. Handle Select Dropdowns (Static & Self-Healing Dropdowns)
        selects = driver.find_elements(By.XPATH, "//select")
        for sel in selects:
            try:
                if not sel.is_displayed() or not sel.is_enabled():
                    continue
                
                select_obj = Select(sel)
                try:
                    curr_val = select_obj.first_selected_option.text
                    if curr_val and "select" not in curr_val.lower():
                        continue
                except:
                    pass
                
                name_attr = (sel.get_attribute("name") or "").lower()
                id_attr = (sel.get_attribute("id") or "").lower()
                aria_label = (sel.get_attribute("aria-label") or "").lower()
                
                label_text = ""
                try:
                    if id_attr:
                        label_el = driver.find_element(By.XPATH, f"//label[@for='{id_attr}']")
                        label_text = label_el.text or ""
                except:
                    pass
                
                indicators = f"{name_attr} {id_attr} {aria_label} {label_text}".lower()
                options = [opt.text for opt in select_obj.options]
                
                # Check static mappings first
                selected = False
                if "sponsor" in indicators or "visa" in indicators or "right to work" in indicators or "authorized" in indicators:
                    for opt in options:
                        opt_lower = opt.lower()
                        if "require" in indicators and "yes" in opt_lower:
                            select_obj.select_by_visible_text(opt)
                            selected = True
                            break
                        elif "authorized" in indicators and "no" in opt_lower:
                            select_obj.select_by_visible_text(opt)
                            selected = True
                            break
                        elif "sponsorship" in indicators and "yes" in opt_lower:
                            select_obj.select_by_visible_text(opt)
                            selected = True
                            break
                elif "consent" in indicators or "ai" in indicators:
                    for opt in options:
                        if "yes" in opt.lower():
                            select_obj.select_by_visible_text(opt)
                            selected = True
                            break
                elif "country" in indicators or "phone" in indicators or "code" in indicators:
                    for opt in options:
                        if "india" in opt.lower() or "+91" in opt:
                            select_obj.select_by_visible_text(opt)
                            selected = True
                            break
                
                # Self-healing fallback: Resolve select dropdown values using AI
                if not selected:
                    resolved_val = resolve_field_value(client, user_config, label_text or name_attr, "select", options, rules, rules_path)
                    if resolved_val:
                        for opt in options:
                            if resolved_val.strip().lower() in opt.lower() or opt.lower() in resolved_val.strip().lower():
                                select_obj.select_by_visible_text(opt)
                                break
            except Exception:
                pass

        return True
    except Exception as e:
        print(f"Error in fill_external_form: {e}")
        return False
