#
# Copyright © 2022-2024 University of Strasbourg. All Rights Reserved.
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

from functools import partial
from http.server import HTTPServer
import json
import threading
import webbrowser
from urllib.parse import urljoin
import time
from mimiqlink.abstractconnection import AbstractConnection

# Import the connection handler
from mimiqlink.handler import AuthenticationHandler

# Import the logging utils
from mimiqlink.utils import getLogger

QPERFECT_CLOUD = "https://mimiq.qperfect.io"
QPERFECT_DEV = "https://mimiqfast.qperfect.io"


class MimiqConnection(AbstractConnection):
    """Connection to the MIMIQ remote services.

    It handles the authentication and the requests.
    """

    def __init__(self, url=None):
        if url is None:
            url = QPERFECT_CLOUD

        super().__init__(url)

        # refresher related variables
        self.refresher_lock = threading.Lock()
        self.refresher_task = None
        self.refresher_interval = 15 * 60
        self.refresher_stop = False

        # tokens
        self.access_token = None
        self.refresh_token = None

        # user limits
        self.user_limits = None

    def get_api_url(self, *paths):
        """Get the API URL for the given paths."""
        base = urljoin(self.url, "api")
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

    def _weblogin(self, data):
        """Authenticate to the remote server with the given credentials. But return the response."""
        endpoint = "sign-in"

        # ask for access tokens
        response = self.session.post(
            self.get_api_url(endpoint), json=data, headers={"Connection": "close"}
        )

        if response.status_code != 200:
            reason = response.json().get("message", "Unknown error")
            raise ConnectionError(
                f"Authentication failed with status code {response.status_code} and reason: {reason}"
            )

        tokens = response.json()

        # set the access tokens
        with self.refresher_lock:
            self.access_token = tokens["token"]
            self.refresh_token = tokens["refreshToken"]

        self.__updateSessionHeaders()
        self.__updateUserLimits()
        self.__startRefresher()

        getLogger().info("Authentication successful.")

        return response

    def connectUser(self, email, password):
        """Authenticate to the remote server with the given credentials (email and password)."""

        if self.isOpen():
            self.close()

        self._weblogin({"email": email, "password": password})

        return self

    def connectToken(self, token):
        """Authenticate to the remote server with the given refresh token"""

        if self.isOpen():
            self.close()

        # set the refresh token
        with self.refresher_lock:
            self.refresh_token = token

        # refresh
        status = self.refresh()

        if not status:
            raise ConnectionError("Authentication failed.")

        getLogger().info("Authentication successful.")
        self.__updateSessionHeaders()
        self.__updateUserLimits()
        self.__startRefresher()
        return self

    def connectWeb(self):
        """Authenticate to the remote services by taking credentials from a locally shown login page"""

        if self.isOpen():
            self.close()

        preferred_port = 1444

        h = partial(AuthenticationHandler, lambda data: self._weblogin(data))

        try:
            # Attempt to create the server with the fixed port
            httpd = HTTPServer(("localhost", preferred_port), h)
            port = preferred_port
        except OSError:
            # If the fixed port is in use, use a random available port
            httpd = HTTPServer(("localhost", 0), h)
            port = httpd.server_port

        getLogger().info(
            f"Listening on: 127.0.0.1:{port}, thread id: {threading.get_ident()}"
        )
        getLogger().info(f"Please login in your browser at http://localhost:{port}")

        webbrowser.open(f"http://localhost:{port}", new=2)

        with httpd:
            while self.access_token is None:
                httpd.handle_request()

        if not self.access_token:
            raise ConnectionError(
                "Authentication failed. Unable to obtain access token."
            )

        return self

    def connect(self, *args, **kwargs):
        """Connect to the remote server.

        If no arguments are provided, the connection will be established using the web login.
        If one argument is provided, it will be used as the token.
        If two arguments are provided, they will be used as the email and password.

        Examples:

        - Connect using the web login:

        >>> conn = MimiqConnection()
        >>> conn.connect()

        or simply:

        >>> conn = MimiqConnection().connect()

        - Connect using a token:

        >>> conn = MimiqConnection()
        >>> conn.connect("mytoken")

        or simply:

        >>> conn = MimiqConnection().connect("mytoken")

        - Connect using a token and a user:

        >>> conn = MimiqConnection()
        >>> conn.connect("john.doe@example.com", "password")
        """
        if self.isOpen():
            return self

        if len(args) == 0:
            return self.connectWeb()

        if len(args) == 1:
            return self.connectToken(*args)

        if len(args) == 2:
            return self.connectUser(*args)

        raise ConnectionError(
            "Invalid number of arguments. Expected 0, 1 (token) or 2 (username, password)."
        )

    def __startRefresher(self):
        """Start the refresher thread."""

        # if the refresher is alreeady running stop it
        with self.refresher_lock:
            if self.refresher_task is not None and self.refresher_task.is_alive():
                self.refresher_stop = True
                self.refresher_task.join()

        # ensure that the refresher is not stopped immediately
        with self.refresher_lock:
            self.refresher_stop = False

        # create and start the refresher
        self.refresher_task = threading.Thread(target=self.__refresherMain, daemon=True)
        self.refresher_task.start()

    def __refresherMain(self):
        """Refresher function
        Will refresh the access token with the refresh token at every
        configured interval.
        """
        while True:
            # check the stop flag every second
            for i in range(self.refresher_interval):
                time.sleep(1)
                with self.refresher_lock:
                    if self.refresher_stop:
                        break

            with self.refresher_lock:
                if self.refresher_stop:
                    break

            self.refresh()

    def refresh(self):
        """Refresh the access token using the refresh token."""
        endpoint = "/access-token"

        # prepare the request
        with self.refresher_lock:
            data = {"refreshToken": self.refresh_token}

        # ask for a new access token
        response = self.session.post(
            self.get_api_url(endpoint), json=data, headers={"Connection": "close"}
        )

        # check if the response is valid
        if response.status_code != 200:
            raise ConnectionError(
                f"Failed to refresh the access token. Server responded with {response.status_code}"
            )

        tokens = response.json()

        # write the new tokens
        with self.refresher_lock:
            self.access_token = tokens["token"]
            self.refresh_token = tokens["refreshToken"]

        self.__updateSessionHeaders()
        self.__updateUserLimits()
        return True

    def __updateSessionHeaders(self):
        # fetch the access token
        with self.refresher_lock:
            token = self.access_token

        # build the headers
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def checkAuth(self):
        with self.refresher_lock:
            if self.access_token is None:
                raise ConnectionError("Not yet authenticated.")

    def savetoken(self, filepath="qperfect.json"):
        """Save the current token to a file."""
        if self.refresh_token is None:
            self.connect()
        with open(filepath, "w") as f:
            json.dump({"token": self.refresh_token, "url": self.url}, f)

    def loadtoken(self, filepath="qperfect.json"):
        """Load and connect using a token from a file."""
        # Attempt to read the token file
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
                saved_url = data.get("url", "")
                token = data.get("token")

            # Check if the current URL matches the saved URL in the token file
            if self.url != saved_url:
                raise ValueError(
                    f"The URL in the token file ({saved_url}) does not match the current URL ({self.url}). Authentication failed."
                )

        except Exception as e:
            # Log error and re-raise as ConnectionError
            getLogger().error(f"Error reading token file: {e}")
            raise ConnectionError("Failed to read token file.") from e

        # Establish a new connection using the token
        try:
            self.connectToken(token)
            return self
        except ConnectionError as e:
            # Log error and re-raise
            getLogger().error(f"Authentication failed: {e}")
            raise ConnectionError(
                "Authentication failed. Unable to connect using the stored token."
            ) from e

    def close(self):
        """Close the connection."""
        getLogger().info(f"Closing connection to {self.url}")
        # ask the refresher to stop
        with self.refresher_lock:
            self.refresher_stop = True
            if self.refresher_task is not None and self.refresher_task.is_alive():
                getLogger().info("Shutting down token refresher")
                self.refresher_task.join()
                getLogger().info(f"Task (done) @{hex(id(self.refresher_task))}")

        # clean the tokens
        self.access_token = None
        self.refresh_token = None

    def isOpen(self):
        """Check if the connection is open."""
        return (
            self.refresher_task is not None
            and self.refresher_task.is_alive()
            and self.access_token is not None
        )

    def checkUserLimits(self, limits=None):
        """Check if the user limits are respected."""
        if limits is None:
            limits = self.user_limits

        if limits is None:
            return

        if limits.get("enabledExecutionTime"):
            used_time = limits.get("usedExecutionTime")
            max_time = limits.get("maxExecutionTime")
            if used_time > max_time:
                getLogger().warning(
                    f"You have exceeded your computing time limit of {max_time} minutes"
                )

        if limits.get("enabledMaxExecutions"):
            used_exec = limits.get("usedExecutions")
            max_exec = limits.get("maxExecutions")
            if used_exec is not None and max_exec is not None:
                if used_exec > max_exec:
                    getLogger().warning(
                        f"You have exceeded your number of executions limit of {max_exec}"
                    )

    def __updateUserLimits(self):
        """Fetch user limits from the server."""
        self.checkAuth()

        endpoint = "users/limits"

        response = self.session.get(self.get_api_url(endpoint))

        if response.status_code != 200:
            raise ConnectionError(
                f"Failed to retrieve user limits. Server responded with {response.status_code}"
            )

        self.user_limits = response.json()
        self.checkUserLimits()

    def __str__(self):
        limits = self.user_limits
        result = f"MimiqConnection:\n├── url: {self.url}\n"

        if limits is not None:
            if limits.get("enabledExecutionTime"):
                used_time = limits.get("usedExecutionTime")
                max_time = limits.get("maxExecutionTime")
                if used_time is not None and max_time is not None:
                    result += f"├── Computing time: {round(used_time / 60)}/{round(max_time / 60)} minutes\n"
            if limits.get("enabledMaxExecutions"):
                used_exec = limits.get("usedExecutions")
                max_exec = limits.get("maxExecutions")
                if used_exec is not None and max_exec is not None:
                    result += f"├── Executions: {used_exec}/{max_exec}\n"
            if limits.get("enabledMaxTimeout"):
                max_timeout = limits.get("maxTimeout")
                if max_timeout is not None:
                    max_timeout = round(max_timeout)
                    result += f"├── Max time limit per request: {max_timeout} minutes\n"
                    result += f"├── Default time limit is equal to max time limit: {max_timeout} minutes\n"
            else:
                result += "├── Max time limit is: 30 minutes\n"
                result += "├── Default time limit is: 30 minutes\n"

        result += "└── status: " + ("open" if self.isOpen() else "closed")

        return result

    def __repr__(self) -> str:
        return self.__str__()
