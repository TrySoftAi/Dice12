import streamlit as st
import json # Needed for loading Google credentials from string if stored as a single TOML string

# --- Streamlit Configuration (MUST be first) ---
st.set_page_config(page_title="Dice.com Job Application Bot", page_icon="🤖", layout="centered")

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager # Keep for local, might be handled by Streamlit Cloud
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
import time
import traceback
import logging
import gspread
# from oauth2client.service_account import ServiceAccountCredentials # Deprecated
from google.oauth2.service_account import Credentials # Using google-auth for service account
from datetime import datetime
import pytz

# --- Basic Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Main Configuration - Fetched from Streamlit Secrets ---
# These will be set in your Streamlit Cloud app settings
DICE_EMAIL = st.secrets.get("DICE_EMAIL", "your_default_email_if_not_set") # Add defaults or handle if None
DICE_PASSWORD = st.secrets.get("DICE_PASSWORD", "your_default_password_if_not_set")
SPREADSHEET_ID = st.secrets.get("SPREADSHEET_ID", "your_default_spreadsheet_id_if_not_set")

# Google Service Account credentials will be loaded from secrets as a dictionary
# The variable SERVICE_ACCOUNT_FILE is no longer used to load the file directly.

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

def login_to_dice(driver):
    """Performs a full two-step login to Dice.com."""
    logging.info("Initiating full two-step login to Dice.com...")
    driver.get("https://www.dice.com/dashboard/login")
    try:
        logging.info("Step 1: Entering email.")
        email_input = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.NAME, "email")))
        email_input.send_keys(DICE_EMAIL) # Uses secret
        time.sleep(ACTION_DELAY)

        logging.info("Clicking 'Continue' button.")
        continue_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, "//button[@data-testid='sign-in-button']")))
        continue_button.click()
        time.sleep(ACTION_DELAY)

        logging.info("Step 2: Entering password.")
        password_input = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.NAME, "password")))
        password_input.send_keys(DICE_PASSWORD) # Uses secret
        time.sleep(ACTION_DELAY)

        logging.info("Clicking final 'Sign In' button.")
        final_login_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, "//button[@type='submit']")))
        final_login_button.click()

        logging.info("Verifying login success by checking for dashboard URL...")
        WebDriverWait(driver, 20).until(EC.url_contains("dashboard"))
        time.sleep(ACTION_DELAY)
        logging.info("SUCCESS: Login verified.")
    except (TimeoutException, NoSuchElementException):
        logging.error("A timeout or element-not-found error occurred during login.")
        logging.error(traceback.format_exc())
        raise

def search_and_apply(driver, job_title, location, worksheet):
    """Searches for jobs, applies filters, and processes listings, logging successes."""
    logging.info(f"Starting job search for '{job_title}' in '{location}'.")
    driver.get("https://www.dice.com/dashboard")

    logging.info("Locating search fields on the dashboard.")
    job_title_field = WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.NAME, "q")))
    location_field = WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.NAME, "location")))

    job_title_field.clear()
    job_title_field.send_keys(job_title)
    time.sleep(0.5)

    location_field.clear()
    location_field.send_keys(location)
    time.sleep(0.5)

    logging.info("Clicking the main search button.")
    search_button = WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "[data-testid='job-search-search-bar-search-button']")))
    search_button.click()

    logging.info("Pausing for 5 seconds to let the results page load...")
    time.sleep(5)

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
        close_button_selector = (By.CSS_SELECTOR, "button[data-testid='undefined-close-button']")
        close_button = WebDriverWait(driver, 15).until(EC.element_to_be_clickable(close_button_selector))
        close_button.click()
        logging.info("Filters applied and panel closed successfully.")

    except TimeoutException:
        logging.error("CRITICAL: Could not find or click an element in the filter panel.")
        # driver.save_screenshot('FILTERING_FAILED_SCREENSHOT.png') # May not work in Streamlit Cloud easily
        raise

    logging.info("Waiting for filtered job list to refresh...")
    time.sleep(3)

    page_number = 1
    while True:
        logging.info(f"--- Processing Page {page_number} ---")
        job_links_selector = (By.CSS_SELECTOR, "a[data-testid='job-search-job-detail-link']")
        WebDriverWait(driver, 10).until(EC.presence_of_element_located(job_links_selector))

        job_elements = driver.find_elements(job_links_selector[0], job_links_selector[1])
        job_count = len(job_elements)
        logging.info(f"Found {job_count} jobs on this page. Starting application process...")

        if job_count == 0:
            logging.info("No more jobs found on this page or subsequent pages.")
            break

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
                time.sleep(10) # Allow new tab to load

                try:
                    shadow_host = WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "apply-button-wc")))
                    shadow_root = shadow_host.shadow_root
                    easy_apply_button = shadow_root.find_element(By.CSS_SELECTOR, "button.btn.btn-primary")
                    driver.execute_script("arguments[0].click();", easy_apply_button)

                    next_button = WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn-next")))
                    next_button.click()

                    submit_button = WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn-next"))) # Assuming same selector for submit
                    submit_button.click()
                    logging.info(f"--- SUCCESS: Job '{job_name}' Submitted! ---")
                    log_to_google_sheet(worksheet, job_name)
                    time.sleep(ACTION_DELAY)
                except TimeoutException:
                    logging.warning(f"Job '{job_name}' is not an 'Easy Apply' job or failed to load. Skipping.")
                    # driver.save_screenshot(f'JOB_{job_name[:20]}_SKIPPED.png')
                finally:
                    if len(driver.window_handles) > 1:
                        driver.close()
                    driver.switch_to.window(original_window)
                    time.sleep(1) # Give time to switch back
            except StaleElementReferenceException:
                logging.error(f"Stale element error on job {i+1}. Page may have refreshed. Skipping.")
                continue
            except Exception as e:
                logging.error(f"An unexpected error occurred on job '{job_name}': {e}")
                logging.error(traceback.format_exc())
                # Ensure back to original window if error
                if driver.current_window_handle != original_window and len(driver.window_handles) > 1:
                    driver.close()
                    driver.switch_to.window(original_window)
                continue
        try:
            logging.info("All jobs on this page processed. Looking for the 'Next' page button...")
            next_page_button_xpath = "//span[@aria-label='Next']/ancestor::button[not(@disabled)]" # Check if button is not disabled
            next_page_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, next_page_button_xpath))
            )
            driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});", next_page_button)
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", next_page_button)
            logging.info("SUCCESS: Clicked 'Next' page. Waiting for new jobs to load...")
            time.sleep(10) # Increased wait time
            page_number += 1
        except TimeoutException:
            logging.info("This is the last page. No 'Next' button found or it's disabled.")
            logging.info("✅ All jobs across all pages have been processed. Bot is finished.")
            break
        except Exception as e:
            logging.error(f"Could not navigate to the next page due to an error: {e}")
            logging.error(traceback.format_exc())
            break

