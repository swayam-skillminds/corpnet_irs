import argparse
import os
import sys
import traceback
import re
import json
import time
import random
from datetime import datetime
from bs4 import BeautifulSoup
import pandas as pd
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import Select
from pydantic import BaseModel
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Header
import httpx
import logging

# Initialize FastAPI app
app = FastAPI(
    title="Salesforce and IRS EIN API",
    description="API for receiving Salesforce data and applying for IRS EIN",
    version="1.0.0"
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define a consistent file path for the CSV data (optional logging)
CSV_FILE_PATH = os.path.join(os.getcwd(), "salesforce_data.csv")

# Pydantic model for request body from Salesforce
class CaseData(BaseModel):
    record_id: str
    username: Optional[str] = None
    password: Optional[str] = None
    first_security_question: Optional[str] = None
    first_security_answer: Optional[str] = None
    second_security_question: Optional[str] = None
    second_security_answer: Optional[str] = None
    third_security_question: Optional[str] = None
    third_security_answer: Optional[str] = None
    fourth_security_question: Optional[str] = None
    fourth_security_answer: Optional[str] = None
    pin_number: Optional[str] = None
    entity_name: Optional[str] = None
    formation_date: Optional[str] = None
    entity_type: Optional[str] = None
    business_category: Optional[str] = None
    business_description: Optional[str] = None
    ein: Optional[str] = None
    quarter_of_first_payroll: Optional[str] = None
    json_summary: Optional[str] = None
    summary_raw: Optional[str] = None
    additional_fields: Optional[Dict[str, Any]] = None

# Helper Functions
def parse_summary_html(html_content):
    if not html_content:
        return None
    if '<' not in html_content:
        return {'Summary': html_content.strip()}
    
    soup = BeautifulSoup(html_content, 'html.parser')
    data = {}
    divs = soup.find_all('div', style=re.compile('padding-left: 5px;'))
    
    for div in divs:
        text = div.get_text(strip=True)
        if ':' in text:
            key, value = text.split(':', 1)
            key = key.replace('strong', '').strip()
            value = value.strip()
            data[key] = value
    
    return data

def export_to_csv_direct(data, csv_file_path):
    if not data:
        logger.warning("No data to export.")
        return False
    
    logger.info(f"Attempting to create file: {csv_file_path}")
    
    directory = os.path.dirname(csv_file_path)
    try:
        if not os.path.exists(directory):
            os.makedirs(directory)
            logger.info(f"Created directory: {directory}")
        else:
            logger.info(f"Directory already exists: {directory}")
            
        test_file = os.path.join(directory, "test_write.txt")
        try:
            with open(test_file, 'w') as f:
                f.write("Test")
            logger.info(f"Successfully created test file: {test_file}")
            os.remove(test_file)
            logger.info("Test file removed successfully")
        except Exception as e:
            logger.error(f"Failed to write test file: {e}")
            return False
    except Exception as e:
        logger.error(f"Failed to access or create directory: {e}")
        return False
    
    try:
        df = pd.DataFrame([data])
        logger.info(f"Data to write: {df.shape[0]} rows, {df.shape[1]} columns")
        df.to_csv(csv_file_path, index=False)
        logger.info(f"Pandas to_csv() completed without exceptions")
        
        if os.path.exists(csv_file_path):
            logger.info(f"SUCCESS: File created at {csv_file_path}")
            file_size = os.path.getsize(csv_file_path)
            logger.info(f"File size: {file_size} bytes")
            return True
        else:
            logger.error(f"ERROR: File was not created: {csv_file_path}")
            return False
    except Exception as e:
        logger.error(f"Failed to create CSV file: {e}")
        return False

def try_multiple_locations(data):
    global CSV_FILE_PATH
    if export_to_csv_direct(data, CSV_FILE_PATH):
        return True
    
    locations = [
        os.path.join(os.getcwd(), "salesforce_data.csv"),
        os.path.join(os.path.expanduser("~"), "Desktop", "salesforce_data.csv"),
        os.path.join(os.path.expanduser("~"), "Documents", "salesforce_data.csv"),
        os.path.join(os.environ.get('TEMP', '/tmp'), "salesforce_data.csv"),
        "salesforce_data.csv"
    ]
    
    success = False
    for location in locations:
        logger.info(f"Trying location: {location}")
        if export_to_csv_direct(data, location):
            logger.info(f"SUCCESS: Found working location at {location}")
            CSV_FILE_PATH = location
            success = True
            break
    
    if not success:
        logger.error("FAILED: Could not write to any locations.")
    
    return success

def flatten_json(data, parent_key='', sep='_'):
    items = []
    for key, value in data.items():
        new_key = f"{parent_key}{sep}{key.lower().replace(' ', '_')}" if parent_key else key.lower().replace(' ', '_')
        if isinstance(value, dict):
            items.extend(flatten_json(value, new_key, sep).items())
        elif isinstance(value, list):
            for i, item in enumerate(value):
                items.extend(flatten_json({f"{new_key}_{i}": item}, '', sep).items())
        else:
            items.append((new_key, value))
    return dict(items)

def parse_json_summary(json_content):
    if not json_content:
        return {}
    try:
        data = json.loads(json_content)
        flattened_data = flatten_json(data)
        return flattened_data
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON_Summary__c: {e}")
        return {}
    except Exception as e:
        logger.error(f"Error parsing JSON_Summary__c: {e}")
        return {}

# IRS EIN Application Functions
def fill_field(driver, field, value, label):
    logger.info(f"Filling {label} with: '{value}'")
    driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", field)
    time.sleep(0.2)
    field.click()
    field.clear()
    field.send_keys(str(value))
    filled_value = field.get_attribute("value")
    logger.info(f"Verification - Filled {label}: '{filled_value}'")

def handle_unexpected_popups(driver):
    try:
        driver.switch_to.alert.accept()
    except:
        pass
    
    try:
        no_thanks_button = driver.find_element(By.XPATH, "//button[contains(text(), 'No thanks')]")
        no_thanks_button.click()
    except:
        pass

    driver.execute_script("""
        window.alert = function() { return true; };
        window.confirm = function() { return true; };
        window.prompt = function() { return null; };
        window.open = function() { return null; };
    """)

state_mapping = {
    "ALABAMA": "AL", "AL": "AL", "ALABAMA (AL)": "AL",
    "ALASKA": "AK", "AK": "AK", "ALASKA (AK)": "AK",
    "ARIZONA": "AZ", "AZ": "AZ", "ARIZONA (AZ)": "AZ",
    "ARKANSAS": "AR", "AR": "AR", "ARKANSAS (AR)": "AR",
    "CALIFORNIA": "CA", "CA": "CA", "CALIFORNIA (CA)": "CA",
    "COLORADO": "CO", "CO": "CO", "COLORADO (CO)": "CO",
    "CONNECTICUT": "CT", "CT": "CT", "CONNECTICUT (CT)": "CT",
    "DELAWARE": "DE", "DE": "DE", "DELAWARE (DE)": "DE",
    "DISTRICT OF COLUMBIA": "DC", "DC": "DC", "DISTRICT OF COLUMBIA (DC)": "DC",
    "FLORIDA": "FL", "FL": "FL", "FLORIDA (FL)": "FL",
    "GEORGIA": "GA", "GA": "GA", "GEORGIA (GA)": "GA",
    "HAWAII": "HI", "HI": "HI", "HAWAII (HI)": "HI",
    "IDAHO": "ID", "ID": "ID", "IDAHO (ID)": "ID",
    "ILLINOIS": "IL", "IL": "IL", "ILLINOIS (IL)": "IL",
    "INDIANA": "IN", "IN": "IN", "INDIANA (IN)": "IN",
    "IOWA": "IA", "IA": "IA", "IOWA (IA)": "IA",
    "KANSAS": "KS", "KS": "KS", "KANSAS (KS)": "KS",
    "KENTUCKY": "KY", "KY": "KY", "KENTUCKY (KY)": "KY",
    "LOUISIANA": "LA", "LA": "LA", "LOUISIANA (LA)": "LA",
    "MAINE": "ME", "ME": "ME", "MAINE (ME)": "ME",
    "MARYLAND": "MD", "MD": "MD", "MARYLAND (MD)": "MD",
    "MASSACHUSETTS": "MA", "MA": "MA", "MASSACHUSETTS (MA)": "MA",
    "MICHIGAN": "MI", "MI": "MI", "MICHIGAN (MI)": "MI",
    "MINNESOTA": "MN", "MN": "MN", "MINNESOTA (MN)": "MN",
    "MISSISSIPPI": "MS", "MS": "MS", "MISSISSIPPI (MS)": "MS",
    "MISSOURI": "MO", "MO": "MO", "MISSOURI (MO)": "MO",
    "MONTANA": "MT", "MT": "MT", "MONTANA (MT)": "MT",
    "NEBRASKA": "NE", "NE": "NE", "NEBRASKA (NE)": "NE",
    "NEVADA": "NV", "NV": "NV", "NEVADA (NV)": "NV",
    "NEW HAMPSHIRE": "NH", "NH": "NH", "NEW HAMPSHIRE (NH)": "NH",
    "NEW JERSEY": "NJ", "NJ": "NJ", "NEW JERSEY (NJ)": "NJ",
    "NEW MEXICO": "NM", "NM": "NM", "NEW MEXICO (NM)": "NM",
    "NEW YORK": "NY", "NY": "NY", "NEW YORK (NY)": "NY",
    "NORTH CAROLINA": "NC", "NC": "NC", "NORTH CAROLINA (NC)": "NC",
    "NORTH DAKOTA": "ND", "ND": "ND", "NORTH DAKOTA (ND)": "ND",
    "OHIO": "OH", "OH": "OH", "OHIO (OH)": "OH",
    "OKLAHOMA": "OK", "OK": "OK", "OKLAHOMA (OK)": "OK",
    "OREGON": "OR", "OR": "OR", "OREGON (OR)": "OR",
    "PENNSYLVANIA": "PA", "PA": "PA", "PENNSYLVANIA (PA)": "PA",
    "RHODE ISLAND": "RI", "RI": "RI", "RHODE ISLAND (RI)": "RI",
    "SOUTH CAROLINA": "SC", "SC": "SC", "SOUTH CAROLINA (SC)": "SC",
    "SOUTH DAKOTA": "SD", "SD": "SD", "SOUTH DAKOTA (SD)": "SD",
    "TENNESSEE": "TN", "TN": "TN", "TENNESSEE (TN)": "TN",
    "TEXAS": "TX", "TX": "TX", "TEXAS (TX)": "TX",
    "UTAH": "UT", "UT": "UT", "UTAH (UT)": "UT",
    "VERMONT": "VT", "VT": "VT", "VERMONT (VT)": "VT",
    "VIRGINIA": "VA", "VA": "VA", "VIRGINIA (VA)": "VA",
    "WASHINGTON": "WA", "WA": "WA", "WASHINGTON (WA)": "WA",
    "WEST VIRGINIA": "WV", "WV": "WV", "WEST VIRGINIA (WV)": "WV",
    "WISCONSIN": "WI", "WI": "WI", "WISCONSIN (WI)": "WI",
    "WYOMING": "WY", "WY": "WY", "WYOMING (WY)": "WY"
}

def select_state(driver, physical_state):
    try:
        state_select = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "state")))
        driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", state_select)
        
        select = Select(state_select)
        available_values = [option.get_attribute("value") for option in select.options]
        
        if not physical_state:
            raise ValueError("physical_state is empty or None")
        physical_state = physical_state.upper().strip()
        
        if physical_state in available_values:
            state_value = physical_state
        else:
            normalized_input = re.sub(r'\s*\([^)]+\)', '', physical_state).strip()
            state_value = state_mapping.get(physical_state, state_mapping.get(normalized_input))
            
            if not state_value or state_value not in available_values:
                raise ValueError(f"Invalid state: '{physical_state}'")
        
        try:
            select.select_by_value(state_value)
        except Exception:
            try:
                display_text = next(text for text, val in zip([o.text for o in select.options], available_values) if val == state_value)
                select.select_by_visible_text(display_text)
            except Exception:
                driver.execute_script(f"arguments[0].value = '{state_value}';", state_select)
                driver.execute_script("arguments[0].dispatchEvent(new Event('change'));", state_select)
                
        handle_unexpected_popups(driver)
    except Exception as e:
        logger.warning(f"Failed to select state with input '{physical_state}': {e}")

