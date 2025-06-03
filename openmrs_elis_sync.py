import requests
import json
import base64
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class OpenMRSIntegration:
    def __init__(self, base_url, username, password):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.jsessionid = None
        self.location_uuid = "ba685651-ed3b-4e63-9b35-78893060758a"
        self.identifier_source_uuid = "8549f706-7e85-4c1d-9424-217d50a2988b"

    def _get_auth_header(self):
        auth_string = f"{self.username}:{self.password}"
        encoded_auth = base64.b64encode(auth_string.encode('utf-8')).decode('utf-8')
        return {"Authorization": f"Basic {encoded_auth}"}

    def login(self):
        logging.info("Attempting to log in to OpenMRS...")
        headers = self._get_auth_header()
        
        try:
            response = self.session.get(f"{self.base_url}/ws/rest/v1/session", headers=headers, verify=False)
            response.raise_for_status()
            
            if 'JSESSIONID' in self.session.cookies:
                self.jsessionid = self.session.cookies['JSESSIONID']
                logging.info(f"OpenMRS JSESSIONID obtained: {self.jsessionid}")
            else:
                logging.error("OpenMRS JSESSIONID not found in initial session GET.")
                return False

            session_data = response.json()
            if session_data.get('authenticated'):
                logging.info("OpenMRS initial session GET successful.")
                
                post_headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                }
                post_payload = {"sessionLocation": self.location_uuid}
                post_response = self.session.post(
                    f"{self.base_url}/ws/rest/v1/session", 
                    headers=post_headers, 
                    data=json.dumps(post_payload),
                    verify=False
                )
                post_response.raise_for_status()
                post_session_data = post_response.json()
                if post_session_data.get('authenticated') and post_session_data.get('sessionLocation'):
                    logging.info("OpenMRS session location set successfully. Login complete.")
                    return True
                else:
                    logging.error("Failed to set OpenMRS session location or not authenticated after POST.")
                    return False
            else:
                logging.error("OpenMRS authentication failed during initial session GET.")
                return False
        except requests.exceptions.RequestException as e:
            logging.error(f"OpenMRS login failed: {e}")
            return False

    def get_new_patient_identifier(self):
        logging.info("Generating new patient identifier from OpenMRS...")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        try:
            response = self.session.post(
                f"{self.base_url}/ws/rest/v1/idgen/identifiersource/{self.identifier_source_uuid}/identifier",
                headers=headers,
                data=json.dumps({}),
                verify=False
            )
            response.raise_for_status()
            identifier_data = response.json()
            identifier = identifier_data.get('identifier')
            if identifier:
                logging.info(f"Generated OpenMRS patient identifier: {identifier}")
                return identifier
            else:
                logging.error("Failed to get identifier from OpenMRS response.")
                return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to generate OpenMRS patient identifier: {e}")
            return None

    def create_openmrs_patient(self, patient_data):
        logging.info("Creating patient in OpenMRS...")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        try:
            response = self.session.post(
                f"{self.base_url}/ws/rest/v1/patient/",
                headers=headers,
                data=json.dumps(patient_data),
                verify=False
            )
            response.raise_for_status()
            created_patient = response.json()
            logging.info(f"Patient created in OpenMRS. UUID: {created_patient.get('uuid')}")
            return created_patient
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to create patient in OpenMRS: {e}")
            return None

