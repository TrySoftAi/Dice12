import streamlit as st
import json

# --- Streamlit Configuration (MUST be first) ---
st.set_page_config(page_title="Dice.com Job Application Bot", page_icon="🤖", layout="wide")

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.os_manager import ChromeType # For specifying Chromium
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException, ElementClickInterceptedException
import time
import traceback
import logging
import gspread
from google.oauth2.service_account import Credentials # Using google-auth for service account
from datetime import datetime
import pytz

# --- Basic Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- SPEED CONFIGURATION ---
ACTION_DELAY = 1.5 # You can adjust this

# --- GOOGLE SHEETS FUNCTION ---
def log_to_google_sheet(worksheet, job_title):
    """Logs a successful application to the specified Google Sheet."""
    try:
        pakistan_tz = pytz.timezone('Asia/Karachi')
        current_time_pkt = datetime.now(pakistan_tz).strftime('%Y-%m-%d %H:%M:%S')
        row = [current_time_pkt, job_title, "Done"]
        worksheet.append_row(row)
        logging.info(f"Successfully logged '{job_title}' to Google Sheets.")
    except Exception as e:
        logging.error(f"Failed to log to Google Sheets: {e}")
        logging.error(traceback.format_exc())

# Modified to accept email and password as parameters
def login_to_dice(driver, dice_email_param, dice_password_param):
    """Performs a full two-step login to Dice.com."""
    logging.info(f"Initiating login to Dice.com with email: {dice_email_param[:5]}...") # Log part of email for privacy
    driver.get("https://www.dice.com/dashboard/login")
    time.sleep(2) # Allow initial page elements (like cookie banners) to load

    try:
        # Attempt to handle cookie consent / CMP wrapper
        WebDriverWait(driver, 7).until(
            EC.visibility_of_element_located((By.ID, "cmpwrapper"))
        )
        logging.info("CMP wrapper (cookie consent) detected.")
        
        # TODO: USER - You MUST inspect Dice.com's cookie banner and find the correct selector for its "Accept" button.
        # The selectors below are common examples and might not work for Dice.
        possible_accept_selectors = [
            (By.ID, "onetrust-accept-btn-handler"), # Common ID for OneTrust
            (By.XPATH, "//button[contains(translate(., 'ACCEPPTALL', 'acceptall'), 'accept all')]"),
            (By.XPATH, "//button[contains(translate(., 'AGREE', 'agree'), 'agree')]"),
             (By.XPATH, "//*[@id='cmpwrapper']//button[contains(normalize-space(),'Accept')]")
        ]
        
        accepted_cookie_banner = False
        for selector_type, selector_value in possible_accept_selectors:
            try:
                accept_button = WebDriverWait(driver, 3).until(
                    EC.element_to_be_clickable((selector_type, selector_value))
                )
                logging.info(f"Attempting to click cookie consent accept button with: {selector_value}")
                accept_button.click()
                accepted_cookie_banner = True
                WebDriverWait(driver, 5).until(EC.invisibility_of_element_located((By.ID, "cmpwrapper")))
                logging.info("Cookie consent accepted and wrapper disappeared.")
                break 
            except: # Broad except as we're trying multiple selectors
                logging.debug(f"Cookie accept button with {selector_value} not found/clickable or wrapper didn't disappear.")
        if not accepted_cookie_banner:
            logging.warning("Could not click a cookie accept button, or wrapper did not disappear. Proceeding...")
    except TimeoutException:
        logging.info("CMP wrapper (cookie consent) not detected or already handled.")
    except Exception as e_cmp:
        logging.warning(f"An error occurred trying to handle CMP wrapper: {e_cmp}. Proceeding...")

    try:
        logging.info("Step 1: Entering email.")
        email_input = WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.NAME, "email")))
        email_input.send_keys(dice_email_param)
        time.sleep(ACTION_DELAY)

        logging.info("Clicking 'Continue' button (sign-in-button).")
        continue_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, "//button[@data-testid='sign-in-button']")))
        try:
            continue_button.click()
        except ElementClickInterceptedException:
            logging.warning("ElementClickInterceptedException on continue_button (sign-in-button), trying JavaScript click.")
            driver.execute_script("arguments[0].click();", continue_button)
        time.sleep(ACTION_DELAY)

        logging.info("Step 2: Entering password.")
        password_input = WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.NAME, "password")))
        password_input.send_keys(dice_password_param)
        time.sleep(ACTION_DELAY)

        logging.info("Clicking final 'Sign In' button (submit).")
        final_login_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, "//button[@type='submit']")))
        try:
            final_login_button.click()
        except ElementClickInterceptedException:
            logging.warning("ElementClickInterceptedException on final_login_button (submit), trying JavaScript click.")
            driver.execute_script("arguments[0].click();", final_login_button)
        
        time.sleep(3) # Increased wait after final login click for redirects
        logging.info(f"URL after login attempt: {driver.current_url}")

        # More robust check for successful login - look for an element unique to the logged-in dashboard
        # TODO: USER - Find a reliable element ID or XPath that ONLY appears on the main dashboard AFTER successful login
        # For example, a user profile name, a settings icon specific to logged-in state, etc.
        # Replace "user-profile-menu-button-id" with an actual reliable selector from Dice.com's dashboard.
        WebDriverWait(driver, 20).until(
             EC.presence_of_element_located((By.XPATH, "//*[contains(@data-testid,'header-user-menu')] | //*[contains(text(),'My Profile')] | //*[contains(text(),'Recommended For You')]"))
        )
        logging.info(f"Login appears successful. Landed on dashboard: {driver.current_url}")

    except (TimeoutException, NoSuchElementException) as e:
        logging.error(f"Login failed or did not reach expected dashboard state. Current URL: {driver.current_url}. Error: {e}")
        # driver.save_screenshot("debug_login_failure.png") # For local debugging if you run non-headless
        raise Exception(f"Login failed. Check credentials and if Dice.com page has changed. Current URL: {driver.current_url}")
    except Exception as e_global:
        logging.error(f"An unexpected error occurred during login: {e_global}. Current URL: {driver.current_url}")
        raise

