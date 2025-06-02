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
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
import time
import traceback
import logging
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import pytz

# --- Basic Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- SPEED CONFIGURATION ---
ACTION_DELAY = 1.5

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

def login_to_dice(driver, dice_email_param, dice_password_param):
    """Performs a full two-step login to Dice.com."""
    logging.info("Initiating full two-step login to Dice.com...")
    driver.get("https://www.dice.com/dashboard/login")
    try:
        logging.info("Step 1: Entering email.")
        email_input = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.NAME, "email")))
        email_input.send_keys(dice_email_param)
        time.sleep(ACTION_DELAY)

        logging.info("Clicking 'Continue' button.")
        continue_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, "//button[@data-testid='sign-in-button']")))
        continue_button.click()
        time.sleep(ACTION_DELAY)

        logging.info("Step 2: Entering password.")
        password_input = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.NAME, "password")))
        password_input.send_keys(dice_password_param)
        time.sleep(ACTION_DELAY)

        logging.info("Clicking final 'Sign In' button.")
        final_login_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, "//button[@type='submit']")))
        final_login_button.click()

        logging.info("Verifying login success by checking for dashboard URL...")
        # Wait for URL to contain 'dashboard' but NOT the login redirect that includes 'profiles' if that's an issue
        WebDriverWait(driver, 20).until(
            lambda d: "dashboard" in d.current_url and "profiles" not in d.current_url 
                      if "login" in d.current_url else "dashboard" in d.current_url
        )
        logging.info(f"Landed on URL: {driver.current_url} after login attempt.")
        time.sleep(ACTION_DELAY) # Allow page to settle
        logging.info("SUCCESS: Login verified (or at least past login page).")

    except (TimeoutException, NoSuchElementException):
        logging.error(f"A timeout or element-not-found error occurred during login. Current URL: {driver.current_url}")
        logging.error(traceback.format_exc())
        raise

