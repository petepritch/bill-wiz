"""
QuickBooks Client for Bill Automation

This module handles authentication and interactions with the QuickBooks API
for creating bills from parsed CFDI data.
"""

import os
import requests
import logging
import base64
import json
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class QuickBooksClient:
    """
    A client for intereacting with the Quickbooks API.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        redirect_uri: str,
        comapny_id: str,
        is_sandbox: bool = True,
        token_path: str = "qb_tokens.json",
    ):
        self.client_id = (client_id,)
        self.client_secret = (client_secret,)
        self.refresh_token = (refresh_token,)
        self.redirect_uri = (redirect_uri,)
        self.company_id = (comapny_id,)
        self.is_sandbox = is_sandbox
        self.token_path = token_path

        if is_sandbox:
            self.base_url = ""
            self.api_url = ""
        else:
            self.base_url = ""
            self.api_url = ""

        auth_string = f"{self.client_id}:{self.client_secret}"
        self.auth_header = {
            "Authorization": f"Basic {base64.b64encode(auth_string.encode()).decode()}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        self.access_token = None
        self.refresh_token = None
        # Get tokens from file if available
        self.load_tokens()

    def _load_tokens(self) -> None:
        """
        Load tokens from a file.
        """
        try:
            if os.path.exists(self.token_path):
                with open(self.token_path, "r") as file:
                    tokens = json.load(file)
                    self.access_token = tokens.get("access_token")
                    self.refresh_token = tokens.get("refresh_token", self.refresh_token)
                    self.token_expiry = tokens.get("token_expiry")

        except Exception as e:
            logger.warning(f"Could not load tokens: {str(e)}")

    def _save_tokens(self) -> None:
        """
        Save tokens to a file.
        """
        try:
            with open(self.token_path, "w") as file:
                tokens = {
                    "access_token": self.access_token,
                    "refresh_token": self.refresh_token,
                    "token_expiry": self.token_expiry,
                }
                json.dump(tokens, file)
        except Exception as e:
            logger.warning(f"Could not save tokens: {str(e)}")

    def _get_auth_header(self) -> Dict[str, str]:
        """
        Get the authorization header for API requests.
        """
        if not self.access_token:
            self._refresh_access_token()

        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _refresh_access_token(self) -> None:
        """
        Refresh the access token using the refresh token.
        """
        now = datetime.now().timestamp()

        if (
            self.access_token and self.token_expiry and now < self.token_expiry - 300
        ):  # 5 minutes buffer
            return

        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
        }
