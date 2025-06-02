import streamlit as st

# --- Streamlit Configuration (MUST be first) ---
st.set_page_config(page_title="Dice.com Job Application Bot", page_icon="🤖", layout="centered")

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
import time
import traceback
import logging
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import pytz

# --- Basic Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Main Configuration ---
DICE_EMAIL = "abdulcui4554@gmail.com"
DICE_PASSWORD = "69084554a"
SPREADSHEET_ID = "1ML4bC7XVwQys-MR0TH8ujk5Fu3RtLxyUfJLC92Gzxqk"
SERVICE_ACCOUNT_FILE = 'service_account_credentials.json'

# --- SPEED CONFIGURATION ---
ACTION_DELAY = 1.5

# --- GOOGLE SHEETS FUNCTION ---
def log_to_google_sheet(worksheet, job_title):
    """Logs a successful application to the specified Google Sheet."""
    try:
        # Set the timezone to Pakistan Standard Time
        pakistan_tz = pytz.timezone('Asia/Karachi')
        # Get the current time and format it
        current_time_pkt = datetime.now(pakistan_tz).strftime('%Y-%m-%d %H:%M:%S')
        
        # Prepare the row data
        row = [current_time_pkt, job_title, "Done"]
        
        # Append the row to the worksheet
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
        email_input.send_keys(DICE_EMAIL)
        time.sleep(ACTION_DELAY)
        logging.info("Clicking 'Continue' button.")
        continue_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, "//button[@data-testid='sign-in-button']")))
        continue_button.click()
        time.sleep(ACTION_DELAY)
        logging.info("Step 2: Entering password.")
        password_input = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.NAME, "password")))
        password_input.send_keys(DICE_PASSWORD)
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
        driver.save_screenshot('FILTERING_FAILED_SCREENSHOT.png')
        raise
    
    logging.info("Waiting for filtered job list to refresh...")
    time.sleep(3)
    
    page_number = 1
    while True:
        logging.info(f"--- Processing Page {page_number} ---")
        job_links_selector = (By.CSS_SELECTOR, "a[data-testid='job-search-job-detail-link']")
        WebDriverWait(driver, 10).until(EC.presence_of_element_located(job_links_selector))
        
        job_count = len(driver.find_elements(job_links_selector[0], job_links_selector[1]))
        logging.info(f"Found {job_count} jobs on this page. Starting application process...")

        original_window = driver.current_window_handle

        for i in range(job_count):
            job_name = "N/A"
            try:
                all_jobs_on_page = WebDriverWait(driver, 10).until(EC.presence_of_all_elements_located(job_links_selector))
                
                if i >= len(all_jobs_on_page):
                    logging.warning("Job list changed during processing. Ending loop for this page.")
                    break
                
                current_job_link = all_jobs_on_page[i]
                job_name = current_job_link.text
                
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
                    
                    # Log to Google Sheets on success
                    log_to_google_sheet(worksheet, job_name)
                    
                    time.sleep(ACTION_DELAY)
                
                except TimeoutException:
                    logging.warning(f"Job '{job_name}' is not an 'Easy Apply' job or failed to load. Skipping.")
                    driver.save_screenshot(f'JOB_{job_name[:20]}_SKIPPED.png')
                
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
                continue

        try:
            logging.info("All jobs on this page processed. Looking for the 'Next' page button...")
            next_page_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "span[aria-label='Next']"))
            )
            driver.execute_script("arguments[0].click();", next_page_button)
            
            logging.info("SUCCESS: Clicked 'Next' page. Waiting for new jobs to load...")
            time.sleep(10)
            page_number += 1
        except TimeoutException:
            logging.info("This is the last page. No 'Next' button found.")
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
        # Setup Google Sheets client
        status_placeholder.info("🔗 Connecting to Google Sheets...")
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_ACCOUNT_FILE, scope)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        worksheet = spreadsheet.sheet1
        logging.info("SUCCESS: Connected to Google Sheets.")
        status_placeholder.success("✅ Connected to Google Sheets successfully.")
    except FileNotFoundError:
        logging.error(f"'{SERVICE_ACCOUNT_FILE}' not found. Please ensure it's in the same directory.")
        status_placeholder.error(f"❌ Error: '{SERVICE_ACCOUNT_FILE}' not found.")
        return
    except Exception as e:
        logging.error(f"Failed to connect to Google Sheets: {e}")
        status_placeholder.error(f"❌ Error: Could not connect to Google Sheets: {e}")
        return

    status_placeholder.info(f"🚀 Starting Bot for: {job_title} in {location}")
    driver = None
    try:
        options = webdriver.ChromeOptions()
        options.add_argument("--disable-notifications")
        options.add_argument("--start-maximized")
        options.add_experimental_option('excludeSwitches', ['enable-logging'])
        options.add_experimental_option("detach", True)
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        
        status_placeholder.info("🔐 Logging in to Dice.com...")
        login_to_dice(driver)
        
        status_placeholder.success("✅ Login successful! Processing jobs...")
        search_and_apply(driver, job_title, location, worksheet)
        
        status_placeholder.success("🎉 Bot has finished processing all pages.")
        logging.info("Process finished for all pages.")
    except Exception as e:
        status_placeholder.error("❌ A critical error occurred. Check console for details.")
        logging.critical("A critical, unhandled error stopped the bot.")
        logging.critical(traceback.format_exc())

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
        # Status placeholder
        status_placeholder = st.empty()
        
        # Run the bot
        try:
            start_bot_task(job_title.strip(), location.strip(), status_placeholder)
        except Exception as e:
            st.error(f"❌ An error occurred: {str(e)}")
            st.exception(e)

# Footer
st.markdown("---")
st.markdown("**Note:** Make sure you have the `service_account_credentials.json` file in the same directory.")