def start_bot_task(job_title, location, status_placeholder):
    """Main bot task function"""
    worksheet = None
    try:
        status_placeholder.info("🔗 Connecting to Google Sheets...")
        # --- Updated Google Sheets Authentication ---
        # Ensure 'google_credentials' is a dictionary-like object from st.secrets
        # It should contain the content of your service_account_credentials.json
        if "google_credentials" not in st.secrets:
            status_placeholder.error("❌ Google credentials not found in Streamlit Secrets.")
            logging.error("Google credentials not found in Streamlit Secrets.")
            return

        # The st.secrets["google_credentials"] should already be a dict
        # if you've set it up correctly in TOML or Streamlit Cloud UI
        # If it's a string (e.g. if you pasted the whole JSON as one TOML string value), parse it:
        # google_creds_dict = json.loads(st.secrets["google_credentials_json_str"]) # Example if stored as string
        google_creds_dict = st.secrets["google_credentials"] # Assuming it's stored as a TOML table

        scoped_credentials = Credentials.from_service_account_info(
            google_creds_dict,
            scopes=['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        )
        client = gspread.authorize(scoped_credentials)
        spreadsheet = client.open_by_key(SPREADSHEET_ID) # SPREADSHEET_ID from secrets
        worksheet = spreadsheet.sheet1
        logging.info("SUCCESS: Connected to Google Sheets.")
        status_placeholder.success("✅ Connected to Google Sheets successfully.")

    except Exception as e: # Catch more specific exceptions if possible
        logging.error(f"Failed to connect to Google Sheets: {e}")
        logging.error(traceback.format_exc())
        status_placeholder.error(f"❌ Error connecting to Google Sheets: {e}")
        return

    if not (DICE_EMAIL and DICE_PASSWORD and SPREADSHEET_ID):
        status_placeholder.error("❌ Dice credentials or Spreadsheet ID are missing in Streamlit Secrets.")
        logging.error("Dice credentials or Spreadsheet ID are missing in Streamlit Secrets.")
        return

    status_placeholder.info(f"🚀 Starting Bot for: {job_title} in {location}")
    driver = None
    try:
        options = webdriver.ChromeOptions()
        # --- Options for Streamlit Cloud (headless Browse) ---
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920x1080") # Standard window size
        options.add_argument("--disable-dev-shm-usage") # Overcome limited resource problems
        # --- Original Options ---
        options.add_argument("--disable-notifications")
        # options.add_argument("--start-maximized") # Not applicable in headless
        options.add_experimental_option('excludeSwitches', ['enable-logging'])
        # options.add_experimental_option("detach", True) # Not for cloud deployment

        # Using webdriver-manager for local, Streamlit Cloud might have its own way or path
        # For Streamlit Community Cloud, you might need to specify the path if webdriver-manager doesn't work out of the box.
        # However, often it does work.
        try:
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
        except Exception as e_driver:
            logging.error(f"Failed to initialize Chrome Driver with webdriver-manager: {e_driver}")
            # Fallback or specific path for Streamlit Cloud if needed (more advanced)
            # For example, sometimes Chrome and ChromeDriver are at fixed paths on Streamlit Cloud.
            # This would require checking Streamlit's latest documentation or community forums.
            # For now, we rely on webdriver-manager.
            status_placeholder.error("❌ Failed to initialize Chrome Driver. Check logs.")
            return


        status_placeholder.info("🔐 Logging in to Dice.com...")
        login_to_dice(driver)

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
            driver.quit()
            logging.info("Browser closed.")

# --- Streamlit UI ---
st.title("🤖 Dice.com Job Application Bot")
st.markdown("---")

# Input sections
col1, col2 = st.columns(2)

with col1:
    st.subheader("📋 Job Title")
    job_title = st.text_input("Enter job title:", placeholder="e.g., Software Engineer, Data Analyst", key="job_title")

with col2:
    st.subheader("📍 Location")
    location = st.text_input("Enter location:", placeholder="e.g., New York, Remote", key="location")

st.markdown("---")

# Search button
if st.button("🔍 Find and Apply for Jobs", type="primary", use_container_width=True):
    if not job_title.strip() or not location.strip():
        st.error("❌ Please enter both Job Title and Location.")
    else:
        status_placeholder = st.empty()
        try:
            start_bot_task(job_title.strip(), location.strip(), status_placeholder)
        except Exception as e: # Catch errors from start_bot_task if any bubble up
            st.error(f"❌ An error occurred during bot execution: {str(e)}")
            st.exception(e)

# Footer
st.markdown("---")
st.markdown("This bot uses credentials and configurations stored securely via Streamlit Secrets.")