class OpenELISIntegration:
    def __init__(self, base_url, username, password):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.jsessionid = None
        self.csrf_token = None

    def login(self):
        logging.info("Attempting to log in to OpenELIS...")
        
        login_url = f"{self.base_url}/api/OpenELIS-Global/ValidateLogin?apiCall=true"
        login_payload = {
            "loginName": self.username,
            "password": self.password,
        }
        login_headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "*/*"
        }

        try:
            logging.info("Sending OpenELIS login POST request...")
            response = self.session.post(
                login_url, 
                headers=login_headers, 
                data=login_payload, 
                verify=False
            )
            response.raise_for_status()
            
            if 'JSESSIONID' in self.session.cookies:
                self.jsessionid = self.session.cookies['JSESSIONID']
                logging.info(f"OpenELIS JSESSIONID obtained from login POST: {self.jsessionid}")
            else:
                logging.error("OpenELIS JSESSIONID not found after login POST.")
                return False

            logging.info("OpenELIS login POST successful. Now fetching CSRF token...")

            session_get_url = f"{self.base_url}/api/OpenELIS-Global/session"
            session_get_headers = {
                "Accept": "*/*",
            }
            session_response = self.session.get(session_get_url, headers=session_get_headers, verify=False)
            session_response.raise_for_status()
            
            session_data = session_response.json()
            if session_data.get('authenticated'):
                self.csrf_token = session_data.get('csrf')
                if self.csrf_token:
                    logging.info(f"OpenELIS CSRF token obtained: {self.csrf_token}")
                    logging.info("OpenELIS session successfully established.")
                    return True
                else:
                    logging.error("Failed to retrieve OpenELIS CSRF token from session response.")
                    return False
            else:
                logging.error("OpenELIS session GET indicates not authenticated after login POST.")
                return False

        except requests.exceptions.RequestException as e:
            logging.error(f"OpenELIS login failed: {e}")
            logging.error(f"Response content: {e.response.text if e.response else 'No response'}")
            return False

    def create_openelis_patient(self, patient_data):
        logging.info("Creating patient in OpenELIS...")
        if not self.jsessionid or not self.csrf_token:
            logging.error("OpenELIS session or CSRF token not established. Please login first.")
            return None

        headers = {
            "Content-Type": "application/json",
            "X-CSRF-TOKEN": self.csrf_token,
            "Accept": "*/*"
        }
        try:
            response = self.session.post(
                f"{self.base_url}/api/OpenELIS-Global/rest/PatientManagement",
                headers=headers,
                data=json.dumps(patient_data),
                verify=False
            )
            response.raise_for_status()
            logging.info("Patient creation request sent to OpenELIS. Status Code: 200 OK.")
            return True
        except requests.exceptions.HTTPError as e:
            logging.error(f"Failed to create patient in OpenELIS. HTTP Error: {e.response.status_code} - {e.response.text}")
            return False
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to create patient in OpenELIS: {e}")
            return False

class PatientMiddleware:
    def __init__(self, openmrs_config, openelis_config):
        self.openmrs = OpenMRSIntegration(**openmrs_config)
        self.openelis = OpenELISIntegration(**openelis_config)

    def synchronize_patient(self, openmrs_patient_response):
        logging.info("Attempting to synchronize patient from OpenMRS to OpenELIS.")

        if not self.openmrs.jsessionid:
            if not self.openmrs.login():
                logging.error("Failed to log in to OpenMRS. Aborting synchronization.")
                return False
        
        if not self.openelis.jsessionid or not self.openelis.csrf_token:
            if not self.openelis.login():
                logging.error("Failed to log in to OpenELIS or retrieve CSRF token. Aborting synchronization.")
                return False

        openmrs_person = openmrs_patient_response.get('person', {})
        
        # Correctly extract preferred name details
        preferred_name = openmrs_person.get('preferredName', {})
        first_name = preferred_name.get('givenName', '')
        last_name = preferred_name.get('familyName', '')

        # Correctly extract patient identifier
        openmrs_patient_id = ""
        identifiers_list = openmrs_patient_response.get('identifiers', [])
        if identifiers_list:
            # The identifier itself is within the 'display' field, like "OpenMRS ID = 100036F"
            # We need to parse it out
            identifier_display = identifiers_list[0].get('display', '')
            if ' = ' in identifier_display:
                openmrs_patient_id = identifier_display.split(' = ')[1].strip()
            else: # Fallback if format is just the ID
                openmrs_patient_id = identifier_display.strip()
            
        openmrs_addresses_list = openmrs_person.get('addresses', [])
        openmrs_addresses = openmrs_addresses_list[0] if openmrs_addresses_list else {}

        openmrs_attributes = openmrs_person.get('attributes', [])

        phone_number = ""
        for attr in openmrs_attributes:
            if attr.get('attributeType', {}).get('uuid') == "14d4f066-15f5-102d-96e4-000c29c2a5d7" or \
               attr.get('attributeType', {}).get('display') == "Telephone Number":
                phone_number = attr.get('value', '')
                break
        
        birthdate_openmrs = openmrs_person.get('birthdate', '')
        birthdate_elis = ""
        if birthdate_openmrs:
            try:
                if 'T' in birthdate_openmrs:
                    dt_object = datetime.fromisoformat(birthdate_openmrs.replace('Z', '+00:00'))
                else:
                    dt_object = datetime.strptime(birthdate_openmrs, "%Y-%m-%d")
                birthdate_elis = dt_object.strftime("%d/%m/%Y")
            except ValueError:
                logging.warning(f"Could not parse OpenMRS birthdate: {birthdate_openmrs}. Using empty string for OpenELIS.")

        openelis_patient_payload = {
            "patientUpdateStatus": "ADD",
            "nationalId": openmrs_patient_id,
            "subjectNumber": openmrs_patient_id,
            "lastName": last_name,
            "firstName": first_name,
            "gender": openmrs_person.get('gender', ''),
            "birthDateForDisplay": birthdate_elis,
            "primaryPhone": phone_number,
            "streetAddress": openmrs_addresses.get('address1', ''),
            "city": openmrs_addresses.get('cityVillage', ''),
            "commune": "", 
            "education": "", 
            "healthDistrict": "", 
            "healthRegion": "", 
            "maritialStatus": "", 
            "nationality": "", 
            "otherNationality": "", 
            "patientContact": { 
                "person": {
                    "firstName": "",
                    "lastName": "",
                    "primaryPhone": "",
                    "email": ""
                }
            }
        }
        logging.info(f"Transformed patient data for OpenELIS: {openelis_patient_payload}")

        if self.openelis.create_openelis_patient(openelis_patient_payload):
            logging.info("Patient successfully synchronized to OpenELIS.")
            return True
        else:
            logging.error("Failed to synchronize patient to OpenELIS.")
            return False

