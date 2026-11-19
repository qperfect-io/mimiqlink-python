#
# Copyright © 2022-2026 QPerfect. All Rights Reserved.
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

import secrets
import requests
import webbrowser
from os.path import basename
from urllib.parse import urlparse
from functools import partial
from http.server import HTTPServer
from keycloak import KeycloakOpenID
from io import IOBase
import os
import json

# Import the logging utils
from mimiqlink.utils import getLogger
from mimiqlink.infos import RequestInfo, RequestInfoList
from mimiqlink.openidhandler import OpenIdConnectCallbackHandler
from mimiqlink.abstractconnection import AbstractConnection, MimiqConnectionError

QPERFECT_CLOUD_V2 = "https://mimiq.qperfect.io/v2/api"
_QPERFECT_AUTH_CLOUD_V2 = "https://mimiq.qperfect.io/auth"

QPERFECT_DEV = "https://mimiqfast.qperfect.io/api"
_QPERFECT_AUTH_DEV = "https://mimiqfast.qperfect.io/auth/"

class QhiveConnection(AbstractConnection):
    """Connection to the Quantum Hive services.

    Quantum Hive authenticates through Keycloak (OpenID Connect). Requests
    carry the access token, and a request refused with status 401 refreshes
    the token and is retried once. The object starts unauthenticated: call
    :meth:`connect` or :meth:`loadtoken` first.

    Most users reach this class through ``mimiqcircuits.MimiqConnection``,
    which picks it for the Quantum Hive URLs.

    Args:
        url (str, optional): The URL of the API. Defaults to None
            (:data:`QPERFECT_CLOUD_V2`).
        auth_url (str, optional): The URL of the Keycloak server. Defaults
            to None, which picks the server that matches
            :data:`QPERFECT_CLOUD_V2` or :data:`QPERFECT_DEV`.

    Examples:
        >>> from mimiqlink import QhiveConnection

        Log in through the browser, then save the session for later.

        >>> conn = QhiveConnection().connect()  # doctest: +SKIP
        >>> conn.savetoken("qperfect.json")  # doctest: +SKIP

        Resume the session from the file.

        >>> conn = QhiveConnection().loadtoken("qperfect.json")  # doctest: +SKIP
        >>> conn.requests()  # doctest: +SKIP
    """

    def __init__(self, url=None, auth_url=None):
        super().__init__(QPERFECT_CLOUD_V2 if url is None else url)
        if auth_url is None:
            auth_url = _QPERFECT_AUTH_DEV if self.url == QPERFECT_DEV else _QPERFECT_AUTH_CLOUD_V2
        self.auth_url = auth_url

        self.access_token = None
        self.refresh_token = None

        # URL normalization
        if self.url.endswith("/"):
            self.url = self.url[:-1]
        if not self.auth_url.endswith("/"):
            self.auth_url += "/"

        self.openid = keycloak_openid = KeycloakOpenID(
            server_url=self.auth_url,
            client_id="qhive-frontend",
            realm_name="qhive"
        )

    def connect(self, *args, **kwargs):
        """Log in to the service.

        The arguments choose how:

        - ``connect()`` opens the Keycloak login page in the browser and
          waits for the redirect on ``localhost`` port 1444 (or a free port).
        - ``connect(token)`` uses a Keycloak token dictionary with
          ``"access_token"`` and ``"refresh_token"`` entries.
        - ``connect(email, password)`` uses credentials.

        If the connection is already open, nothing happens.

        Returns:
            QhiveConnection or None: This connection, or None when the token
            or credentials do not give a session the server accepts.

        Raises:
            MimiqConnectionError: If the browser login fails, the token is
                not a dictionary with ``"access_token"`` and
                ``"refresh_token"`` entries, or more than two positional
                arguments are given.
            keycloak.exceptions.KeycloakError: If Keycloak refuses the
                credentials.
        """
        if self.isOpen():
            return self

        if len(args) == 0:
            return self._connectStandard()

        if len(args) == 1:
            return self._connectToken(*args)

        if len(args) == 2:
            return self._connectDirect(*args)

        raise MimiqConnectionError(
            "Invalid number of arguments. Expected 0, 1 (token) or 2 (username, password)."
        )

    def close(self):
        """Log out of Keycloak and forget the tokens.

        A failed logout is ignored.
        """
        try:
            if self.access_token is not None:
                self.openid.logout(self.refresh_token)
        except Exception as e:
            getLogger().debug(f"Logout failed: {e}")
        finally:
            self.access_token = None
            self.refresh_token = None

    def isOpen(self):
        """Return True if the access token is accepted by the server.

        Queries the server on every call.
        """
        if self.access_token == None or self.refresh_token == None:
            return False
        return self.checkAuth()

    def checkAuth(self):
        """Return True if the access token is accepted by the server, False otherwise.

        Unlike :meth:`MimiqConnection.checkAuth`, it does not raise.
        """
        if self.access_token is None or self.refresh_token == None:
            return False
        try:
            user = self.openid.userinfo(self.access_token)
        except Exception as e:
            getLogger().debug(f"userinfo check failed: {e}")
            return False
        return bool(user)

    def get_api_url(self, *paths):
        """Not available for Quantum Hive.

        Raises:
            MimiqConnectionError: Always.
        """
        raise MimiqConnectionError("Not applicable to QHive connection")

    def _connectStandard(self):
        preferred_port = 1444
        random_state = secrets.token_hex(16)
        h = partial(OpenIdConnectCallbackHandler, random_state, self.openid, self._acceptToken)

        try:
            # Attempt to create the server with the fixed port
            httpd = HTTPServer(("localhost", preferred_port), h)
            port = preferred_port
        except OSError:
            # If the fixed port is in use, use a random available port
            httpd = HTTPServer(("localhost", 0), h)
            port = httpd.server_port

        auth_url = self.openid.auth_url(
            redirect_uri=f"http://localhost:{port}/callback",
            scope="openid",
            state=random_state)
        webbrowser.open(auth_url, new=2)

        httpd.auth_failed = False
        with httpd:
            while self.access_token is None and not httpd.auth_failed:
                httpd.handle_request()

        if not self.access_token:
            raise MimiqConnectionError(
                "Authentication failed. Unable to obtain access token."
            )
        return self
    
    def _connectToken(self, token):
        if not (
            isinstance(token, dict) and 'access_token' in token and 'refresh_token' in token
        ):
            raise MimiqConnectionError(
                "Expected a token dictionary with 'access_token' and 'refresh_token'."
            )
        self.access_token = token['access_token']
        self.refresh_token = token['refresh_token']
        return self if self.checkAuth() else None

    def _connectDirect(self, email, password):
        token = self.openid.token(email, password)
        return self._connectToken(token)

    def _acceptToken(self, token):
        if isinstance(token, dict) and 'access_token' in token:
            self.access_token = token['access_token']
            self.refresh_token = token['refresh_token']

    def _refreshToken(self):
        if not self.refresh_token:
            return False
        try:
            token = self.openid.refresh_token(self.refresh_token)
        except Exception as e:
            getLogger().debug(f"Token refresh failed: {e}")
            return False
        if isinstance(token, dict) and 'refresh_token' in token:
            self._acceptToken(token)
            return True
        return False




    def _assertConnection(self):
        if self.access_token is None:
            raise MimiqConnectionError("Connection is not open, make sure you are connected")
        if not self.isOpen() and not self._refreshToken():
            raise MimiqConnectionError("Stale connection, please connect again")

    def _authenticatedRequest(self, endpoint, method="GET", headers=None, **kwargs):
        headers = {} if headers is None else headers # Fresh blank dict
        headers["Authorization"] = f"Bearer {self.access_token}"
        url = self.url + endpoint
        response = requests.request(method, url, headers=headers, **kwargs)
        if response.status_code == 401 and self._refreshToken():
            headers["Authorization"] = f"Bearer {self.access_token}"
            response = requests.request(method, url, headers=headers, **kwargs)
        return response




    def request(self, emulatortype, algorithm, label, timeout, uploads):
        """Upload files and create an execution on the service.

        ``request.json`` and ``circuits.json`` are sent with the job; every
        other file is uploaded as a circuit file. The job is then committed
        for execution.

        Args:
            emulatortype (str): The type of executor, for example ``"CIRC"``.
            algorithm (str): The simulation algorithm.
            label (str): A label to identify the execution.
            timeout (int): The time limit of the execution, in minutes.
            uploads (list): The files to upload, as paths or open binary file
                objects.

        Returns:
            str: The identifier of the new execution.

        Raises:
            MimiqConnectionError: If the connection is not open or the
                service refuses a step.
        """
        self._assertConnection()

        form_data = {
            "algorithm": algorithm,
            "label": label,
            "emuType": emulatortype,
            "timeout": timeout,
        }

        new_requests_params = {
            "circuits.json": "parameters",
            "request.json": "request"
        }
        file_uploads = []
        circuit_files = []

        # Split uploads into the circuits and non-circuits
        for file in uploads:
            if isinstance(file, IOBase) and not file.closed:
                filename = basename(file.name)
                upload = file
            else:
                filename = basename(file)
                upload = open(file, "rb")

            if filename in new_requests_params.keys():
                file_uploads.append((new_requests_params[filename], upload))
            else:
                circuit_files.append(dict(filename=filename, upload=upload))

        response = self._authenticatedRequest("/jobs", "POST", data=form_data, files=file_uploads)

        if response.status_code != 200: 
            raise MimiqConnectionError(f"Failed to create request with status code {response.status_code}")
        requestId = response.text

        for file in circuit_files:
            response = self._authenticatedRequest(f"/files/{requestId}/circuit/{file['filename']}", "POST", data=file["upload"])
            if response.status_code != 201: #Created
                raise MimiqConnectionError(f"Failed upload circuit file with status code {response.status_code}")
        
        response = self._authenticatedRequest(f"/jobs/{requestId}/commit", "PATCH")
        if response.status_code != 200: 
            raise MimiqConnectionError(f"Failed job commit with status code {response.status_code}")

        return requestId

    def requestInfo(self, request):
        """Fetch the details of an execution.

        Args:
            request (str): The execution identifier.

        Returns:
            RequestInfo: The execution's details.

        Raises:
            MimiqConnectionError: If the connection is not open or the
                service refuses the request.
        """
        self._assertConnection()

        response = self._authenticatedRequest(f"/jobs/{request}")

        if response.status_code != 200:
            raise MimiqConnectionError(
                f"Failed to retrieve execution details for {request}. Server responded with {response.status_code}"
            )

        return RequestInfo(response.json())

    def requests(self, **kwargs):
        """Fetch the list of the user's executions.

        Args:
            **kwargs: Accepted for compatibility and not used.

        Returns:
            RequestInfoList: The executions.

        Raises:
            MimiqConnectionError: If the connection is not open or the
                service refuses the request.
        """
        self._assertConnection()

        response = self._authenticatedRequest(f"/jobs")
        if response.status_code != 200:
            raise MimiqConnectionError(
                f"Failed to retrieve the list of requests. Server responded with {response.status_code}"
            )

        return RequestInfoList(response.json())

    def isJobDone(self, request):
        """Return True if the execution's status is ``ERROR``, ``SUCCESSFUL`` or ``CANCELED``."""
        infos = self.requestInfo(request)
        status = infos.status
        return status in ["ERROR", "SUCCESSFUL", "CANCELED"]

    def isJobFailed(self, request):
        """Return True if the execution's status is ``ERROR``."""
        infos = self.requestInfo(request)
        status = infos.status
        return status == "ERROR"

    def isJobStarted(self, request):
        """Return True if the execution's status is ``COMMITED``, ``PROCESSED`` or ``AUTHORIZED``."""
        infos = self.requestInfo(request)
        status = infos.status
        return status in ["COMMITED", "PROCESSED", "AUTHORIZED"]

    def isJobCanceled(self, request):
        """Return True if the execution's status is ``CANCELED``."""
        infos = self.requestInfo(request)
        status = infos.status
        return status == "CANCELED"

    def stopexecution(self, request):
        """Cancel an execution. Same as :meth:`stopExecution`."""
        self._assertConnection()

        response = self._authenticatedRequest(f"/jobs/{request}/cancel", "PATCH")
        if response.status_code != 200:
            raise MimiqConnectionError(
                f"Failed to stop the execution {request}. Server responded with {response.status_code}."
            )

        return None

    def stopExecution(self, request):
        """Cancel an execution.

        Args:
            request (str): The execution identifier.

        Raises:
            MimiqConnectionError: If the connection is not open or the
                service refuses the request.
        """
        self._assertConnection()

        response = self._authenticatedRequest(f"/jobs/{request}/cancel", "PATCH")
        if response.status_code != 200:
            raise MimiqConnectionError(
                f"Failed to stop the execution {request}. Server responded with {response.status_code}."
            )

        return None

    def deleteFiles(self, request):
        """Delete an execution's files from the service.

        Args:
            request (str): The execution identifier.

        Raises:
            MimiqConnectionError: If the connection is not open, the
                execution has not completed, or the service refuses the
                request.
        """
        self._assertConnection()

        response = self._authenticatedRequest(f"/files/{request}", "DELETE")
        if response.status_code == 200:
            raise MimiqConnectionError("Could not delete files for job because it is not completed")
        if response.status_code != 202:
            raise MimiqConnectionError(f"Failed to delete files for job. Server responded with {response.status_code}.")
        return None


    def savetoken(self, filepath="qperfect.json"):
        """Save the refresh token and the service URLs to a JSON file.

        The file is created readable by its owner only. :meth:`loadtoken`
        reads it back.

        Args:
            filepath (str): The file to write. Defaults to
                ``"qperfect.json"``.

        Raises:
            MimiqConnectionError: If the connection is not open.

        Warning:
            The file grants access to the account. Keep it private.
        """
        self._assertConnection()
        fd = os.open(filepath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(dict(token=self.refresh_token, url=self.url, auth_url=self.auth_url), f)

    def loadtoken(self, filepath="qperfect.json"):
        """Log in with a refresh token saved by :meth:`savetoken`.

        Args:
            filepath (str): The file to read. Defaults to ``"qperfect.json"``.

        Returns:
            QhiveConnection: This connection.

        Raises:
            MimiqConnectionError: If the file cannot be read, was saved for
                different URLs, or the token can no longer be refreshed.
        """
        
        # Attempt to read the token file
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
                saved_url = data.get("url", "")
                saved_auth_url = data.get("auth_url", "")
                token = data.get("token")
        except Exception as e:
            # Log error and re-raise as ConnectionError
            getLogger().error(f"Error reading token file: {e}")
            raise MimiqConnectionError("Failed to read token file.") from e

        # Check if the current URLs match the saved URLs in the token file
        if self.url != saved_url:
            raise MimiqConnectionError(
                f"The URL in the token file ({saved_url}) does not match the current URL ({self.url})."
            )
        if self.auth_url != saved_auth_url:
            raise MimiqConnectionError(
                f"The authentication URL in the token file ({saved_auth_url}) does not match the current authentication URL ({self.auth_url})."
            )

        self.refresh_token = token
        self.access_token = None
        if not self._refreshToken():
            raise MimiqConnectionError("Failed to refresh connection using token, perhaps the token is stale and you must connect again")
        self._assertConnection()
        return self

    def downloadFile(self, request, index, filetype, destdir):
        """Download one file of an execution.

        Args:
            request (str): The execution identifier.
            index (str): The name of the file on the service, also used as
                the local file name.
            filetype (str): The kind of file, for example ``"results"``.
            destdir (str): The directory to write to, created if missing.

        Returns:
            str: ``index``.

        Raises:
            MimiqConnectionError: If the connection is not open or the
                download fails.
        """
        self._assertConnection()

        response = self._authenticatedRequest(f"/files/{request}/{filetype}/{index}", "GET", allow_redirects=True)
        if response.status_code >= 300:
            raise MimiqConnectionError(
                f"Failed to retrieve {filetype} files for {request}. Server responded with {response.status_code}"
            )

        # Create directory if it doesn't exist
        if not os.path.exists(destdir):
            os.makedirs(destdir)

        # at this point we should have a valid filename and a valid directory
        # so we write everything to the file
        with open(os.path.join(destdir, index), "wb") as f:
            f.write(response.content)

        return index

    def downloadFiles(self, request, source, destdir=None):
        """Download all files of one kind for an execution.

        Args:
            request (str): The execution identifier.
            source (str): ``"uploads"`` or ``"results"``.
            destdir (str, optional): The directory to write to, created if
                missing. Defaults to None (a directory named after
                ``request`` in the current directory).

        Returns:
            list[str]: The names of the written files.

        Raises:
            MimiqConnectionError: If the connection is not open or the list
                of files cannot be fetched.
            requests.HTTPError: If a file download fails.
        """
        self._assertConnection()

        response = self._authenticatedRequest(f"/files/{request}/{source}")
        if response.status_code != 200:
            raise MimiqConnectionError(
                f"Failed to retrieve files for {request}. Server responded with {response.status_code}"
            )
        urlsToDownload = response.json()

        if destdir is None:
            destdir = os.path.join("./", request)
        if not os.path.exists(destdir):
            os.makedirs(destdir)

        names = []
        for url in urlsToDownload:
            urlpath = urlparse(url).path
            filename = basename(urlpath)
            filepath = os.path.join(destdir, filename)
            
            response = requests.get(url)
            response.raise_for_status()
            
            with open(filepath, "wb") as out:
                out.write(response.content)
            names.append(filename)
        return names