def search_and_apply(driver, job_title, location, worksheet):
    """Searches for jobs, applies filters, and processes listings, logging successes."""
    logging.info(f"Starting job search for '{job_title}' in '{location}'.")
    
    # Assuming login was successful, we should be on or able to navigate to the correct search area.
    # If the login directly lands on a page with search, this driver.get() might be redundant or even harmful.
    # Let's test by trying to find search elements directly first, assuming login landed correctly.
    # If not, we might need driver.get("specific_search_page_url_if_known")
    # The previous logs showed it being redirected to /login?redirectURL=/dashboard/profiles even after driver.get("/dashboard")
    # This implies the session wasn't authenticated. If login_to_dice now ensures proper login, this part should work.

    logging.info(f"Current URL before attempting search: {driver.current_url}")
    if "login" in driver.current_url or "profiles" in driver.current_url and "dashboard" not in driver.current_url.split('?')[0]:
        logging.warning("It seems we are not on the main dashboard. Attempting to navigate to /dashboard again.")
        driver.get("https://www.dice.com/dashboard")
        time.sleep(3) # Wait for potential redirect
        logging.info(f"URL after re-navigating to /dashboard: {driver.current_url}")
        # Re-check if we are on a valid dashboard page
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.XPATH, "//*[contains(@data-testid,'header-user-menu')] | //*[contains(text(),'My Profile')] | //*[contains(text(),'Recommended For You')] | //input[@name='q']"))
            )
            logging.info(f"Successfully on a dashboard-like page for search. Current URL: {driver.current_url}")
        except TimeoutException:
            logging.error(f"Still not on expected dashboard after re-navigation. Current URL: {driver.current_url}")
            raise Exception("Failed to reach a usable Dice dashboard page for job searching.")

    logging.info("Locating search fields on the dashboard.")
    try:
        # TODO: USER - Verify these selectors based on the actual Dice.com dashboard after you log in manually.
        job_title_selector = (By.NAME, "q") 
        job_title_field = WebDriverWait(driver, 20).until(EC.visibility_of_element_located(job_title_selector))
        
        location_selector = (By.NAME, "location")
        location_field = WebDriverWait(driver, 10).until(EC.visibility_of_element_located(location_selector))
    except TimeoutException as e:
        logging.error(f"Timeout finding search input fields on {driver.current_url}. Page might have changed.")
        raise 

    job_title_field.clear()
    job_title_field.send_keys(job_title)
    time.sleep(0.5)
    location_field.clear()
    location_field.send_keys(location)
    time.sleep(0.5)

    logging.info("Clicking the main search button.")
    search_button_selector = (By.CSS_SELECTOR, "[data-testid='job-search-search-bar-search-button']")
    search_button = WebDriverWait(driver, 15).until(EC.element_to_be_clickable(search_button_selector))
    try:
        search_button.click()
    except ElementClickInterceptedException:
        logging.warning("ElementClickInterceptedException on search_button, trying JavaScript click.")
        driver.execute_script("arguments[0].click();", search_button)
    logging.info("Search initiated.")
    time.sleep(5) # Wait for search results
    # (The rest of search_and_apply: filters, job processing, pagination remains the same as your last good version)
    # Ensure those selectors are also checked if issues arise later in the flow.
    try:
        logging.info("Attempting to click 'All filters' button...")
        all_filters_button_selector = (By.XPATH, "//button[contains(., 'All filters')]")
        all_filters_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable(all_filters_button_selector))
        driver.execute_script("arguments[0].click();", all_filters_button) # JS click for robustness
        time.sleep(ACTION_DELAY)

        logging.info("Clicking the 'Easy Apply' filter...")
        easy_apply_selector = (By.XPATH, "//label[contains(., 'Easy apply')]")
        easy_apply_filter = WebDriverWait(driver, 15).until(EC.element_to_be_clickable(easy_apply_selector))
        easy_apply_filter.click()
        time.sleep(ACTION_DELAY)

        logging.info("Clicking the 'Remote' filter...")
        remote_filter_selector = (By.XPATH, "//label[contains(., 'Remote')]")
        remote_filter = WebDriverWait(driver, 15).until(EC.element_to_be_clickable(remote_filter_selector))
        remote_filter.click()
        time.sleep(ACTION_DELAY)

        logging.info("Closing the filter menu...")
        # TODO: USER - Find a more reliable selector for the filter panel's close button.
        close_button_selector = (By.CSS_SELECTOR, "button[data-testid='undefined-close-button']") 
        # Example alternative: (By.XPATH, "//button[@aria-label='Close panel' or @aria-label='Close modal' or @aria-label='Close']")
        close_button = WebDriverWait(driver, 15).until(EC.element_to_be_clickable(close_button_selector))
        close_button.click()
        logging.info("Filters applied and panel closed successfully.")

    except TimeoutException:
        logging.warning("Could not find or click an element in the filter panel. Proceeding with applied filters or default.")

    logging.info("Waiting for filtered job list to refresh...")
    time.sleep(3)
    page_number = 1
    while True:
        logging.info(f"--- Processing Page {page_number} ---")
        job_links_selector = (By.CSS_SELECTOR, "a[data-testid='job-search-job-detail-link']")
        try:
            WebDriverWait(driver, 10).until(EC.presence_of_all_elements_located(job_links_selector)) # presence_of_all_elements_located
        except TimeoutException:
            logging.info("No more job links found or page did not load as expected. Ending process for this search.")
            break 
        job_elements = driver.find_elements(job_links_selector[0], job_links_selector[1]) 
        job_count = len(job_elements)
        logging.info(f"Found {job_count} jobs on this page. Starting application process...")
        if job_count == 0:
            logging.info("No jobs found on this page to process.")
            # Check for "next" button even if no jobs, in case of empty intermediate pages
            pass # Will proceed to "next page" check
        original_window = driver.current_window_handle
        for i in range(job_count):
            job_name = "N/A"
            try:
                all_jobs_on_page = WebDriverWait(driver, 10).until(EC.presence_of_all_elements_located(job_links_selector))
                if i >= len(all_jobs_on_page):
                    logging.warning("Job list changed during processing. Ending loop for this page.")
                    break
                current_job_link = all_jobs_on_page[i]
                job_name = current_job_link.text or "N/A"
                logging.info(f"--- Processing Job '{job_name}' ({i + 1} of {job_count}, Page {page_number}) ---")
                driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});", current_job_link)
                time.sleep(0.5)
                current_job_link.click()
                WebDriverWait(driver, 10).until(EC.number_of_windows_to_be(2))
                for window_handle in driver.window_handles:
                    if window_handle != original_window:
                        driver.switch_to.window(window_handle)
                        break
                time.sleep(10) 
                try:
                    shadow_host = WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "apply-button-wc")))
                    shadow_root = shadow_host.shadow_root
                    easy_apply_button = shadow_root.find_element(By.CSS_SELECTOR, "button.btn.btn-primary")
                    driver.execute_script("arguments[0].click();", easy_apply_button)
                    next_button = WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn-next")))
                    next_button.click()
                    submit_button = WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn-next"))) 
                    submit_button.click()
                    logging.info(f"--- SUCCESS: Job '{job_name}' Submitted! ---")
                    log_to_google_sheet(worksheet, job_name)
                    time.sleep(ACTION_DELAY)
                except TimeoutException:
                    logging.warning(f"Job '{job_name}' is not an 'Easy Apply' job or failed to load elements in apply flow. Skipping.")
                finally:
                    if len(driver.window_handles) > 1:
                        driver.close()
                    driver.switch_to.window(original_window)
                    time.sleep(1)
            except StaleElementReferenceException:
                logging.error(f"Stale element error on job {i+1}. Page may have refreshed. Skipping.")
                continue
            except Exception as e:
                logging.error(f"An unexpected error occurred on job '{job_name}': {e}")
                logging.error(traceback.format_exc())
                if driver.current_window_handle != original_window and len(driver.window_handles) > 1:
                    driver.close()
                    driver.switch_to.window(original_window)
                continue
        try:
            logging.info("All jobs on this page processed. Looking for the 'Next' page button...")
            next_page_button_xpath = "//span[@aria-label='Next']/ancestor::button[not(@disabled)]"
            next_page_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, next_page_button_xpath)))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});", next_page_button)
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", next_page_button) # JS click for robustness
            logging.info("SUCCESS: Clicked 'Next' page. Waiting for new jobs to load...")
            time.sleep(10)
            page_number += 1
        except TimeoutException:
            logging.info("This is the last page. No 'Next' button found or it's disabled.")
            logging.info("✅ All jobs across all pages have been processed. Bot is finished.")
            break
        except Exception as e:
            logging.error(f"Could not navigate to the next page due to an error: {e}")
            logging.error(traceback.format_exc())
            break


