import os
import re
import sys
import io
import time
import traceback
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select
from selenium.webdriver.remote.webdriver import WebDriver
from modules.helpers import anonymize_text

# System prompt guiding the AI to output clean Python Selenium snippets
dynamic_selenium_prompt = """
You are an advanced, self-correcting browser automation agent.
You have control over a Selenium Webdriver instance named `driver`.
Based on the applicant's profile and the visible interactive elements, write a Python script to fill fields, choose select options, or click buttons to progress or submit the form.

Applicant Profile:
Name: {name}
Email: {email}
Phone: {phone}
Location: {location}
Sponsorship needed: {sponsorship}
Desired Salary: {desired_salary}
Notice Period: {notice_period}
Resume Path: {resume_path}
Default Password for accounts: {password}
Resume details: {resume_highlights}

Current Page URL: {url}

Visible Interactive Elements on Page:
{dom_summary}

Execution Log & History:
{history_str}

Rules:
1. Output ONLY executable Python code enclosed inside a single ```python ... ``` code block. Do NOT include markdown text outside the code block.
2. You can use standard libraries and Selenium objects which are pre-imported: `driver`, `By`, `Keys`, `Select`, `time`.
3. If you find file inputs for Resume/CV, use the absolute path: r"{resume_path}".
4. If you believe the form has been successfully completed or submitted (e.g., you see "Thank you", "Application received", "Success", etc.), write: print("APPLIED_SUCCESS") in your code.
5. Make your code robust: wait for elements to be interactable, scroll into view if necessary, and use try-except blocks for optional steps.
"""

def get_cleaned_dom_summary(driver: WebDriver) -> str:
    '''
    Extracts visible interactive elements in a token-friendly format.
    '''
    dom_lines = []
    try:
        # Scan inputs, select lists, buttons, textareas, and active links
        elements = driver.find_elements(By.XPATH, "//*[self::input or self::select or self::button or self::textarea or self::a or @role='button']")
        for i, el in enumerate(elements):
            try:
                if not el.is_displayed() or not el.is_enabled():
                    continue
                
                tag = el.tag_name
                type_attr = el.get_attribute("type") or ""
                id_attr = el.get_attribute("id") or ""
                name_attr = el.get_attribute("name") or ""
                placeholder = el.get_attribute("placeholder") or ""
                aria_label = el.get_attribute("aria-label") or ""
                text = (el.text or "").strip()
                
                # Fetch sibling/parent label if available
                label_text = ""
                if id_attr:
                    try:
                        label_el = driver.find_element(By.XPATH, f"//label[@for='{id_attr}']")
                        label_text = (label_el.text or "").strip()
                    except:
                        pass
                
                # Render representation
                desc = f"Index {i} | <{tag} type='{type_attr}' id='{id_attr}' name='{name_attr}' placeholder='{placeholder}' aria-label='{aria_label}'"
                if label_text:
                    desc += f" label='{label_text}'"
                desc += f">{text}</{tag}>"
                
                # Skip duplicate links or empty generic tags
                if tag == "a" and not text:
                    continue
                    
                dom_lines.append(desc)
            except:
                pass
    except Exception as e:
        dom_lines.append(f"Failed to scan DOM elements: {e}")
        
    return "\n".join(dom_lines[:150]) # Cap at 150 elements to prevent context bloat

def execute_generated_code(driver: WebDriver, code_str: str) -> tuple[str | None, str]:
    '''
    Executes generated Python code inside a controlled local namespace.
    Returns (error_traceback, stdout_output).
    '''
    # Capture print outputs
    old_stdout = sys.stdout
    captured_output = io.StringIO()
    sys.stdout = captured_output
    
    error_tb = None
    try:
        # Strip python markdown ticks
        code_clean = ""
        match = re.search(r"```python\s*(.*?)\s*```", code_str, re.DOTALL | re.IGNORECASE)
        if match:
            code_clean = match.group(1)
        else:
            code_clean = code_str.strip()
            # Handle cases where ticks exist but without word python
            code_clean = code_clean.replace("```", "")
            
        namespace = {
            "driver": driver,
            "By": By,
            "Keys": Keys,
            "Select": Select,
            "time": time
        }
        
        # Run code block
        exec(code_clean, globals(), namespace)
    except Exception as e:
        error_tb = traceback.format_exc()
    finally:
        sys.stdout = old_stdout
        
    return error_tb, captured_output.getvalue()

