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

from abc import ABC, abstractmethod
import os
import os.path
import io
import re
import requests
from requests.adapters import HTTPAdapter

# Import the logging utils
from mimiqlink.utils import getLogger

from mimiqlink.infos import RequestInfo, RequestInfoList


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


class ConnectionError(Exception):
    """Exception raised for errors in the connection to the remote server."""

    pass


class AbstractConnection(ABC):
    """Base class for connection to MIMIQ and other remote services.

    This abstract class defines the interface for all connection types.
    """

    def __init__(self, url=None):
        self.url = url

        # session for doing requests
        self.session = requests.Session()
        self.session.mount("http://", TimeoutHTTPAdapter(timeout=(1, None)))
        self.session.mount("https://", TimeoutHTTPAdapter(timeout=(1, None)))

    @abstractmethod
    def connect(self, *args, **kwargs):
        """Establish a connection to the remote service."""
        pass

    @abstractmethod
    def close(self):
        """Close the connection to the remote service."""
        pass

    @abstractmethod
    def isOpen(self):
        """Check if the connection is open."""
        pass

    @abstractmethod
    def checkAuth(self):
        """Check if the authentication is valid."""
        pass

    @abstractmethod
    def get_api_url(self, *paths):
        """Get the API URL for the given paths.

        This method should join the base URL with the API prefix and the given paths.
        """
        pass

    def request(self, emulatortype, name, label, timeout, uploads):
        """Request an execution to the remote server."""
        self.checkAuth()

        endpoint = "request"

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

        response = self.session.post(self.get_api_url(endpoint), files=data, timeout=0)

        if response.status_code != 200:
            raise ConnectionError(
                f"File upload failed with status code {response.status_code}"
            )

        return response.json()["executionRequestId"]

    def requestInfo(self, request):
        """Retrieve the execution details for a given request."""
        self.checkAuth()

        endpoint = f"request/{request}"

        response = self.session.get(self.get_api_url(endpoint))

        if response.status_code != 200:
            raise ConnectionError(
                f"Failed to retrieve execution details for {request}. Server responded with {response.status_code}"
            )

        return RequestInfo(response.json())

    def requests(self, **kwargs):
        """Retrieve the list of requests from the server."""
        self.checkAuth()

        query = ""
        for key, value in kwargs.items():
            if query == "":
                query += f"?{key}={value}"
            else:
                query += f"&{key}={value}"

        endpoint = "request"
        response = self.session.get(self.get_api_url(endpoint) + query)
        if response.status_code != 200:
            raise ConnectionError(
                f"Failed to retrieve the list of requests. Server responded with {response.status_code}"
            )

        return RequestInfoList(response.json()["executions"]["docs"])

    def isJobDone(self, request):
        """Check if the job is done."""
        infos = self.requestInfo(request)
        status = infos.status()
        return status == "DONE" or status == "ERROR"

    def isJobFailed(self, request):
        """Check if the job failed."""
        infos = self.requestInfo(request)
        status = infos.status()
        return status == "ERROR"

    def isJobStarted(self, request):
        """Check if the job is started."""
        infos = self.requestInfo(request)
        status = infos.status()
        return status != "NEW"

    def isJobCanceled(self, request):
        """Check if the job is canceled."""
        infos = self.requestInfo(request)
        status = infos.status()
        return status == "CANCELED"

    def stopexecution(self, request):
        """Stop the execution of a given request."""
        self.checkAuth()

        endpoint = f"stop-execution/{request}"
        response = self.session.post(self.get_api_url(endpoint))

        if response.status_code != 200:
            raise ConnectionError(
                f"Failed to stop the execution {request}. Server responded with {response.status_code}."
            )

        return None

    def deleteFiles(self, request):
        """Delete the files for a given request."""
        self.checkAuth()

        endpoint = f"delete-files/{request}"
        response = self.session.post(self.get_api_url(endpoint))

        if response.status_code != 200:
            raise ConnectionError(
                f"Failed to delete the files for {request}. Server responded with {response.status_code}."
            )

        return None

    def downloadFile(self, request, index, filetype, destdir):
        """Download a specific file from the server."""
        self.checkAuth()

        endpoint = f"files/{request}/{index}"
        url = self.get_api_url(endpoint) + f"?source={filetype}"

        response = self.session.get(url)

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

        # Create directory if it doesn't exist
        if not os.path.exists(destdir):
            os.makedirs(destdir)

        # at this point we should have a valid filename and a valid directory
        # so we write everything to the file
        with open(os.path.join(destdir, filename), "wb") as f:
            f.write(response.content)

        return filename

    def downloadFiles(self, request, source, destdir=None):
        """Download files for a given request."""
        self.checkAuth()

        if destdir is None:
            destdir = os.path.join("./", request)

        # Create the directory if it doesn't exist
        if not os.path.exists(destdir):
            os.makedirs(destdir)

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
        """Download the input files for a given request."""
        return self.downloadFiles(request, "uploads", **kwargs)

    def downloadResults(self, request, **kwargs):
        """Download the result files for a given request."""
        return self.downloadFiles(request, "results", **kwargs)
