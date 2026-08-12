import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

options = Options()
options.add_argument("--headless")
driver = webdriver.Chrome(options=options)
driver.get("https://www.linkedin.com/login")
time.sleep(5)
print("Page title:", driver.title)
try:
    email = driver.find_element("xpath", "//input[@type='email' or @id='session_key' or @id='username']")
    print("Found email field:", email.get_attribute("outerHTML"))
except Exception as e:
    print("Email field exception:", e)

driver.save_screenshot("login_screen.png")
driver.quit()