def run_dynamic_agent_loop(driver: WebDriver, client, user_config: dict) -> str:
    '''
    Self-programming loop: queries the LLM for custom Selenium code,
    runs it, and auto-corrects on failure up to 3 times.
    '''
    from runAiBot import print_lg
    
    print_lg("\n🤖 Starting Dynamic Agent Self-Programming Loop...")
    
    personals = user_config.get("personals", {})
    questions = user_config.get("questions", {})
    search_cfg = user_config.get("search", {})
    
    # User profile formatting
    profile = {
        "name": f"{personals.get('first_name', '')} {personals.get('last_name', '')}".strip() or "Candidate",
        "email": user_config.get("secrets", {}).get("username", "") or "candidate@example.com",
        "phone": personals.get("phone_number", "") or "9999999999",
        "location": f"{personals.get('current_city', '')}, {personals.get('state', '')}, {personals.get('country', '')}".strip(", ") or "India",
        "sponsorship": "Yes" if "citizen" not in (questions.get("us_citizenship") or "").lower() else "No",
        "desired_salary": str(questions.get("desired_salary", "")),
        "notice_period": str(questions.get("notice_period", "")),
        "resume_path": os.path.abspath(questions.get("default_resume_path", "")) if questions.get("default_resume_path") else "",
        "password": search_cfg.get("external_apply_password", "secure_password_123"),
        "resume_highlights": questions.get("linkedin_headline", "Software Engineer")
    }

    history_log = []
    
    for attempt in range(1, 4):
        print_lg(f"\n--- Dynamic Code Generation Attempt {attempt}/3 ---")
        
        # 1. Fetch current DOM summary
        dom_summary = get_cleaned_dom_summary(driver)
        dom_summary_anonymized = anonymize_text(dom_summary)
        
        history_str = "\n".join(history_log) if history_log else "No actions performed yet."
        
        # Compile prompt
        prompt = dynamic_selenium_prompt.format(
            name=profile["name"],
            email=profile["email"],
            phone=profile["phone"],
            location=profile["location"],
            sponsorship=profile["sponsorship"],
            desired_salary=profile["desired_salary"],
            notice_period=profile["notice_period"],
            resume_path=profile["resume_path"],
            password=profile["password"],
            resume_highlights=profile["resume_highlights"],
            url=driver.current_url,
            dom_summary=dom_summary_anonymized,
            history_str=history_str
        )
        
        # Invoke LLM
        active_client = client.get_next() if hasattr(client, "get_next") else client
        if not active_client:
            print_lg("No active LLM client available for dynamic code generation.")
            return "manual_review"
            
        try:
            print_lg("Requesting Selenium script from LLM...")
            response = active_client.model.invoke(prompt)
            code_candidate = response.text if hasattr(response, "text") else getattr(response, "content", str(response))
            
            print_lg(f"\n--- Code Generated by LLM ---\n{code_candidate}\n-----------------------------")
            
            # Execute code snippet
            error_tb, stdout_log = execute_generated_code(driver, code_candidate)
            
            if error_tb:
                print_lg(f"❌ Execution failed with traceback:\n{error_tb}")
                history_log.append(f"Attempt {attempt} failed.\nGenerated Code: {code_candidate}\nTraceback/Error: {error_tb}")
                buffer_time = 2
                time.sleep(buffer_time)
            else:
                print_lg("✅ Code executed successfully without uncaught exceptions.")
                print_lg(f"Stdout log: {stdout_log}")
                
                # Check for success completion flags
                if "APPLIED_SUCCESS" in stdout_log:
                    print_lg("Submission confirmation signal detected from code execution.")
                    return "applied"
                    
                # Success on this step, exit the loop and proceed to next step
                return "manual_review"
                
        except Exception as api_err:
            print_lg(f"Error during prompt invocation/execution: {api_err}")
            history_log.append(f"Attempt {attempt} failed on invocation error: {api_err}")
            
    print_lg("Reached maximum dynamic execution retries (3 attempts). Handing over control.")
    return "manual_review"