def start_bot_task(job_title, location, dice_email_ui, dice_password_ui, spreadsheet_id_ui, status_placeholder):
    """Main bot task function"""
    worksheet = None
    try:
        status_placeholder.info("🔗 Connecting to Google Sheets...")
        if "google_credentials" not in st.secrets: # This key must match your Streamlit secret
            status_placeholder.error("❌ Google credentials not found in Streamlit Secrets. Please configure them in app settings.")
            logging.error("Google credentials not found in Streamlit Secrets.")
            return

        google_creds_dict = st.secrets["google_credentials"]
        scoped_credentials = Credentials.from_service_account_info(
            google_creds_dict,
            scopes=['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        )
        client = gspread.authorize(scoped_credentials)
        spreadsheet = client.open_by_key(spreadsheet_id_ui) # Uses spreadsheet_id from UI
        worksheet = spreadsheet.sheet1
        logging.info("SUCCESS: Connected to Google Sheets.")
        status_placeholder.success("✅ Connected to Google Sheets successfully.")

    except Exception as e:
        logging.error(f"Failed to connect to Google Sheets: {e}")
        logging.error(traceback.format_exc())
        status_placeholder.error(f"❌ Error connecting to Google Sheets: {e}")
        return

    status_placeholder.info(f"🚀 Starting Bot for: {job_title} in {location} using Dice email: {dice_email_ui[:5]}...") # Mask email
    driver = None
    try:
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920x1080")
        options.add_argument("--disable-features=VizDisplayCompositor")
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--disable-extensions")
        options.add_argument("--log-level=0")
        options.add_argument("--disable-notifications")
        options.add_experimental_option('excludeSwitches', ['enable-logging'])

        try:
            service = Service(ChromeDriverManager(chrome_type=ChromeType.CHROMIUM).install())
            driver = webdriver.Chrome(service=service, options=options)
        except Exception as e_driver:
            logging.error(f"Failed to initialize Chrome Driver: {e_driver}")
            status_placeholder.error(f"❌ Failed to initialize Chrome Driver: {e_driver}. Check logs.")
            return

        status_placeholder.info("🔐 Logging in to Dice.com...")
        login_to_dice(driver, dice_email_ui, dice_password_ui) # Pass UI credentials
        
        # login_to_dice will raise an exception if login fails fundamentally
        status_placeholder.success("✅ Login successful! Navigating to search...")
        
        search_and_apply(driver, job_title, location, worksheet) # Call search_and_apply

        status_placeholder.success("🎉 Bot has finished processing all pages.")
        logging.info("Process finished for all pages.")
    except Exception as e: # Catch exceptions from login_to_dice or search_and_apply
        status_placeholder.error(f"❌ A critical error occurred: {e}")
        logging.critical(f"A critical, unhandled error stopped the bot: {e}")
        logging.critical(traceback.format_exc())
    finally:
        if driver:
            driver.quit()
            logging.info("Browser closed.")

# --- Streamlit UI ---
st.title("🤖 Dice.com Job Application Bot")
st.markdown("---")

st.subheader("🎯 Job Search Criteria")
col1, col2 = st.columns(2)
with col1:
    job_title_ui = st.text_input("Enter job title:", placeholder="e.g., Software Engineer", key="job_title_ui")
with col2:
    location_ui = st.text_input("Enter location:", placeholder="e.g., New York, Remote", key="location_ui")

st.markdown("---")
st.subheader("🎲 Dice.com Credentials")
col3, col4 = st.columns(2)
with col3:
    dice_email_ui_input = st.text_input("Dice Email:", placeholder="your.email@example.com", key="dice_email_ui")
with col4:
    dice_password_ui_input = st.text_input("Dice Password:", type="password", key="dice_password_ui")

st.markdown("---")
st.subheader("📊 Google Sheet Configuration")
spreadsheet_id_ui_input = st.text_input("Google Spreadsheet ID:", value="1ML4bC7XVwQys-MR0TH8ujk5Fu3RtLxyUfJLC92Gzxqk", key="spreadsheet_id_ui")


st.markdown("---")

if st.button("🔍 Find and Apply for Jobs", type="primary", use_container_width=True):
    if not (job_title_ui.strip() and location_ui.strip() and
            dice_email_ui_input.strip() and dice_password_ui_input.strip() and
            spreadsheet_id_ui_input.strip()):
        st.error("❌ Please fill in all fields: Job Title, Location, Dice Email, Dice Password, and Spreadsheet ID.")
    else:
        status_placeholder = st.empty()
        try:
            start_bot_task(
                job_title_ui.strip(),
                location_ui.strip(),
                dice_email_ui_input.strip(), # These are now taken from UI
                dice_password_ui_input.strip(), # Password from UI
                spreadsheet_id_ui_input.strip(), # Spreadsheet ID from UI
                status_placeholder
            )
        except Exception as e: 
            st.error(f"❌ An error occurred during bot execution: {str(e)}")
            st.exception(e) # Shows full traceback in Streamlit UI

# Footer
st.markdown("---")
st.markdown("Google Service Account credentials for Sheets are loaded securely from Streamlit Secrets.")