def click_button(driver, wait, locator, desc="button", scroll=True, retries=2):
    for attempt in range(retries + 1):
        try:
            button = wait.until(EC.element_to_be_clickable(locator))
            if scroll:
                driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", button)
                time.sleep(0.2)
            button.click()
            logger.info(f"Successfully clicked the '{desc}'")
            time.sleep(0.5)
            handle_unexpected_popups(driver)
            return True
        except Exception as e:
            if attempt == retries:
                logger.warning(f"Failed to click '{desc}': {e}")
                return False
            time.sleep(0.5)

def select_radio(driver, wait, radio_id, desc="radio button", retry=1):
    try:
        driver.execute_script(f"document.getElementById('{radio_id}').checked = true;")
        if driver.execute_script(f"return document.getElementById('{radio_id}').checked;"):
            logger.info(f"Selected '{desc}' using JavaScript")
            time.sleep(0.3)
            handle_unexpected_popups(driver)
            return True
        
        radio = wait.until(EC.element_to_be_clickable((By.ID, radio_id)))
        driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", radio)
        radio.click()
        time.sleep(0.5)
        handle_unexpected_popups(driver)
        logger.info(f"Selected '{desc}' by clicking")
        return True
    except Exception as e:
        logger.warning(f"Failed to select '{desc}': {e}")
        return False

