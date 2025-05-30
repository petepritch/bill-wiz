"""
QuickBooks Authentication Module

This module handles all QuickBooks API authentication, token management,
and API request functions.
"""

import os
import time
import requests
import streamlit as st
from intuitlib.client import AuthClient
from intuitlib.enums import Scopes
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# QuickBooks API credentials
CLIENT_ID = os.getenv("QB_CLIENT_ID")
CLIENT_SECRET = os.getenv("QB_CLIENT_SECRET")
ACCESS_TOKEN = os.getenv("QB_ACCESS_TOKEN")
REFRESH_TOKEN = os.getenv("QB_REFRESH_TOKEN")
COMPANY_ID = os.getenv("QB_COMPANY_ID")
TOKEN_EXPIRY = os.getenv("QB_TOKEN_EXPIRY")

# API endpoints and settings
REDIRECT_URI = os.getenv(
    "QB_REDIRECT_URI", "https://developer.intuit.com/v2/OAuth2Playground/RedirectUrl"
)
IS_SANDBOX = os.getenv("QB_SANDBOX", "True").lower() == "true"

if IS_SANDBOX:
    BASE_URL = "https://sandbox-quickbooks.api.intuit.com"
    ENVIRONMENT = "sandbox"
else:
    BASE_URL = "https://quickbooks.api.intuit.com"
    ENVIRONMENT = "production"

# Initialize the auth client
auth_client = AuthClient(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    environment=ENVIRONMENT,
)


def save_tokens_to_env(access_token, refresh_token, token_expiry, company_id=None):
    """Save tokens to .env file"""
    env_file = ".env"

    # Check if .env file exists
    if not os.path.exists(env_file):
        # Create a new .env file with the tokens
        with open(env_file, "w") as f:
            f.write(f"QB_ACCESS_TOKEN={access_token}\n")
            f.write(f"QB_REFRESH_TOKEN={refresh_token}\n")
            f.write(f"QB_TOKEN_EXPIRY={token_expiry}\n")
            if company_id:
                f.write(f"QB_COMPANY_ID={company_id}\n")
        return

    # Read current .env file
    with open(env_file, "r") as f:
        lines = f.readlines()

    # Update tokens
    token_vars = {
        "QB_ACCESS_TOKEN": access_token,
        "QB_REFRESH_TOKEN": refresh_token,
        "QB_TOKEN_EXPIRY": token_expiry,
    }

    if company_id:
        token_vars["QB_COMPANY_ID"] = company_id

    # Track which vars we've updated
    updated_vars = set()
    new_lines = []

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            new_lines.append(line)
            continue

        var_name = line.split("=")[0]
        if var_name in token_vars:
            new_lines.append(f"{var_name}={token_vars[var_name]}")
            updated_vars.add(var_name)
        else:
            new_lines.append(line)

    # Add any missing vars
    for var_name, value in token_vars.items():
        if var_name not in updated_vars:
            new_lines.append(f"{var_name}={value}")

    # Write updated .env file
    with open(env_file, "w") as f:
        f.write("\n".join(new_lines) + "\n")

    # Also update the current environment variables
    for var_name, value in token_vars.items():
        os.environ[var_name] = str(value)


def refresh_access_token():
    """Refresh access token using refresh token"""
    if not REFRESH_TOKEN:
        st.error("No refresh token available. Please re-authenticate.")
        return None

    try:
        auth_client.refresh(refresh_token=REFRESH_TOKEN)

        # Save the new tokens
        save_tokens_to_env(
            auth_client.access_token,
            auth_client.refresh_token,
            str(int(time.time()) + auth_client.x_refresh_token_expires_in),
        )

        # Return the new access token
        return auth_client.access_token
    except Exception as e:
        st.error(f"Error refreshing token: {str(e)}")
        return None


def is_token_valid():
    """Check if the access token is still valid"""
    if not ACCESS_TOKEN or not TOKEN_EXPIRY:
        return False

    try:
        expiry = int(TOKEN_EXPIRY)
        current_time = int(time.time())
        # Return True if token is not expired (with 5 minute buffer)
        return current_time < (expiry - 300)
    except:
        return False


def get_valid_access_token():
    """Get a valid access token, refreshing if necessary"""
    if is_token_valid():
        return ACCESS_TOKEN
    else:
        return refresh_access_token()