OPENMRS_CONFIG = {
    "base_url": "http://localhost/openmrs",
    "username": "admin",
    "password": "Admin123"
}

OPENELIS_CONFIG = {
    "base_url": "https://localhost:8445",
    "username": "admin",
    "password": "adminADMIN!"
}

def main():
    middleware = PatientMiddleware(OPENMRS_CONFIG, OPENELIS_CONFIG)

    if not middleware.openmrs.login():
        logging.error("Failed to authenticate with OpenMRS. Exiting.")
        return

    if not middleware.openelis.login():
        logging.error("Failed to authenticate with OpenELIS. Exiting.")
        return

    sample_openmrs_request_payload = {
        "identifiers": [
            {
                "identifier": middleware.openmrs.get_new_patient_identifier(),
                "identifierType": "05a29f94-c0ed-11e2-94be-8c13b969e334",
                "location": middleware.openmrs.location_uuid,
                "preferred": True
            }
        ],
        "person": {
            "names": [
                {
                    "givenName": "sedan",
                    "middleName": "medan",
                    "familyName": "bedan"
                }
            ],
            "gender": "M",
            "birthdate": "1996-11-25",
            "birthdateEstimated": False,
            "dead": False,
            "addresses": [
                {
                    "address1": "789 Sync Street",
                    "cityVillage": "Middleware City",
                    "country": "IntegrateLand"
                }
            ],
            "attributes": [
                {
                    "attributeType": "14d4f066-15f5-102d-96e4-000c29c2a5d7",
                    "value": "555-123-4567"
                }
            ]
        }
    }
    
    if not sample_openmrs_request_payload['identifiers'][0]['identifier']:
        logging.error("Could not generate OpenMRS patient identifier. Aborting sync.")
        return

    openmrs_created_patient_response = middleware.openmrs.create_openmrs_patient(sample_openmrs_request_payload)
    
    if openmrs_created_patient_response:
        logging.info(f"OpenMRS patient creation successful: {openmrs_created_patient_response.get('uuid')}")
        # The debugging line is kept here for reference, but can be removed for clean runs.
        # logging.info(f"Full OpenMRS patient creation response for debugging: {json.dumps(openmrs_created_patient_response, indent=2)}")
        logging.info("Initiating synchronization to OpenELIS...")
        if middleware.synchronize_patient(openmrs_created_patient_response):
            logging.info("Patient synchronization process completed successfully!")
        else:
            logging.error("Patient synchronization process failed.")
    else:
        logging.error("Failed to create patient in OpenMRS. Synchronization aborted.")

if __name__ == "__main__":
    requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
    main()