async def run_irs_ein_application(data: CaseData):
    # Parse summary_raw and json_summary
    summary_data = parse_summary_html(data.summary_raw) if data.summary_raw else {}
    flattened_json = parse_json_summary(data.json_summary) if data.json_summary else {}

    # Extract data with fallbacks
    first_name = flattened_json.get('party_0_data_first_name_value', 'Rob')
    last_name = flattened_json.get('party_0_data_last_name_value', 'Chuchla')
    pin_number = data.pin_number or ''
    ssn_last_four = pin_number[-4:] if pin_number and isinstance(pin_number, str) and len(pin_number) >= 4 else ''
    phone_number = flattened_json.get('party_0_data_phone_number_value', '2812173123')
    entity_type = data.entity_type or "Limited Liability Company (LLC)"
    quarter_of_first_payroll = data.quarter_of_first_payroll or flattened_json.get('employee_information_data_first_payroll_date_value', '03/31/2025')
    formation_date = data.formation_date or "2024-06-24"
    business_category = data.business_category or flattened_json.get('business_information_data_business_category_value', 'Finance')
    business_description = data.business_description or flattened_json.get('business_information_data_business_description_value', '')
    legal_business_name = data.entity_name or flattened_json.get('business_information_data_legal_business_name_value', 'Lane Four Capital Partners LLC')
    physical_street1 = flattened_json.get('physical_business_address_data_street1_value', '3315 Cherry Ln')
    physical_street2 = flattened_json.get('physical_business_address_data_street2_value', '')
    physical_city = flattened_json.get('physical_business_address_data_city_value', 'Austin')
    physical_state = flattened_json.get('physical_business_address_data_state_value', 'TX')
    physical_zipcode = flattened_json.get('physical_business_address_data_zipcode_value', '78703')
    mailing_street1 = flattened_json.get('mailing_address_data_street1_value', '3315 Cherry Ln')
    mailing_street2 = flattened_json.get('mailing_address_data_street2_value', '')
    mailing_city = flattened_json.get('mailing_address_data_city_value', 'Austin')
    mailing_state = flattened_json.get('mailing_address_data_state_value', 'TX')
    mailing_zipcode = flattened_json.get('mailing_address_data_zipcode_value', '78703')

    # Log data to CSV for debugging (optional)
    csv_data = {
        "record_id": data.record_id,
        "first_name": first_name,
        "last_name": last_name,
        "pin_number": pin_number,
        "entity_type": entity_type,
        "quarter_of_first_payroll": quarter_of_first_payroll,
        "formation_date": formation_date,
        "business_category": business_category,
        "business_description": business_description,
        "legal_business_name": legal_business_name,
        "physical_street1": physical_street1,
        "physical_city": physical_city,
        "physical_state": physical_state,
        "physical_zipcode": physical_zipcode,
        "mailing_street1": mailing_street1,
        "mailing_city": mailing_city,
        "mailing_state": mailing_state,
        "mailing_zipcode": mailing_zipcode,
        **summary_data,
        **flattened_json
    }
    try_multiple_locations(csv_data)

    options = uc.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--disable-infobars')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--start-maximized')
    
    prefs = {
        "profile.default_content_setting_values": {
            "popups": 2, "notifications": 2, "geolocation": 2,
        },
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
        "autofill.profile_enabled": False,
        "autofill.credit_card_enabled": False,
        "password_manager_enabled": False,
        "profile.password_dismissed_save_prompt": True
    }
    options.add_experimental_option("prefs", prefs)

    driver = None
    try:
        driver = uc.Chrome(options=options)
        wait = WebDriverWait(driver, 10)
        actions = ActionChains(driver)
        
        handle_unexpected_popups(driver)
        
        driver.get("https://sa.www4.irs.gov/modiein/individual/index.jsp")
        handle_unexpected_popups(driver)
        
        click_button(driver, wait, (By.XPATH, "//input[@type='submit' and @name='submit' and @value='Begin Application >>']"), 
                    "Begin Application button")
        
        wait.until(EC.presence_of_element_located((By.ID, "individual-leftcontent")))

        entity_type_mapping = {
            "Limited Liability Company (LLC)": "limited",
            "C-Corporation": "corporations",
            "S-Corporation": "corporations",
            "Non-Profit Corporation": "corporations",
            "ProfessionalLimitedLiabilityCompany (PLLC)": "limited",
            "ProfessionalCorporation": "corporations",
            "Sole Proprietorship": "sole",
            "Partnership": "partnerships",
            "LimitedPartnership": "partnerships",
            "LimitedLiabilityPartnership": "partnerships",
            "Corporation": "corporations",
            "GeneralPartnership": "partnerships",
            "Trusteeship": "trusts",
            "LLC": "limited",
            "LLP": "partnerships",
            "LimitedLiabilityCompany": "limited",
            "ProfessionalLimitedLiabilityCompany": "limited",
            "Estate": "estate"
        }
        
        entity_type_normalized = entity_type.strip()
        if entity_type_normalized not in entity_type_mapping:
            entity_type_normalized = entity_type.replace(" ", "").replace("(", "").replace(")", "")
        
        mapped_value = entity_type_mapping.get(entity_type_normalized, None)
        if mapped_value:
            select_radio(driver, wait, mapped_value, f"entity type {mapped_value}")
        else:
            select_radio(driver, wait, "viewadditional", "View Additional Types")
        
        click_button(driver, wait, (By.XPATH, "//input[@type='submit' and @value='Continue >>']"), "Continue button")
        
        click_button(driver, wait, (By.XPATH, "//input[@type='submit' and @value='Continue >>']"), "Continue button")
        
        try:
            llc_members_field = wait.until(EC.element_to_be_clickable((By.ID, "numbermem")))
            fill_field(driver, llc_members_field, "2", "LLC Members")
        except Exception as e:
            logger.warning(f"Failed to fill LLC Members field: {e}")
        
        select_state(driver, physical_state)
        
        click_button(driver, wait, (By.XPATH, "//input[@type='submit' and @value='Continue >>']"), "Continue button")
        
        select_radio(driver, wait, "radio_n", "radio_n option")
        
        click_button(driver, wait, (By.XPATH, "//input[@type='submit' and @value='Continue >>']"), "Continue button")
        
        click_button(driver, wait, (By.XPATH, "//input[@type='submit' and @value='Continue >>']"), "Continue button")
        
        select_radio(driver, wait, "newbiz", "newbiz option")
        
        click_button(driver, wait, (By.XPATH, "//input[@type='submit' and @value='Continue >>']"), "Continue button")
        
        try:
            first_name_field = wait.until(EC.element_to_be_clickable((By.ID, "responsiblePartyFirstName")))
            fill_field(driver, first_name_field, first_name, "First Name")
            
            last_name_field = wait.until(EC.element_to_be_clickable((By.ID, "responsiblePartyLastName")))
            fill_field(driver, last_name_field, last_name, "Last Name")
            
            ssn3_field = wait.until(EC.element_to_be_clickable((By.ID, "responsiblePartySSN3")))
            fill_field(driver, ssn3_field, pin_number[:3] if len(pin_number) >= 3 else '000', "SSN3")
            
            ssn2_field = wait.until(EC.element_to_be_clickable((By.ID, "responsiblePartySSN2")))
            fill_field(driver, ssn2_field, pin_number[3:5] if len(pin_number) >= 5 else '00', "SSN2")
            
            ssn4_field = wait.until(EC.element_to_be_clickable((By.ID, "responsiblePartySSN4")))
            fill_field(driver, ssn4_field, ssn_last_four, "SSN4")
        except Exception as e:
            logger.warning(f"Failed to fill responsible party fields: {e}")
        
        select_radio(driver, wait, "iamsole", "iamsole option")
        
        click_button(driver, wait, (By.XPATH, "//input[@type='submit' and @value='Continue >>']"), "Continue button")
        
        try:
            street_field = wait.until(EC.element_to_be_clickable((By.ID, "physicalAddressStreet")))
            fill_field(driver, street_field, physical_street1, "Physical Street Address")
            
            city_field = wait.until(EC.element_to_be_clickable((By.ID, "physicalAddressCity")))
            fill_field(driver, city_field, physical_city, "Physical City")
            
            state_select = wait.until(EC.element_to_be_clickable((By.ID, "physicalAddressState")))
            select = Select(state_select)
            physical_state_normalized = physical_state.upper().strip()
            state_value = state_mapping.get(physical_state_normalized, physical_state_normalized)
            select.select_by_value(state_value)
            
            zip_field = wait.until(EC.element_to_be_clickable((By.ID, "physicalAddressZipCode")))
            fill_field(driver, zip_field, physical_zipcode, "Physical Zip Code")
            
            if phone_number:
                phone_cleaned = ''.join(filter(str.isdigit, phone_number))
                if len(phone_cleaned) >= 10:
                    phone_first3 = phone_cleaned[:3]
                    phone_middle3 = phone_cleaned[3:6]
                    phone_last4 = phone_cleaned[6:10]
                    
                    phone_first_field = wait.until(EC.element_to_be_clickable((By.ID, "phoneFirst3")))
                    fill_field(driver, phone_first_field, phone_first3, "Phone First 3")
                    
                    phone_middle_field = wait.until(EC.element_to_be_clickable((By.ID, "phoneMiddle3")))
                    fill_field(driver, phone_middle_field, phone_middle3, "Phone Middle 3")
                    
                    phone_last_field = wait.until(EC.element_to_be_clickable((By.ID, "phoneLast4")))
                    fill_field(driver, phone_last_field, phone_last4, "Phone Last 4")
        except Exception as e:
            logger.warning(f"Failed to fill address or phone fields: {e}")
        
        primary_address = (physical_street1, physical_city, physical_state, physical_zipcode)
        mailing_address = (mailing_street1, mailing_city, mailing_state, mailing_zipcode)
        
        addresses_same = all(
            (p == m) or (m == '' and p != '') 
            for p, m in zip(primary_address, mailing_address)
        )
        
        if addresses_same:
            select_radio(driver, wait, "radioAnotherAddress_n", "Same address option")
        else:
            select_radio(driver, wait, "radioAnotherAddress_y", "Different address option")
        
        click_button(driver, wait, (By.XPATH, "//input[@type='submit' and @value='Continue >>']"), "Continue button")
        click_button(driver, wait, (By.XPATH, "//input[@type='submit' and @name='Submit' and @value='Accept As Entered']"), "Accept As Entered button")
        
        try:
            legal_business_name_cleaned = legal_business_name.strip()
            endings_to_remove = ['Corp', 'Inc', 'LLC', 'LC', 'PLLC', 'PA']
            for ending in endings_to_remove:
                if legal_business_name_cleaned.upper().endswith(ending.upper()):
                    legal_business_name_cleaned = legal_business_name_cleaned[:-(len(ending))].strip()
            legal_business_name_cleaned = re.sub(r'[^\w\s\-&]', '', legal_business_name_cleaned)
            
            business_name_field = wait.until(EC.element_to_be_clickable((By.ID, "businessOperationalLegalName")))
            fill_field(driver, business_name_field, legal_business_name_cleaned, "Legal Business Name")
        except Exception as e:
            logger.warning(f"Failed to fill Legal Business Name field with '{legal_business_name_cleaned}': {e}")
        
        try:
            county_field = wait.until(EC.element_to_be_clickable((By.ID, "businessOperationalCounty")))
            fill_field(driver, county_field, physical_city, "Business Operational County")
        except Exception as e:
            logger.warning(f"Failed to fill Business Operational County with '{physical_city}': {e}")
        
        try:
            state_select = wait.until(EC.element_to_be_clickable((By.ID, "articalsFiledState")))
            select = Select(state_select)
            physical_state_normalized = physical_state.upper().strip()
            state_value = state_mapping.get(physical_state_normalized, physical_state_normalized)
            select.select_by_value(state_value)
            logger.info(f"Selected Articles Filed State with value '{state_value}'")
        except Exception as e:
            logger.warning(f"Failed to select Articles Filed State with '{physical_state}': {e}")
        
        try:
            logger.info(f"Raw formation_date: '{formation_date}'")
            date_formats = ["%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"]
            parsed_date = None
            for date_format in date_formats:
                try:
                    parsed_date = datetime.strptime(formation_date.strip(), date_format)
                    logger.info(f"Successfully parsed date with format {date_format}: {parsed_date}")
                    break
                except ValueError:
                    continue
            
            if parsed_date is None:
                raise ValueError(f"Could not parse formation_date '{formation_date}'")
            
            formation_month = parsed_date.month
            formation_year = parsed_date.year
            
            month_select = wait.until(EC.element_to_be_clickable((By.ID, "BUSINESS_OPERATIONAL_MONTH_ID")))
            driver.execute_script("arguments[0].scrollIntoView({behavior: 'auto', block: 'center'});", month_select)
            time.sleep(0.5)
            select = Select(month_select)
            month_value = str(formation_month)
            select.select_by_value(month_value)
            logger.info(f"Selected formation month: {month_value}")
            
            year_input = wait.until(EC.element_to_be_clickable((By.ID, "BUSINESS_OPERATIONAL_YEAR_ID")))
            driver.execute_script("arguments[0].scrollIntoView({behavior: 'auto', block: 'center'});", year_input)
            time.sleep(0.5)
            year_input.clear()
            year_value = str(formation_year)
            year_input.send_keys(year_value)
            logger.info(f"Entered formation year: {year_value}")
            driver.execute_script("arguments[0].blur();", year_input)
        except Exception as e:
            logger.warning(f"Error setting formation date: {e}")
        
        click_button(driver, wait, (By.XPATH, "//input[@type='submit' and @value='Continue >>']"), "Continue button")
        
        radio_buttons = [
            ("radioTrucking_n", "Trucking radio (No)"),
            ("radioInvolveGambling_n", "Involve Gambling radio (No)"),
            ("radioExciseTax_n", "Excise Tax radio (No)"),
            ("radioSellTobacco_n", "Sell Tobacco radio (No)"),
            ("radioHasEmployees_n", "Has Employees radio (No)")
        ]
        for radio_id, desc in radio_buttons:
            select_radio(driver, wait, radio_id, desc)
        
        click_button(driver, wait, (By.XPATH, "//input[@type='submit' and @value='Continue >>']"), "Continue button")
        
        select_radio(driver, wait, "other", "Other principal activity radio")
        click_button(driver, wait, (By.XPATH, "//input[@type='submit' and @value='Continue >>']"), "Continue button")
        
        select_radio(driver, wait, "other", "Other principal service radio")
        
        try:
            if not business_description:
                business_description = "Any and all lawful business"
                logger.info("Business description is empty, using default: 'Any and all lawful business'")
            specify_field = wait.until(EC.element_to_be_clickable((By.ID, "pleasespecify")))
            fill_field(driver, specify_field, business_description, "Please Specify Business Description")
        except Exception as e:
            logger.warning(f"Failed to fill Please Specify field with '{business_description}': {e}")
        
        click_button(driver, wait, (By.XPATH, "//input[@type='submit' and @value='Continue >>']"), "Continue button")
        
        select_radio(driver, wait, "receiveonline", "Receive Online radio")
        
        click_button(driver, wait, (By.XPATH, "//input[@type='submit' and @value='Continue >>']"), "Continue button")
        
        logger.info("Form submission process completed successfully")
        return True, "IRS EIN application process completed successfully"

    except Exception as e:
        logger.error(f"Error during IRS EIN application: {e}")
        return False, str(e)

    finally:
        if driver is not None:
            try:
                driver.service.process.terminate()
                driver.quit()
                logger.info("Browser closed successfully.")
            except Exception as e:
                logger.error(f"Error closing browser: {e}")
                try:
                    driver.service.process.kill()
                except Exception:
                    logger.error("Failed to force kill browser process")
        else:
            logger.info("Driver was not initialized, nothing to close.")

# FastAPI Endpoints
@app.post("/run-irs-ein")
async def run_irs_ein_application_endpoint(data: CaseData, authorization: str = Header(None)):
    # Validate API key
    expected_api_key = os.getenv("API_KEY", "your-api-key")
    if authorization != f"Bearer {expected_api_key}":
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    # Run the automation
    success, message = await run_irs_ein_application(data)
    
    # Send completion status to Salesforce
    salesforce_endpoint = 'https://your-salesforce-instance.salesforce.com/services/apexrest/FormAutomationCompletion'
    status = "Completed" if success else "Failed"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                salesforce_endpoint,
                json={
                    "formId": data.record_id,
                    "status": status,
                    "message": message
                },
                headers={
                    'Authorization': 'Bearer your-salesforce-session-id',
                    'Content-Type': 'application/json'
                }
            )
            if response.status_code != 200:
                logger.error(f"Failed to send completion to Salesforce: {response.text}")
        except Exception as e:
            logger.error(f"Error sending completion to Salesforce: {e}")
    
    if success:
        return {"message": message, "record_id": data.record_id}
    else:
        raise HTTPException(status_code=500, detail=message)

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
