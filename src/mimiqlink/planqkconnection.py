#
# Copyright © 2022-2025 QPerfect. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import os
import requests
import threading
import base64
from urllib.parse import urljoin
import time

# Base class for the connection
from mimiqlink.abstractconnection import AbstractConnection, MimiqConnectionError

# Import the logging utils
from mimiqlink.utils import getLogger

PLANQK_API = "https://gateway.platform.planqk.de"


class JWTtoken:
    """Access token returned by the PlanQK API.

    Attributes:
        access_token (str): The bearer token.
        scope (str): The scope granted.
        token_type (str): The token type.
        expires_in (int): The lifetime of the token, in seconds.
    """

    def __init__(self, access_token, scope, token_type, expires_in):
        self.access_token = access_token
        self.scope = scope
        self.token_type = token_type
        self.expires_in = expires_in

    def __str__(self):
        return f"JWT Token:\n├── access_token: {self.access_token}\n├── scope: {self.scope}\n├── token_type: {self.token_type}\n└── expires_in: {self.expires_in}"

    def __repr__(self):
        return f"JWTtoken({self.access_token})"


class PlanqkConnection(AbstractConnection):
    """Connection to the MIMIQ services through the PlanQK gateway.

    It authenticates with a PlanQK consumer key and secret and keeps the
    access token fresh with a background thread, which fetches a new token
    after 80% of the current one's lifetime.

    Args:
        url (str, optional): The URL of the gateway. Defaults to None
            (:data:`PLANQK_API`).
        consumer_key (str, optional): The PlanQK consumer key.
        consumer_secret (str, optional): The PlanQK consumer secret.

    Examples:
        >>> from mimiqlink import PlanqkConnection

        Connect with credentials read from the ``PLANQK_CONSUMER_KEY`` and
        ``PLANQK_CONSUMER_SECRET`` environment variables.

        >>> conn = PlanqkConnection().connect()  # doctest: +SKIP

        Connect with explicit credentials.

        >>> conn = PlanqkConnection().connect("my_consumer_key", "my_consumer_secret")  # doctest: +SKIP

        Connect to another gateway.

        >>> conn = PlanqkConnection(url="https://custom-gateway.example.com").connect("key", "secret")  # doctest: +SKIP
    """

    def __init__(self, url=None, consumer_key=None, consumer_secret=None):
        if url is None:
            url = PLANQK_API

        super().__init__(url)

        # PlanQK credentials
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret

        # Token and refresher variables
        self.token = None
        self.token_lock = threading.Lock()
        self.refresher_task = None
        self.refresher_stop = False

    def get_api_url(self, *paths):
        """Return the URL of an API endpoint: ``<url>/api/planqk/<paths...>``."""
        base = urljoin(self.url + "/", "api/planqk/")
        if not paths:
            return base

        # Join all paths with the base URL
        result = base
        for path in paths:
            # Remove leading slash if present to avoid double slashes
            if path.startswith("/"):
                path = path[1:]
            result = urljoin(result + "/", path)

        return result

    @staticmethod
    def get_planqk_token(consumer_key, consumer_secret):
        """Fetch a new access token with the client credentials grant.

        The token is requested from :data:`PLANQK_API`.

        Args:
            consumer_key (str): The PlanQK consumer key.
            consumer_secret (str): The PlanQK consumer secret.

        Returns:
            JWTtoken: The new token.

        Raises:
            MimiqConnectionError: If PlanQK refuses the credentials.
        """
        path = urljoin(PLANQK_API, "token")

        creds = base64.b64encode(f"{consumer_key}:{consumer_secret}".encode()).decode()
        headers = {"Authorization": f"Basic {creds}"}
        data = "grant_type=client_credentials"

        response = requests.post(path, headers=headers, data=data, timeout=30)

        if response.status_code != 200:
            raise MimiqConnectionError(
                f"Failed to get PlanQK token. Server responded with {response.status_code}"
            )

        result = response.json()

        return JWTtoken(
            result["access_token"],
            result["scope"],
            result["token_type"],
            result["expires_in"],
        )

    def connect(self, consumer_key=None, consumer_secret=None):
        """Authenticate to the PlanQK gateway.

        Credentials given here replace the ones given to the constructor.
        A credential still missing is read from the ``PLANQK_CONSUMER_KEY``
        or ``PLANQK_CONSUMER_SECRET`` environment variable. If the connection
        is already open, nothing happens.

        Args:
            consumer_key (str, optional): The PlanQK consumer key.
            consumer_secret (str, optional): The PlanQK consumer secret.

        Returns:
            PlanqkConnection: This connection.

        Raises:
            MimiqConnectionError: If a credential is missing or PlanQK refuses
                them.
        """
        if self.isOpen():
            return self

        # Set the credentials if provided
        if consumer_key is not None:
            self.consumer_key = consumer_key
        if consumer_secret is not None:
            self.consumer_secret = consumer_secret

        # Check if we have credentials
        if self.consumer_key is None or self.consumer_secret is None:
            # Try to get credentials from environment variables
            self.consumer_key = self.consumer_key or os.environ.get(
                "PLANQK_CONSUMER_KEY"
            )
            self.consumer_secret = self.consumer_secret or os.environ.get(
                "PLANQK_CONSUMER_SECRET"
            )

            if self.consumer_key is None or self.consumer_secret is None:
                raise MimiqConnectionError(
                    "No consumer key or secret provided and not found in environment variables."
                )

        # Get the initial token
        token = self.get_planqk_token(self.consumer_key, self.consumer_secret)

        with self.token_lock:
            self.token = token

        # Update the session headers
        self.__updateSessionHeaders()

        # Start the refresher
        self.__startRefresher()

        getLogger().info("Successfully connected to PlanQK API.")

        return self

    def __updateSessionHeaders(self):
        """Update the session headers with the current token."""
        with self.token_lock:
            token = self.token

        if token is None:
            raise MimiqConnectionError("Not yet authenticated.")

        self.session.headers.update({"Authorization": f"Bearer {token.access_token}"})

    def __startRefresher(self):
        """Start the token refresher thread."""
        # If the refresher is already running, stop it
        # Join outside the lock: the refresher takes it to read the stop flag.
        if self.refresher_task is not None and self.refresher_task.is_alive():
            with self.token_lock:
                self.refresher_stop = True
            self.refresher_task.join()

        with self.token_lock:
            self.refresher_stop = False

        # Create and start the refresher
        self.refresher_task = threading.Thread(target=self.__refresherMain, daemon=True)
        self.refresher_task.start()

    def __refresherMain(self):
        """Token refresher main function.

        Will refresh the token before it expires.
        """
        while True:
            # Get the current token and its expiration time
            with self.token_lock:
                token = self.token

            if token is None:
                break

            # Sleep for 80% of the token's lifetime
            sleep_time = int(token.expires_in * 0.8)

            # Check the stop flag every second
            for _ in range(sleep_time):
                time.sleep(1)
                with self.token_lock:
                    if self.refresher_stop:
                        break

            with self.token_lock:
                if self.refresher_stop:
                    break

            # Get a new token
            try:
                getLogger().debug("Refreshing PlanQK token")
                new_token = self.get_planqk_token(
                    self.consumer_key, self.consumer_secret
                )

                with self.token_lock:
                    self.token = new_token

                self.__updateSessionHeaders()
                getLogger().debug(
                    f"Successfully refreshed PlanQK token. New expiration: {new_token.expires_in}s"
                )
            except Exception as e:
                getLogger().error(f"Failed to refresh PlanQK token: {e}")

    def close(self):
        """Stop the token refresher and forget the token."""
        getLogger().info(f"Closing connection to PlanQK API ({self.url})")

        # Ask the refresher to stop
        with self.token_lock:
            self.refresher_stop = True

        # Join outside the lock: the refresher takes it to read the stop flag.
        if self.refresher_task is not None and self.refresher_task.is_alive():
            getLogger().info("Shutting down token refresher")
            self.refresher_task.join()
            getLogger().info(f"Task (done) @{hex(id(self.refresher_task))}")

        with self.token_lock:
            self.token = None

    def isOpen(self):
        """Return True if the connection has a token and its refresher is running."""
        return (
            self.refresher_task is not None
            and self.refresher_task.is_alive()
            and self.token is not None
        )

    def checkAuth(self):
        """Check that the connection holds a token.

        Raises:
            MimiqConnectionError: If the connection is not authenticated.
        """
        with self.token_lock:
            if self.token is None:
                raise MimiqConnectionError("Not yet authenticated to PlanQK API.")

    def __str__(self):
        result = f"PlanqkConnection:\n├── url: {self.url}\n"

        with self.token_lock:
            if self.token:
                result += f"├── token_type: {self.token.token_type}\n"
                result += f"├── expires_in: {self.token.expires_in}s\n"

        result += "└── status: " + ("open" if self.isOpen() else "closed")

        return result

    def __repr__(self) -> str:
        return self.__str__()
