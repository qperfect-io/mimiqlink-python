#
# Copyright © 2022-2024 University of Strasbourg. All Rights Reserved.
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
import logging
import os
import os.path
import io
import re
import json
import requests
from requests.adapters import HTTPAdapter
import threading
import webbrowser


# import the connection handler
from mimiqlink.handler import AuthenticationHandler

QPERFECT_CLOUD = "https://mimiq.qperfect.io/api"

QPERFECT_CLOUD2 = "https://mimiqfast.qperfect.io/api"


def getLogger():
    logger = logging.getLogger("mimiqlink")
    logger.setLevel(logging.INFO)
    return logger


class ConnectionError(Exception):
    "Exception raised for errors in the connection to the remote server."

    pass


class TimeoutHTTPAdapter(HTTPAdapter):
    def __init__(self, *args, **kwargs):
        if "timeout" in kwargs:
            self.timeout = kwargs["timeout"]
            del kwargs["timeout"]
        super().__init__(*args, **kwargs)

    def send(self, request, **kwargs):
        timeout = kwargs.get("timeout")
        if timeout is None and hasattr(self, "timeout"):
            kwargs["timeout"] = self.timeout
        # HACK: fix here. used to put timeout=0 (and hence timeout=None) in upload (otherwise we have a timeout)
        if timeout == 0:
            kwargs["timeout"] = None
        return super().send(request, **kwargs)


