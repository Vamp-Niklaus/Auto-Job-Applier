from selenium.common.exceptions import SessionNotCreatedException
try:
    raise SessionNotCreatedException("Chrome profile is locked by another process.")
except SessionNotCreatedException as e:
    print("Caught SessionNotCreatedException")
except Exception as e:
    print("Caught Exception")