def initial_auth_flow():
    """Handle the initial authorization flow - Direct Code Extraction Version"""
    # Define the scopes needed for your application
    scopes = [Scopes.ACCOUNTING]

    # Generate the authorization URL
    auth_url = auth_client.get_authorization_url(scopes)

    # Display instructions and URL in Streamlit
    st.title("QuickBooks API Authorization")
    st.write("You need to authorize this application to access your QuickBooks data.")
    st.markdown(f"### Step 1: [Click here to authorize with QuickBooks]({auth_url})")

    st.write("---")

    st.markdown("### Step 2: After authorizing, you'll see a URL with 'code=' in it")
    st.write(
        "Copy ONLY the value of the 'code' parameter (the text after 'code=' and before any '&')"
    )

    auth_code = st.text_input("Paste ONLY the authorization code here:")

    st.markdown("### Step 3: Copy the Company ID (realmId)")
    st.write("In the same URL, find 'realmId=' and copy the number that follows it")

    realm_id = st.text_input("Paste the realmId here:")

    if st.button("Complete Authorization") and auth_code and realm_id:
        try:
            st.write(
                f"Using authorization code: {auth_code[:5]}... (length: {len(auth_code)})"
            )
            st.write(f"Using realmId: {realm_id}")

            # Create a new auth client with exact credentials to avoid any issues
            temp_auth_client = AuthClient(
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
                redirect_uri=REDIRECT_URI,
                environment=ENVIRONMENT,
            )

            # Set the realm ID directly
            temp_auth_client.realm_id = realm_id

            # Get the bearer token with just the code
            try:
                temp_auth_client.get_bearer_token(code=auth_code)

                # Save the tokens
                save_tokens_to_env(
                    temp_auth_client.access_token,
                    temp_auth_client.refresh_token,
                    str(int(time.time()) + temp_auth_client.x_refresh_token_expires_in),
                    temp_auth_client.realm_id,
                )

                st.success(
                    "Authorization successful! You can now use the QuickBooks API."
                )
                st.experimental_rerun()
            except Exception as inner_e:
                st.error(f"Error getting bearer token: {str(inner_e)}")

                # Try direct token request as last resort
                try:
                    st.write("Attempting direct token request...")
                    import requests
                    import base64

                    token_endpoint = (
                        "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
                    )
                    auth_header = base64.b64encode(
                        f"{CLIENT_ID}:{CLIENT_SECRET}".encode()
                    ).decode()

                    headers = {
                        "Authorization": f"Basic {auth_header}",
                        "Content-Type": "application/x-www-form-urlencoded",
                    }

                    data = {
                        "grant_type": "authorization_code",
                        "code": auth_code,
                        "redirect_uri": REDIRECT_URI,
                    }

                    response = requests.post(token_endpoint, headers=headers, data=data)
                    st.write(f"Response status: {response.status_code}")

                    if response.status_code == 200:
                        token_data = response.json()
                        save_tokens_to_env(
                            token_data["access_token"],
                            token_data["refresh_token"],
                            str(
                                int(time.time())
                                + token_data["x_refresh_token_expires_in"]
                            ),
                            realm_id,
                        )
                        st.success("Direct token request successful!")
                        st.experimental_rerun()
                    else:
                        st.error(f"Direct token request failed: {response.text}")
                except Exception as direct_e:
                    st.error(f"Direct token request error: {str(direct_e)}")

        except Exception as e:
            st.error(f"Authorization failed: {str(e)}")
            st.write(
                "Please try the authorization process again with a fresh authorization code."
            )


def make_api_request(endpoint, method="GET", data=None):
    """Make an API request to QuickBooks with automatic token handling"""
    access_token = get_valid_access_token()
    if not access_token:
        st.error("Failed to get a valid access token")
        return None

    url = f"{BASE_URL}/v3/company/{COMPANY_ID}/{endpoint}"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    try:
        if method == "GET":
            response = requests.get(url, headers=headers)
        elif method == "POST":
            response = requests.post(url, headers=headers, json=data)
        else:
            st.error(f"Unsupported method: {method}")
            return None

        # Handle token expiration
        if response.status_code == 401:
            # Token might be expired, try refreshing
            new_token = refresh_access_token()
            if new_token:
                # Update headers with new token
                headers["Authorization"] = f"Bearer {new_token}"
                # Retry the request
                if method == "GET":
                    response = requests.get(url, headers=headers)
                elif method == "POST":
                    response = requests.post(url, headers=headers, json=data)

        if response.status_code >= 400:
            st.error(f"API Error: {response.status_code}")
            st.error(response.text)
            return None

        return response
    except requests.exceptions.RequestException as e:
        st.error(f"API request failed: {str(e)}")
        return None


def run_query(query):
    """Run a query against the QuickBooks API"""
    encoded_query = requests.utils.quote(query)
    endpoint = f"query?query={encoded_query}"
    return make_api_request(endpoint)


def check_qb_connection():
    """Check if we have valid QuickBooks credentials and tokens"""
    if not CLIENT_ID or not CLIENT_SECRET:
        st.error("Missing QuickBooks API credentials. Please check your .env file.")
        return False

    # Handle authentication if needed
    access_token = get_valid_access_token()
    if not access_token:
        initial_auth_flow()
        return False

    return True
