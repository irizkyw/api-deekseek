import os
import sys
import time
import json
from pathlib import Path
from DrissionPage import ChromiumPage, ChromiumOptions

def main():
    print("Opening browser to obtain DeepSeek cookies...")
    print("Please solve any Cloudflare Turnstile challenges in the browser window.")
    
    options = ChromiumOptions().auto_port()
    if os.name != 'nt':
        options.set_paths(browser_path="/usr/bin/google-chrome")
        DOCKER_MODE = os.getenv("DOCKERMODE", "false").lower() == "true"
        if DOCKER_MODE:
            options.set_argument("--no-sandbox")
            options.set_argument("--disable-gpu")
            options.headless(True)
    else:
        options.headless(False)

    driver = ChromiumPage(addr_or_opts=options)
    try:
        driver.get("https://chat.deepseek.com")
        
        # Wait up to 60 seconds for cookies to contain cf_clearance
        cf_clearance_found = False
        for _ in range(60):
            try:
                cookies = driver.cookies()
                cookies_dict = {c.get("name", ""): c.get("value", "") for c in cookies}
                if 'cf_clearance' in cookies_dict and cookies_dict['cf_clearance'].strip():
                    cf_clearance_found = True
                    break
            except Exception:
                pass
            time.sleep(1)
            
        if not cf_clearance_found:
            print("Error: cf_clearance cookie not found. Please refresh or solve the challenge in the browser window.")
            sys.exit(1)
            
        cookies_dict = {c.get("name", ""): c.get("value", "") for c in driver.cookies()}
        user_agent = driver.user_agent
        
        cookie_data = {
            'cookies': cookies_dict,
            'user_agent': user_agent
        }
        
        cookies_path = Path(__file__).parent / 'cookies.json'
        with open(cookies_path, 'w', encoding='utf-8') as f:
            json.dump(cookie_data, f, indent=4, ensure_ascii=False)
            
        print(f"Successfully saved cookies to {cookies_path}!")
        
    except Exception as e:
        print(f"Error getting cookies: {e}")
        sys.exit(1)
    finally:
        try:
            driver.quit()
        except:
            pass

if __name__ == "__main__":
    main()