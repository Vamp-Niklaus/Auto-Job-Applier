import time
import re
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from modules.helpers import anonymize_text, convert_to_json
from modules.external_form_filler import fill_external_form

def classify_external_page(client, candidate_years: float, page_text: str) -> dict:
    '''
    Ask the AI client to classify the current state of the external page based on its text content.
    '''
    from modules.ai.prompts import ai_external_classify_prompt
    
    # Anonymize page text before sending to LLM
    page_text = anonymize_text(page_text)
    
    # Keep page text length reasonable to prevent token bloat
    if len(page_text) > 8000:
        page_text = page_text[:8000] + "... (truncated)"
        
    prompt = ai_external_classify_prompt.format(
        candidate_years=candidate_years,
        page_text=page_text
    )
    
    try:
        active_client = client.get_next() if hasattr(client, "get_next") else client
        if not active_client:
            return {"state": "FORM_PAGE", "reason": "No active client"}
        
        # Invoke LLM
        response = active_client.model.invoke(prompt)
        text = response.text if hasattr(response, "text") else getattr(response, "content", str(response))
        result = convert_to_json(text.strip())
        return result
    except Exception as e:
        print(f"Error during page classification: {e}")
        return {"state": "FORM_PAGE", "reason": f"Classification failed: {e}"}

def solve_external_step(driver: WebDriver, client, candidate_years: float, user_config: dict, step: int = 1) -> str:
    '''
    Recursively solves external application page steps (up to 4 steps deep).
    Returns 'applied', 'skipped', or 'manual_review'.
    '''
    from runAiBot import print_lg
    
    if step > 4:
        print_lg("Reached maximum navigation depth (4 steps) on external page. Stopping solver.")
        return "manual_review"

    print_lg(f"=== External Page Solver: Analyzing Step {step} ===")
    
    try:
        body_element = driver.find_element(By.TAG_NAME, "body")
        page_text = body_element.text or ""
    except Exception as e:
        print_lg(f"Failed to extract page text: {e}")
        return "manual_review"

    # Call LLM to classify state
    classification = classify_external_page(client, candidate_years, page_text)
    state = classification.get("state", "FORM_PAGE").upper()
    reason = classification.get("reason", "No reason provided")
    
    print_lg(f"AI classified page state as: [{state}] -> {reason}")

    if state == "CRITERIA_MISMATCH":
        print_lg(f"Skipping external application: {reason}")
        return "skipped"

    elif state == "SUBMITTED_SUCCESS":
        print_lg("External application successfully completed!")
        return "applied"

    elif state == "LOGIN_REGISTRATION":
        # Attempt to automate email submission or registration
        print_lg("Registration page detected. Filling credentials...")
        try:
            email_field = driver.find_element(By.XPATH, "//input[@type='email' or contains(@name, 'email') or contains(@id, 'email')]")
            if email_field.is_displayed() and email_field.is_enabled():
                email = user_config.get("secrets", {}).get("username", "")
                email_field.clear()
                email_field.send_keys(email)
                
                # Check for password
                try:
                    password_field = driver.find_element(By.XPATH, "//input[@type='password']")
                    password = user_config.get("search", {}).get("external_apply_password", "")
                    if password_field.is_displayed() and password_field.is_enabled() and password:
                        password_field.clear()
                        password_field.send_keys(password)
                except Exception:
                    pass
                
                # Click Submit/Next/Continue button
                submit_buttons = driver.find_elements(By.XPATH, "//button[contains(., 'Next') or contains(., 'Continue') or contains(., 'Submit') or @type='submit']")
                for btn in submit_buttons:
                    if btn.is_displayed() and btn.is_enabled():
                        btn.click()
                        print_lg("Clicked continue/submit registration.")
                        break
                
                time.sleep(3) # Let page load
                return solve_external_step(driver, client, candidate_years, user_config, step + 1)
        except Exception as err:
            print_lg(f"Failed to auto-solve registration step: {err}")
        return "manual_review"

    elif state == "DESCRIPTION_PAGE":
        print_lg("Navigation/Description page detected. Attempting to click primary 'Apply' button...")
        try:
            # Look for common apply/interested buttons
            apply_xpaths = [
                "//button[contains(., 'Apply') or contains(., 'Interested') or contains(., 'Start')]",
                "//a[contains(., 'Apply') or contains(., 'Interested') or contains(., 'Start')]",
                "//span[contains(., 'Apply') or contains(., 'Interested')]/parent::button",
                "//span[contains(., 'Apply') or contains(., 'Interested')]/parent::a"
            ]
            
            clicked = False
            for xpath in apply_xpaths:
                buttons = driver.find_elements(By.XPATH, xpath)
                for btn in buttons:
                    # Avoid clicking social share buttons or unrelated navigation links
                    btn_text = (btn.text or "").lower()
                    if "share" in btn_text or "email" in btn_text or "linkedin" in btn_text or "twitter" in btn_text:
                        continue
                    if btn.is_displayed() and btn.is_enabled():
                        # Click via JS for stability
                        driver.execute_script("arguments[0].click();", btn)
                        print_lg(f"Clicked navigation button: '{btn.text.strip()}'")
                        clicked = True
                        break
                if clicked:
                    break
            
            if clicked:
                time.sleep(4) # Wait for page load/transition
                return solve_external_step(driver, client, candidate_years, user_config, step + 1)
            else:
                print_lg("No clickable apply button found on description page.")
        except Exception as err:
            print_lg(f"Failed to click navigation button: {err}")
        return "manual_review"

    elif state == "FORM_PAGE":
        print_lg("Application form detected. Running autofill form filler...")
        fill_success = fill_external_form(driver, user_config)
        if fill_success:
            print_lg("Form fields successfully autofilled.")
        else:
            print_lg("Some form fields could not be filled automatically.")
        return "manual_review"

    return "manual_review"
