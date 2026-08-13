import os
import time
import json
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

# Helper Mock Client for testing without consuming API tokens
class MockAIClient:
    class MockModel:
        def invoke(self, prompt):
            class MockResponse:
                @property
                def text(self):
                    if "screening" in prompt.lower() or "protocol" in prompt.lower():
                        return '{"answer": "Yes", "reason": "User profile agrees to screening"}'
                    elif "programming language" in prompt.lower() or "favorite" in prompt.lower():
                        return '{"answer": "Python programming", "reason": "Candidate has extensive Python experience"}'
                    elif "remotely" in prompt.lower() or "feedback" in prompt.lower():
                        return '{"answer": "Excited", "reason": "User is excited about remote work"}'
                    return '{"answer": "Unknown", "reason": "No match"}'
            return MockResponse()
            
    def __init__(self):
        self.model = self.MockModel()
        
    def get_next(self):
        return self

def test_learning_flow():
    print("=== STARTING SELF-HEALING FORM FILLER TEST ===")
    
    # 1. Clean previous rules if any
    rules_path = "config/external_rules.json"
    if os.path.exists(rules_path):
        os.remove(rules_path)
        print("Cleared previous external rules file.")

    # 2. Setup mock config
    user_config = {
        "secrets": {
            "username": "rakeshkumarjnv7364@gmail.com"
        },
        "personals": {
            "first_name": "Rakesh",
            "last_name": "Kumar",
            "phone_number": "6377003472",
            "current_city": "Noida",
            "state": "Uttar Pradesh",
            "country": "India"
        },
        "questions": {
            "us_citizenship": "Indian Citizen"
        },
        "search": {
            "external_apply_password": "secure_password_123"
        }
    }

    # 3. Initialize Headless Chrome Driver
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    
    # Check if a custom chromedriver binary is specified or let selenium manager handle it
    driver = webdriver.Chrome(options=options)
    
    try:
        # Load local test page
        test_file_path = os.path.abspath("test_form.html")
        driver.get(f"file://{test_file_path}")
        print(f"Loaded test form page: {driver.current_url}")

        from modules.external_form_filler import fill_external_form
        mock_client = MockAIClient()

        # ---------------- ITERATION 1: No Cache (Triggers AI Resolution) ----------------
        print("\n--- Iteration 1: Running Form Filler (No Cache, AI queries active) ---")
        success = fill_external_form(driver, user_config, client=mock_client)
        assert success, "Form filler failed to execute"

        # Assert fields are filled correctly
        fn_val = driver.find_element(By.ID, "first_name").get_attribute("value")
        email_val = driver.find_element(By.ID, "email").get_attribute("value")
        
        screening_sel = Select(driver.find_element(By.ID, "screening_protocol")).first_selected_option.text
        hobby_sel = Select(driver.find_element(By.ID, "hobby_question")).first_selected_option.text
        feedback_val = driver.find_element(By.ID, "feedback_field").get_attribute("value")

        print(f"Filled First Name: {fn_val}")
        print(f"Filled Email: {email_val}")
        print(f"Selected Screening Protocol Option: '{screening_sel}'")
        print(f"Selected Programming Language Option: '{hobby_sel}'")
        print(f"Filled Feedback Text: '{feedback_val}'")

        assert fn_val == "Rakesh", "First name incorrect"
        assert email_val == "rakeshkumarjnv7364@gmail.com", "Email incorrect"
        assert "yes" in screening_sel.lower(), "AI failed to resolve screening protocol select box"
        assert "python" in hobby_sel.lower(), "AI failed to resolve programming language select box"
        assert feedback_val == "Excited", "AI failed to resolve feedback input field"

        # Assert rules are cached
        assert os.path.exists(rules_path), "Rules file config/external_rules.json was not created"
        with open(rules_path, "r") as f:
            rules = json.load(f).get("field_mappings", {})
        print(f"\nRules successfully written to {rules_path}:")
        print(json.dumps(rules, indent=2))
        
        assert len(rules) > 0, "No rules written to database"

        # ---------------- ITERATION 2: Using Cache (0 LLM Calls) ----------------
        print("\n--- Iteration 2: Resetting fields & running using Cached Rules database ---")
        driver.refresh()
        
        # Call form filler with client=None (disabling LLM completely)
        # If it fills correctly, it PROVES it is reading successfully from cache/rules database!
        success_cache = fill_external_form(driver, user_config, client=None)
        assert success_cache, "Form filler using cache failed to execute"

        screening_sel_cached = Select(driver.find_element(By.ID, "screening_protocol")).first_selected_option.text
        hobby_sel_cached = Select(driver.find_element(By.ID, "hobby_question")).first_selected_option.text
        feedback_val_cached = driver.find_element(By.ID, "feedback_field").get_attribute("value")

        print(f"Cached Screening Option: '{screening_sel_cached}'")
        print(f"Cached Programming Option: '{hobby_sel_cached}'")
        print(f"Cached Feedback Text: '{feedback_val_cached}'")

        assert "yes" in screening_sel_cached.lower(), "Cache failed to fill screening protocol dropdown"
        assert "python" in hobby_sel_cached.lower(), "Cache failed to fill programming language dropdown"
        assert feedback_val_cached == "Excited", "Cache failed to fill feedback input field"

        print("\n✅ SUCCESS: Self-healing, caching, and recovery successfully verified!")

    finally:
        driver.quit()
        if os.path.exists(rules_path):
            os.remove(rules_path)

if __name__ == "__main__":
    test_learning_flow()