def search_and_apply(driver, job_title, location, worksheet):
    """Searches for jobs, applies filters, and processes listings, logging successes."""
    logging.info(f"Starting job search for '{job_title}' in '{location}'.")
    
    # Attempt to navigate to a more specific search page or ensure dashboard is loaded
    # It seems after login, it might redirect to /dashboard/login?redirectURL=/dashboard/profiles
    # We need to get to the actual job search interface.
    # Let's try navigating to the base dashboard and then ensure we are on a page where search is possible.
    driver.get("https://www.dice.com/dashboard")
    logging.info(f"Navigated to /dashboard. Current URL: {driver.current_url}")
    time.sleep(2) # Give it a moment to redirect if it's going to

    # Add a wait for a known element on the *actual* job search dashboard
    # This is a placeholder - you need to find a real element on the page that indicates the search form is ready
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, "//*[contains(text(),'Recommended For You')] | //input[@name='q'] | //*[@data-testid='job-search-search-bar-search-button']")) 
            # The above tries to find common dashboard text, the old search input, or the search button
        )
        logging.info(f"Suspected dashboard / search page loaded. Current URL: {driver.current_url}")
    except TimeoutException:
        logging.error(f"Timeout waiting for main dashboard elements. Current URL: {driver.current_url}")
        # driver.save_screenshot("debug_dashboard_load_failed.png") # For local debugging
        raise Exception("Failed to load the expected Dice dashboard page for job searching.")


    logging.info("Locating search fields on the dashboard.")
    try:
        # TODO: USER - Verify this selector. Is 'name="q"' still correct for the job title input?
        # Or find a more robust selector e.g., by data-testid or a unique ID.
        job_title_selector = (By.NAME, "q") 
        # Alternative if 'q' is common: job_title_selector = (By.XPATH, "//input[@placeholder='Job title, skill, or company']")
        job_title_field = WebDriverWait(driver, 20).until(EC.visibility_of_element_located(job_title_selector))
        logging.info(f"Job title field found using {job_title_selector}")

        # TODO: USER - Verify this selector. Is 'name="location"' still correct for the location input?
        location_selector = (By.NAME, "location")
        # Alternative: location_selector = (By.XPATH, "//input[@placeholder='City, state, or zip code']")
        location_field = WebDriverWait(driver, 10).until(EC.visibility_of_element_located(location_selector))
        logging.info(f"Location field found using {location_selector}")

    except TimeoutException as e:
        logging.error(f"Timeout finding search fields. Page might have changed or not loaded correctly. Current URL: {driver.current_url}")
        # driver.save_screenshot("debug_search_fields_timeout.png") # Helpful for local debugging
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
    search_button.click()

    logging.info("Pausing for 5 seconds to let the results page load...")
    time.sleep(5)
    # ... (rest of the function as before)
    try:
        logging.info("Attempting to click 'All filters' button...")
        all_filters_button_selector = (By.XPATH, "//button[contains(., 'All filters')]")
        all_filters_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable(all_filters_button_selector))
        driver.execute_script("arguments[0].click();", all_filters_button)
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
        close_button_selector = (By.CSS_SELECTOR, "button[data-testid='undefined-close-button']") # This data-testid seems unstable
        # TODO: USER - Find a more reliable selector for the filter panel's close button.
        # Example: close_button_selector = (By.XPATH, "//div[@aria-label='Filter modal']//button[@aria-label='Close']")
        close_button = WebDriverWait(driver, 15).until(EC.element_to_be_clickable(close_button_selector))
        close_button.click()
        logging.info("Filters applied and panel closed successfully.")

    except TimeoutException:
        logging.warning("Could not find or click an element in the filter panel. Proceeding without all filters if some were applied.")


    logging.info("Waiting for filtered job list to refresh...")
    time.sleep(3)

    page_number = 1
    while True:
        logging.info(f"--- Processing Page {page_number} ---")
        job_links_selector = (By.CSS_SELECTOR, "a[data-testid='job-search-job-detail-link']")
        try:
            WebDriverWait(driver, 10).until(EC.presence_of_element_located(job_links_selector))
        except TimeoutException:
            logging.info("No more job links found or page did not load as expected. Ending process for this search.")
            break 

        job_elements = driver.find_elements(job_links_selector[0], job_links_selector[1]) 
        job_count = len(job_elements)
        logging.info(f"Found {job_count} jobs on this page. Starting application process...")

        if job_count == 0:
            logging.info("No jobs found on this page to process.")
            pass 

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
            next_page_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, next_page_button_xpath))
            )
            driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});", next_page_button)
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", next_page_button)
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
        if "google_credentials" not in st.secrets:
            status_placeholder.error("❌ Google credentials not found in Streamlit Secrets. Please configure them in app settings.")
            logging.error("Google credentials not found in Streamlit Secrets.")
            return

        google_creds_dict = st.secrets["google_credentials"]
        scoped_credentials = Credentials.from_service_account_info(
            google_creds_dict,
            scopes=['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        )
        client = gspread.authorize(scoped_credentials)
        spreadsheet = client.open_by_key(spreadsheet_id_ui)
        worksheet = spreadsheet.sheet1
        logging.info("SUCCESS: Connected to Google Sheets.")
        status_placeholder.success("✅ Connected to Google Sheets successfully.")

    except Exception as e:
        logging.error(f"Failed to connect to Google Sheets: {e}")
        logging.error(traceback.format_exc())
        status_placeholder.error(f"❌ Error connecting to Google Sheets: {e}")
        return

    status_placeholder.info(f"🚀 Starting Bot for: {job_title} in {location} using Dice email: {dice_email_ui}")
    driver = None
    try:
        options = webdriver.ChromeOptions()
        
        # --- WebDriver Options ---
        # Comment out --headless to see the browser locally. 
        # MUST be enabled for Streamlit Cloud deployment.
        # options.add_argument("--headless") 
        
        # These are generally good for both local (even if visible) and cloud headless
        options.add_argument("--no-sandbox") # Bypasses OS security model, REQUIRED for many Linux environments including Streamlit Cloud
        options.add_argument("--disable-dev-shm-usage") # Overcomes limited resource problems in Docker/Linux
        options.add_argument("--disable-gpu") # Often necessary for headless, may not harm visible mode
        options.add_argument("--window-size=1920x1080") # Good for consistency
        options.add_argument("--disable-notifications")
        options.add_experimental_option('excludeSwitches', ['enable-logging'])
        # If running LOCALLY and you want the browser to stay open after script finishes (for debugging):
        # options.add_experimental_option("detach", True)


        try:
            service = Service(ChromeDriverManager(chrome_type=ChromeType.CHROMIUM).install())
            driver = webdriver.Chrome(service=service, options=options)
        except Exception as e_driver:
            logging.error(f"Failed to initialize Chrome Driver: {e_driver}")
            status_placeholder.error(f"❌ Failed to initialize Chrome Driver: {e_driver}. Check logs.")
            return

        status_placeholder.info("🔐 Logging in to Dice.com...")
        login_to_dice(driver, dice_email_ui, dice_password_ui)

        status_placeholder.success("✅ Login successful! Processing jobs...")
        search_and_apply(driver, job_title, location, worksheet)

        status_placeholder.success("🎉 Bot has finished processing all pages.")
        logging.info("Process finished for all pages.")
    except Exception as e:
        status_placeholder.error(f"❌ A critical error occurred: {e}. Check logs for details.")
        logging.critical("A critical, unhandled error stopped the bot.")
        logging.critical(traceback.format_exc())
    finally:
        if driver:
            # If using options.add_experimental_option("detach", True) for local debugging,
            # you might want to conditionally not quit, or quit after a delay.
            # For normal operation (especially cloud), always quit.
            time.sleep(5) # Optional: keep browser open for 5s locally if not detaching
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
                dice_email_ui_input.strip(),
                dice_password_ui_input.strip(),
                spreadsheet_id_ui_input.strip(),
                status_placeholder
            )
        except Exception as e:
            st.error(f"❌ An error occurred during bot execution: {str(e)}")
            st.exception(e)

st.markdown("---")
st.markdown("Google Service Account credentials for Sheets are loaded securely from Streamlit Secrets.")
