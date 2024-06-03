#
# Copyright © 2022-2023 University of Strasbourg. All Rights Reserved.
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
from time import sleep
import threading
import webbrowser

# import the connection handler
from mimiqlink.handler import AuthenticationHandler

QPERFECT_CLOUD = "https://mimiq.qperfect.io/api"

QPERFECT_CLOUD2 = "https://mimiqfast.qperfect.io/api"


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

        # session for doing requests
        self.session = requests.Session()
        self.session.mount("http://", TimeoutHTTPAdapter(timeout=(1, None)))
        self.session.mount("https://", TimeoutHTTPAdapter(timeout=(1, None)))

    def connectUser(self, email, password):
        "Authenticate to the remote server with the given credentials (email and password)."
        endpoint = "/sign-in"

        # prepare the request
        data = {"email": email, "password": password}

        # ask for access tokens
        response = self.session.post(
            self.url + endpoint, json=data, headers={"Connection": "close"}
        )

        if response.status_code == 200:
            tokens = response.json()

            # set the access tokens
            with self.refresher_lock:
                self.access_token = tokens["token"]
                self.refresh_token = tokens["refreshToken"]

            # update the session headers
            self.updateSessionHeaders()

            # refresher thread, running in the background
            self.startRefresher()

            logging.info("Authentication successful.")

        else:
            reason = response.json()["message"]
            logging.error(
                f"Authentication failed with status code {response.status_code} and reason: {reason}"
            )

    def _weblogin(self, data):
        "Authenticate to the remote server with the given credentials. But return the response."
        endpoint = "/sign-in"

        # ask for access tokens
        response = self.session.post(
            self.url + endpoint, json=data, headers={"Connection": "close"}
        )

        if response.status_code == 200:
            tokens = response.json()

            # set the access tokens
            with self.refresher_lock:
                self.access_token = tokens["token"]
                self.refresh_token = tokens["refreshToken"]

            self.updateSessionHeaders()

            # refresher thread, running in the background
            self.startRefresher()

            logging.info("Authentication successful.")

        else:
            reason = response.json()["message"]
            logging.error(
                f"Authentication failed with status code {response.status_code} and reason: {reason}"
            )

        return response

    def connectToken(self, token):
        "Authenticate to the remote server with the given refresh token"

        # set the refresh token
        with self.refresher_lock:
            self.refresh_token = token

        # refresh
        status = self.refresh()

        if status:
            logging.info("Authentication successfull.")
            self.updateSessionHeaders()
            self.startRefresher()
        else:
            logging.error("Authentication failed.")

    def startRefresher(self):
        """Start the refresher thread."""
        # ensure that the refresher is not stopped immediately
        with self.refresher_lock:
            self.refresher_stop = False

        # create and start the refresher
        self.refresher_task = threading.Thread(target=self.refresher)
        self.refresher_task.start()

    def refresher(self):
        """Refresher function
        Will refresh the access token with the refresh token at every
        configured interval.
        """
        while True:
            # check the stop flag every second
            for i in range(self.refresher_interval):
                sleep(1)
                with self.refresher_lock:
                    if self.refresher_stop:
                        break

            with self.refresher_lock:
                if self.refresher_stop:
                    break

            status = self.refresh()

            if not status:
                logging.error("Access token refresh failed. Connection is closed")

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
            return False

        tokens = response.json()

        # write the new tokens
        with self.refresher_lock:
            self.access_token = tokens["token"]
            self.refresh_token = tokens["refreshToken"]

        self.updateSessionHeaders()

        return True

    def request(self, emulatortype, name, label, timeout, uploads):
        "Request an execution to the remote server"

        if not self.checkAuth():
            return None

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
            logging.error(f"File upload failed with status code {response.status_code}")
            return None

        return response.json()["executionRequestId"]

    def stopexecution(self, request):
        "Stop the execution of a given request."
        if not self.checkAuth():
            return None

        endpoint = f"/stop-execution/{request}"

        response = self.session.post(self.url + endpoint)

        if response.status_code != 200:
            logging.error(
                f"Failed to stop the execution {request}. Server responded with {response.status_code}."
            )
            return None

        return None

    def deletefiles(self, request):
        "Delete the files for a given request."
        if not self.checkAuth():
            return None

        endpoint = f"/delete-files/{request}"

        response = self.session.post(self.url + endpoint)

        if response.status_code != 200:
            logging.error(
                f"Failed to delete the files for {request}. Server responded with {response.status_code}."
            )
            return None

        return None

    def requestInfo(self, request):
        "Retrieve the execution details for a given request."
        if not self.checkAuth():
            return None

        endpoint = f"/request/{request}"

        response = self.session.get(self.url + endpoint)

        if response.status_code != 200:
            logging.error(
                f"Failed to retrieve execution details for {request}. Server responded with {response.status_code}"
            )
            return {}

        return response.json()

    def requests(self, **kwargs):
        "Retrieve the list of requests from the server."
        if not self.checkAuth():
            return None

        query = ""

        for key, value in kwargs.items():
            if query == "":
                query += f"?{key}={value}"
            else:
                query += f"&{key}={value}"

        endpoint = "/request"
        response = self.session.get(self.url + endpoint + query)
        if response.status_code != 200:
            logging.error(
                f"Failed to retrieve the list of requests. Server responded with {response.status_code}"
            )
            return None
        return response.json()["executions"]["docs"]

    def printRequests(self, **kwargs):
        "Print the list of requests from the server."
        reqs = self.requests(**kwargs)

        numnew = sum("status" in req and req["status"] == "NEW" for req in reqs)
        numrunning = sum("status" in req and req["status"] == "RUNNING" for req in reqs)

        print(f"{len(reqs)} jobs of which {numnew} NEW and {numrunning} RUNNING:")
        #
        # all but the last one
        for req in reqs[:-1]:
            print(f"├── Request {req["_id"]}")
            print(f"│   ├── Name: {req["name"]}")
            print(f"│   ├── Label: {req["label"]}")
            print(f"│   ├── Status: {req["status"]}")
            print(f"│   ├── User Email: {req["user"]["email"]}")
            print(f"│   ├── Created Date: {req["creationDate"]}")
            print(f"│   ├── Running Date: {req.get("runningDate", "None")}")
            print(f"│   └── Done Date: {req.get("doneDate", "None")}")

        # the last one
        req = reqs[-1]
        print(f"└── Request {req["_id"]}")
        print(f"    ├── Name: {req["name"]}")
        print(f"    ├── Label: {req["label"]}")
        print(f"    ├── Status: {req["status"]}")
        print(f"    ├── User Email: {req["user"]["email"]}")
        print(f"    ├── Created Date: {req["creationDate"]}")
        print(f"    ├── Running Date: {req.get("runningDate", "None")}")
        print(f"    └── Done Date: {req.get("doneDate", "None")}")

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

    def updateSessionHeaders(self):
        # fetch the access token
        with self.refresher_lock:
            token = self.access_token

        # build the headers
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def checkAuth(self):
        with self.refresher_lock:
            if self.access_token is None:
                logging.error("Not yet authenticated.")
                return False

        return True

    def downloadFile(self, request, index, filetype, destdir):
        if not self.checkAuth():
            return None

        endpoint = f"/files/{request}/{index}?source={filetype}"

        response = self.session.get(self.url + endpoint)

        if response.status_code >= 300:
            logging.error(
                f"Failed to retrieve {filetype} files for {request}. Server responded with {response.status_code}"
            )
            return None

        filename = re.findall(
            'filename="(.+)"', response.headers.get("Content-Disposition")
        )[0]
        # print(f"Saving {filename} in {destdir}")

        # Should never happen, but just in case.
        # If it does, we can't do anything about it here. We need to patch the server
        if not filename:
            logging.error(f"Something went wrong. Server is missing the filename")
            return None

        # at this point we should have a valid filename and a valid directory
        # so we write everything to the file
        with open(os.path.join(destdir, filename), "wb") as f:
            f.write(response.content)

        return filename

    def downloadFiles(self, request, source, destdir=None):
        if not self.checkAuth():
            return None

        if destdir is None:
            destdir = os.path.join("./", request)

        # # if the directory alreayd exists send a warning, otherwise create it
        # try:
        #     os.mkdir(destdir)
        # except FileExistsError:
        #     logging.warning(f"Directory {destdir} already exists.")

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

    def connect(self):
        "Authenticate to the remote services by taking credentials from a locally shown login page"

        fixed_port = 1444

        h = partial(AuthenticationHandler, lambda data: self._weblogin(data))

        try:
            # Attempt to create the server with the fixed port
            httpd = HTTPServer(("localhost", fixed_port), h)
            port = fixed_port
        except OSError:
            # If the fixed port is in use, use a random available port
            httpd = HTTPServer(("localhost", 0), h)
            port = httpd.server_port

        print(
            f"Starting authentication server on port {port} (http://localhost:{port})"
        )
        webbrowser.open(f"http://localhost:{port}", new=2)

        with httpd:
            while self.access_token is None:
                httpd.handle_request()

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

        with open(filepath, "r") as f:
            data = json.load(f)
            url = data.get("url", "")
            token = data["token"]

        conn = MimiqConnection(url)
        conn.connectToken(token)
        return conn

    def close(self):
        "Close the connection."
        # ask the refresher to stop
        with self.refresher_lock:
            self.refresher_stop = True

        # join the thread
        self.refresher_task.join()

        # clean the tokens
        self.access_token = None
        self.refresh_token = None

    def isOpen(self):
        "Check if the connection is open."
        a = self.refresher_task is not None
        b = self.refresher_task.is_alive()
        c = self.access_token is not None
        return a and b and c
