import os
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def fill_external_form(driver: WebDriver, user_config: dict) -> bool:
    '''
    A smart, lightweight form-filler that scans the active external webpage
    and attempts to autofill standard applicant fields, upload resumes,
    and enter passwords for account creation.
    '''
    try:
        personals = user_config.get("personals", {})
        questions = user_config.get("questions", {})
        search_cfg = user_config.get("search", {})
        
        # Gather inputs
        first_name = personals.get("first_name", "")
        last_name = personals.get("last_name", "")
        phone = personals.get("phone_number", "")
        email = user_config.get("secrets", {}).get("username", "")
        linkedin = questions.get("linkedIn", "")
        github = questions.get("website", "") # Fallback to portfolio
        password = search_cfg.get("external_apply_password", "")
        resume_path = questions.get("default_resume_path", "")
        
        # Verify absolute path for resume upload
        if resume_path and not os.path.isabs(resume_path):
            resume_path = os.path.abspath(resume_path)

        # 1. Fill Text Inputs & Textareas
        inputs = driver.find_elements(By.XPATH, "//input[@type='text' or @type='email' or @type='tel' or not(@type)] | //textarea")
        for inp in inputs:
            try:
                if not inp.is_displayed() or not inp.is_enabled():
                    continue
                
                # Check for existing value to avoid overwriting
                val = inp.get_attribute("value") or ""
                if val.strip():
                    continue
                
                name_attr = (inp.get_attribute("name") or "").lower()
                id_attr = (inp.get_attribute("id") or "").lower()
                placeholder = (inp.get_attribute("placeholder") or "").lower()
                aria_label = (inp.get_attribute("aria-label") or "").lower()
                
                # Match indicators
                indicators = f"{name_attr} {id_attr} {placeholder} {aria_label}"
                
                if "first" in indicators and "name" in indicators:
                    inp.send_keys(first_name)
                elif "last" in indicators and "name" in indicators:
                    inp.send_keys(last_name)
                elif "name" in indicators and not ("company" in indicators or "school" in indicators):
                    full_name = f"{first_name} {last_name}".strip()
                    inp.send_keys(full_name)
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
            except Exception:
                pass

        # 2. Fill Password Fields (Account Creation)
        passwords = driver.find_elements(By.XPATH, "//input[@type='password']")
        for pw in passwords:
            try:
                if pw.is_displayed() and pw.is_enabled() and password:
                    pw.send_keys(password)
            except Exception:
                pass

        # 3. Handle File Uploads (Resume)
        if resume_path and os.path.exists(resume_path):
            file_inputs = driver.find_elements(By.XPATH, "//input[@type='file']")
            for f_inp in file_inputs:
                try:
                    # SmartRecruiters/Greenhouse/Lever usually accept resume on file input
                    name_attr = (f_inp.get_attribute("name") or "").lower()
                    id_attr = (f_inp.get_attribute("id") or "").lower()
                    indicators = f"{name_attr} {id_attr}"
                    
                    # If it's a resume input, or just the first file input
                    if "resume" in indicators or "cv" in indicators or len(file_inputs) == 1:
                        f_inp.send_keys(resume_path)
                        time.sleep(2) # Give upload a moment
                except Exception:
                    pass

        # 4. Handle Checkboxes (Consent / Terms)
        checkboxes = driver.find_elements(By.XPATH, "//input[@type='checkbox']")
        for cb in checkboxes:
            try:
                name_attr = (cb.get_attribute("name") or "").lower()
                id_attr = (cb.get_attribute("id") or "").lower()
                indicators = f"{name_attr} {id_attr}"
                
                # Check privacy/consent checkboxes by default
                if "consent" in indicators or "privacy" in indicators or "terms" in indicators:
                    if not cb.is_selected():
                        cb.click()
            except Exception:
                pass

        # 5. Handle Select Dropdowns
        from selenium.webdriver.support.ui import Select
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
                        label_text = (label_el.text or "").lower()
                except:
                    pass
                
                indicators = f"{name_attr} {id_attr} {aria_label} {label_text}"
                options = [opt.text for opt in select_obj.options]
                
                # Visa / Sponsorship
                if "sponsor" in indicators or "visa" in indicators or "right to work" in indicators or "authorized" in indicators:
                    for opt in options:
                        opt_lower = opt.lower()
                        # User needs visa sponsorship (since they are Indian Citizen applying internationally)
                        if "require" in indicators and "yes" in opt_lower:
                            select_obj.select_by_visible_text(opt)
                            break
                        elif "authorized" in indicators and "no" in opt_lower:
                            select_obj.select_by_visible_text(opt)
                            break
                        elif "sponsorship" in indicators and "yes" in opt_lower:
                            select_obj.select_by_visible_text(opt)
                            break

                # Consent to AI
                elif "consent" in indicators or "ai" in indicators:
                    for opt in options:
                        if "yes" in opt.lower():
                            select_obj.select_by_visible_text(opt)
                            break

                # Phone Country Code
                elif "country" in indicators or "phone" in indicators or "code" in indicators:
                    for opt in options:
                        if "india" in opt.lower() or "+91" in opt:
                            select_obj.select_by_visible_text(opt)
                            break
            except Exception:
                pass

        return True
    except Exception as e:
        print(f"Error in fill_external_form: {e}")
        return False
