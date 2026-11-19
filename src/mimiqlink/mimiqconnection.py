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
import os
import threading
import webbrowser
from urllib.parse import urljoin
import time
from mimiqlink.abstractconnection import AbstractConnection, MimiqConnectionError

# Import the connection handler
from mimiqlink.handler import AuthenticationHandler

# Import the logging utils
from mimiqlink.utils import getLogger

QPERFECT_CLOUD = "https://mimiq.qperfect.io"


class MimiqConnection(AbstractConnection):
    """Connection to the MIMIQ cloud services.

    It authenticates to the service, keeps the access token fresh with a
    background thread that refreshes it every 15 minutes, and sends the
    requests defined in :class:`AbstractConnection`. The object starts
    unauthenticated: call :meth:`connect` or :meth:`loadtoken` first.

    Most users reach this class through ``mimiqcircuits.MimiqConnection``,
    which adds circuit submission and result retrieval on top of it.

    Args:
        url (str, optional): The URL of the service. Defaults to None
            (:data:`QPERFECT_CLOUD`).

    Examples:
        >>> from mimiqlink import MimiqConnection

        Log in through a page opened in the browser.

        >>> conn = MimiqConnection()
        >>> conn.connect()  # doctest: +SKIP

        Save the refresh token, and reuse it later without logging in again.

        >>> conn.savetoken("qperfect.json")  # doctest: +SKIP
        >>> conn = MimiqConnection().loadtoken("qperfect.json")  # doctest: +SKIP

        List the past executions and inspect one of them.

        >>> jobs = conn.requests()  # doctest: +SKIP
        >>> conn.requestInfo(jobs[0].id).status  # doctest: +SKIP
        'DONE'

        Log out.

        >>> conn.close()  # doctest: +SKIP
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
        """Return the URL of an API endpoint: ``<url>/api/<paths...>``."""
        base = urljoin(self.url + "/", "api")
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
            raise MimiqConnectionError(
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
        """Log in with an email address and a password.

        Closes the connection first if it is open.

        Args:
            email (str): The account's email address.
            password (str): The account's password.

        Returns:
            MimiqConnection: This connection.

        Raises:
            MimiqConnectionError: If the service refuses the credentials.
        """

        if self.isOpen():
            self.close()

        self._weblogin({"email": email, "password": password})

        return self

    def connectToken(self, token):
        """Log in with a refresh token.

        Closes the connection first if it is open. The token is the one
        :meth:`savetoken` writes to the ``"token"`` field of its file.

        Args:
            token (str): The refresh token.

        Returns:
            MimiqConnection: This connection.

        Raises:
            MimiqConnectionError: If the service refuses the token.
        """

        if self.isOpen():
            self.close()

        # set the refresh token
        with self.refresher_lock:
            self.refresh_token = token

        # refresh
        status = self.refresh()

        if not status:
            raise MimiqConnectionError("Authentication failed.")

        getLogger().info("Authentication successful.")
        self.__updateSessionHeaders()
        self.__updateUserLimits()
        self.__startRefresher()
        return self

    def connectWeb(self):
        """Log in through a login page served locally and opened in the browser.

        Closes the connection first if it is open. The page is served on
        ``localhost`` port 1444, or on a free port if that one is taken, and
        the call blocks until the login succeeds.

        Returns:
            MimiqConnection: This connection.

        Raises:
            MimiqConnectionError: If no access token is obtained.
        """

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
            raise MimiqConnectionError(
                "Authentication failed. Unable to obtain access token."
            )

        return self

    def connect(self, *args, **kwargs):
        """Log in to the service.

        The arguments choose how:

        - ``connect()`` logs in through a page opened in the browser
          (:meth:`connectWeb`).
        - ``connect(token)`` uses a refresh token (:meth:`connectToken`).
        - ``connect(email, password)`` uses credentials
          (:meth:`connectUser`).

        If the connection is already open, nothing happens.

        Returns:
            MimiqConnection: This connection.

        Raises:
            MimiqConnectionError: If the login fails, or more than two
                positional arguments are given.

        Examples:
            >>> from mimiqlink import MimiqConnection

            Browser login.

            >>> conn = MimiqConnection().connect()  # doctest: +SKIP

            Login with a refresh token.

            >>> conn = MimiqConnection().connect("my-refresh-token")  # doctest: +SKIP

            Login with credentials.

            >>> conn = MimiqConnection().connect("john.doe@example.com", "password")  # doctest: +SKIP
        """
        if self.isOpen():
            return self

        if len(args) == 0:
            return self.connectWeb()

        if len(args) == 1:
            return self.connectToken(*args)

        if len(args) == 2:
            return self.connectUser(*args)

        raise MimiqConnectionError(
            "Invalid number of arguments. Expected 0, 1 (token) or 2 (username, password)."
        )

    def __startRefresher(self):
        """Start the refresher thread."""

        # if the refresher is already running stop it
        with self.refresher_lock:
            self.refresher_stop = True
            running = self.refresher_task

        # The refresher takes the lock once a second, so it can only see the
        # stop flag while the lock is released: joining under it never returns.
        if running is not None and running.is_alive():
            running.join()

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
        """Exchange the refresh token for a new access token and refresh token.

        The background thread calls this every 15 minutes; call it by hand
        only to force a refresh. It also updates the user's limits.

        Returns:
            bool: True.

        Raises:
            MimiqConnectionError: If the service refuses the refresh token.
        """
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
            raise MimiqConnectionError(
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
        """Check that the connection holds an access token.

        Raises:
            MimiqConnectionError: If the connection is not authenticated.
        """
        with self.refresher_lock:
            if self.access_token is None:
                raise MimiqConnectionError("Not yet authenticated.")

    def savetoken(self, filepath="qperfect.json"):
        """Save the refresh token and the service URL to a JSON file.

        The file is created readable by its owner only. :meth:`loadtoken`
        reads the file back. If the connection has no token yet, it logs in
        first with :meth:`connect`, which opens the browser login page.

        Args:
            filepath (str): The file to write. Defaults to
                ``"qperfect.json"``.

        Warning:
            The file grants access to the account. Keep it private.
        """
        if self.refresh_token is None:
            self.connect()
        fd = os.open(filepath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"token": self.refresh_token, "url": self.url}, f)

    def loadtoken(self, filepath="qperfect.json"):
        """Log in with a refresh token saved by :meth:`savetoken`.

        Args:
            filepath (str): The file to read. Defaults to ``"qperfect.json"``.

        Returns:
            MimiqConnection: This connection.

        Raises:
            MimiqConnectionError: If the file cannot be read, was saved for a
                different URL, or the service refuses the token.
        """
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
            raise MimiqConnectionError("Failed to read token file.") from e

        # Establish a new connection using the token
        try:
            self.connectToken(token)
            return self
        except MimiqConnectionError as e:
            # Log error and re-raise
            getLogger().error(f"Authentication failed: {e}")
            raise MimiqConnectionError(
                "Authentication failed. Unable to connect using the stored token."
            ) from e

    def close(self):
        """Stop the token refresher and forget the tokens.

        The tokens are not revoked on the service.
        """
        getLogger().info(f"Closing connection to {self.url}")
        # ask the refresher to stop
        with self.refresher_lock:
            self.refresher_stop = True
            task = self.refresher_task

        # Joining under the lock deadlocks: the refresher needs the same lock
        # once a second to notice that it was asked to stop.
        if task is not None and task.is_alive():
            getLogger().info("Shutting down token refresher")
            task.join()
            getLogger().info(f"Task (done) @{hex(id(task))}")

        # clean the tokens
        self.access_token = None
        self.refresh_token = None

    def isOpen(self):
        """Return True if the connection has an access token and its refresher is running."""
        return (
            self.refresher_task is not None
            and self.refresher_task.is_alive()
            and self.access_token is not None
        )

    def checkUserLimits(self, limits=None):
        """Log a warning for each usage limit the account has exceeded.

        Checks the computing time and the number of executions. The service
        does not change state.

        Args:
            limits (dict, optional): The limits to check, as returned by the
                service. Defaults to None (the limits fetched at the last
                login or token refresh).
        """
        if limits is None:
            limits = self.user_limits

        if limits is None:
            return

        if limits.get("enabledExecutionTime"):
            # The service reports seconds.
            used_time = limits.get("usedExecutionTime")
            max_time = limits.get("maxExecutionTime")
            if used_time is not None and max_time is not None and used_time > max_time:
                getLogger().warning(
                    f"You have exceeded your computing time limit of {round(max_time / 60)} minutes"
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
            raise MimiqConnectionError(
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