class MimiqConnection:
    """Connection to the MIMIQ remote services.

    It handles the authentication and the requests.
    """

    def __init__(self, url=None):
        if url is None:
            self.url = QPERFECT_CLOUD
        else:
            self.url = url

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

        # session for doing requests
        self.session = requests.Session()
        self.session.mount("http://", TimeoutHTTPAdapter(timeout=(1, None)))
        self.session.mount("https://", TimeoutHTTPAdapter(timeout=(1, None)))

    def _weblogin(self, data):
        "Authenticate to the remote server with the given credentials. But return the response."
        endpoint = "/sign-in"

        # ask for access tokens
        response = self.session.post(
            self.url + endpoint, json=data, headers={"Connection": "close"}
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
        "Authenticate to the remote server with the given credentials (email and password)."
        self._weblogin({"email": email, "password": password})
        return self

    def connectToken(self, token):
        "Authenticate to the remote server with the given refresh token"

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
        "Authenticate to the remote services by taking credentials from a locally shown login page"

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

    def connect(self, *args):
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
        import time

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
        "Refresh the access token using the refresh token."
        endpoint = "/access-token"

        # prepare the request
        with self.refresher_lock:
            data = {"refreshToken": self.refresh_token}

        # ask for a new access token
        response = self.session.post(
            self.url + endpoint, json=data, headers={"Connection": "close"}
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

    def request(self, emulatortype, name, label, timeout, uploads):
        "Request an execution to the remote server"
        self.checkAuth()

        endpoint = "/request"

        data = [
            ("name", (None, name)),
            ("label", (None, label)),
            ("emulatorType", (None, emulatortype)),
            ("timeout", (None, timeout)),
        ]

        for file in uploads:
            if isinstance(file, io.IOBase) and not file.closed:
                data.append(("uploads", (os.path.basename(file.name), file)))
            else:
                data.append(("uploads", (os.path.basename(file), open(file, "rb"))))

        response = self.session.post(self.url + endpoint, files=data, timeout=0)

        if response.status_code != 200:
            raise ConnectionError(
                f"File upload failed with status code {response.status_code}"
            )

        return response.json()["executionRequestId"]

    def stopexecution(self, request):
        "Stop the execution of a given request."
        self.checkAuth()

        endpoint = f"/stop-execution/{request}"

        response = self.session.post(self.url + endpoint)

        if response.status_code != 200:
            raise ConnectionError(
                f"Failed to stop the execution {request}. Server responded with {response.status_code}."
            )

        return None

    def deleteFiles(self, request):
        "Delete the files for a given request."
        self.checkAuth()

        endpoint = f"/delete-files/{request}"

        response = self.session.post(self.url + endpoint)

        if response.status_code != 200:
            raise ConnectionError(
                f"Failed to delete the files for {request}. Server responded with {response.status_code}."
            )

        return None

    def requestInfo(self, request):
        "Retrieve the execution details for a given request."
        self.checkAuth()

        endpoint = f"/request/{request}"

        response = self.session.get(self.url + endpoint)

        if response.status_code != 200:
            raise ConnectionError(
                f"Failed to retrieve execution details for {request}. Server responded with {response.status_code}"
            )

        return response.json()

    def requests(self, **kwargs):
        "Retrieve the list of requests from the server."
        self.checkAuth()

        query = ""

        for key, value in kwargs.items():
            if query == "":
                query += f"?{key}={value}"
            else:
                query += f"&{key}={value}"

        endpoint = "/request"
        response = self.session.get(self.url + endpoint + query)
        if response.status_code != 200:
            raise ConnectionError(
                f"Failed to retrieve the list of requests. Server responded with {response.status_code}"
            )

        return response.json()["executions"]["docs"]

    def printRequests(self, **kwargs):
        "Print the list of requests from the server."
        reqs = self.requests(**kwargs)

        numnew = sum("status" in req and req["status"] == "NEW" for req in reqs)
        numrunning = sum("status" in req and req["status"] == "RUNNING" for req in reqs)

        print(f"{len(reqs)} jobs of which {numnew} NEW and {numrunning} RUNNING:")

        # all but the last one
        for req in reqs[:-1]:
            print(f"├── Request {req['_id']}")
            print(f"│   ├── Name: {req['name']}")
            print(f"│   ├── Label: {req['label']}")
            print(f"│   ├── Status: {req['status']}")
            print(f"│   ├── User Email: {req['user']['email']}")
            print(f"│   ├── Created Date: {req['creationDate']}")
            print(f"│   ├── Running Date: {req.get('runningDate', 'None')}")
            print(f"│   └── Done Date: {req.get('doneDate', 'None')}")

        # the last one
        req = reqs[-1]
        print(f"└── Request {req['_id']}")
        print(f"    ├── Name: {req['name']}")
        print(f"    ├── Label: {req['label']}")
        print(f"    ├── Status: {req['status']}")
        print(f"    ├── User Email: {req['user']['email']}")
        print(f"    ├── Created Date: {req['creationDate']}")
        print(f"    ├── Running Date: {req.get('runningDate', 'None')}")
        print(f"    └── Done Date: {req.get('doneDate', 'None')}")

    def isJobDone(self, request):
        "Check if the job is done."
        infos = self.requestInfo(request)
        status = infos["status"]
        return status == "DONE" or status == "ERROR"

    def isJobFailed(self, request):
        "Check if the job failed."
        infos = self.requestInfo(request)
        status = infos["status"]
        return status == "ERROR"

    def isJobStarted(self, request):
        "Check if the job is started."
        infos = self.requestInfo(request)
        status = infos["status"]
        return status != "NEW"

    def isJobCanceled(self, request):
        "Check if the job is canceled."
        infos = self.requestInfo(request)
        status = infos["status"]
        return status == "CANCELED"

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

    def downloadFile(self, request, index, filetype, destdir):
        self.checkAuth()

        endpoint = f"/files/{request}/{index}?source={filetype}"

        response = self.session.get(self.url + endpoint)

        if response.status_code >= 300:
            raise ConnectionError(
                f"Failed to retrieve {filetype} files for {request}. Server responded with {response.status_code}"
            )

        filename = re.findall(
            'filename="(.+)"', response.headers.get("Content-Disposition")
        )[0]

        # Should never happen, but just in case.
        # If it does, we can't do anything about it here. We need to patch the server
        if not filename:
            raise ConnectionError(
                "Something went wrong. Server is missing the filename"
            )

        # at this point we should have a valid filename and a valid directory
        # so we write everything to the file
        with open(os.path.join(destdir, filename), "wb") as f:
            f.write(response.content)

        return filename

    def downloadFiles(self, request, source, destdir=None):
        self.checkAuth()

        if destdir is None:
            destdir = os.path.join("./", request)

        infos = self.requestInfo(request)

        if source == "uploads":
            sourcename = "numberOfUploadedFiles"
        else:
            sourcename = "numberOfResultedFiles"

        nf = infos.get(sourcename, 0)

        names = []
        for idx in range(nf):
            name = self.downloadFile(request, idx, source, destdir)
            names.append(name)

        return names

    def downloadJobFiles(self, request, **kwargs):
        return self.downloadFiles(request, "uploads", **kwargs)

    def downloadResults(self, request, **kwargs):
        return self.downloadFiles(request, "results", **kwargs)

    def savetoken(self, filepath="qperfect.json"):
        "Save the current token to a file."
        if self.refresh_token is None:
            self.connect()
        with open(filepath, "w") as f:
            json.dump({"token": self.refresh_token, "url": self.url}, f)

    @staticmethod
    def loadtoken(filepath="qperfect.json"):
        "Start a new connection and load the credentials from a file."

        # This will allow to load the token from a file.
        # The syntax will be:
        #     MimiqConnection.loadtoken("qperfect.json")

        try:
            with open(filepath, "r") as f:
                data = json.load(f)
                url = data.get("url", "")
                token = data["token"]
        except Exception as e:
            getLogger().error(f"Error reading token file: {e}")
            raise ConnectionError("Failed to read token file.")

        conn = MimiqConnection(url)
        try:
            conn.connectToken(token)
        except ConnectionError as e:
            getLogger().error(f"Authentication failed: {e}")
            raise ConnectionError("Authentication failed. Unable to connect using the stored token.")
        
        return conn

    def close(self):
        "Close the connection."
        getLogger().info("Closing connection to {self.url}")
        # ask the refresher to stop
        with self.refresher_lock:
            self.refresher_stop = True

        getLogger().info("Shutting down token refresher")
        self.refresher_task.join()
        getLogger().info(f"Task (done) @{hex(id(self.refresher_task))}")

        # clean the tokens
        self.access_token = None
        self.refresh_token = None

    def isOpen(self):
        "Check if the connection is open."
        a = self.refresher_task is not None
        b = self.refresher_task.is_alive()
        c = self.access_token is not None
        return a and b and c

    def checkUserLimits(self, limits=None):
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
        "Fetch user limits from the server."
        self.checkAuth()

        endpoint = "/users/limits"

        response = self.session.get(self.url + endpoint)

        if response.status_code != 200:
            raise ConnectionError(
                f"Failed to retrieve user limits. Server responded with {response.status_code}"
            )

        self.user_limits = response.json()
        self.checkUserLimits()

    def __str__(self):
        limits = self.user_limits
        result = f"Connection:\n├── url: {self.url}\n"

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

        result += "└── status: " + ("open" if self.isOpen() else "closed") + "\n"

        return result

    def __repr__(self) -> str:
        return self.__str__()
