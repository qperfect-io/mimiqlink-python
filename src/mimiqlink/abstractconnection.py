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


class MimiqConnectionError(ConnectionError):
    """Raised when a remote service refuses a request or cannot be reached.

    It derives from the builtin :class:`ConnectionError`, so code that catches
    that keeps working.
    """

    pass


# The library used to raise a class of its own named `ConnectionError` from
# this module and the builtin from every other one. Both are this class now,
# and the old name stays importable.
ConnectionError = MimiqConnectionError


class AbstractConnection(ABC):
    """Base class for connections to MIMIQ and other remote services.

    It defines the interface shared by :class:`MimiqConnection`,
    :class:`QhiveConnection` and :class:`PlanqkConnection`: authentication
    (``connect``, ``close``, ``isOpen``, ``checkAuth``), job submission
    (``request``), job inspection (``requestInfo``, ``requests``,
    ``isJobDone`` and the other ``isJob*`` checks), cancellation
    (``stopExecution``) and file transfer (``downloadResults``,
    ``downloadJobFiles``, ``deleteFiles``). The methods implemented here talk
    to the MIMIQ cloud REST API under :meth:`get_api_url`; subclasses for
    other services override them.

    Args:
        url (str, optional): The base URL of the service.
    """

    def __init__(self, url=None):
        self.url = url

        # session for doing requests
        self.session = requests.Session()
        self.session.mount("http://", TimeoutHTTPAdapter(timeout=(1, None)))
        self.session.mount("https://", TimeoutHTTPAdapter(timeout=(1, None)))

    @abstractmethod
    def connect(self, *args, **kwargs):
        """Authenticate to the remote service and return the connection."""
        pass

    @abstractmethod
    def close(self):
        """Log out and forget the stored credentials."""
        pass

    @abstractmethod
    def isOpen(self):
        """Return True if the connection is authenticated."""
        pass

    @abstractmethod
    def checkAuth(self):
        """Check that the connection is authenticated.

        Subclasses raise :class:`MimiqConnectionError` or return False when
        it is not.
        """
        pass

    @abstractmethod
    def get_api_url(self, *paths):
        """Return the URL of an API endpoint.

        Joins the base URL, the service's API prefix and ``paths`` with
        ``/``.
        """
        pass

    def request(self, emulatortype, name, label, timeout, uploads):
        """Upload files and create an execution on the remote service.

        Args:
            emulatortype (str): The type of executor, for example ``"CIRC"``
                for circuit simulation.
            name (str): The name of the execution (``mimiqcircuits`` passes
                the simulation algorithm).
            label (str): A label to identify the execution.
            timeout (int): The time limit of the execution, in minutes.
            uploads (list): The files to upload, as paths or open binary file
                objects. Paths are opened and not closed.

        Returns:
            str: The identifier of the new execution.

        Raises:
            MimiqConnectionError: If the connection is not authenticated or
                the service refuses the request.
        """
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
            raise MimiqConnectionError(
                f"File upload failed with status code {response.status_code}"
            )

        return response.json()["executionRequestId"]

    def requestInfo(self, request):
        """Fetch the details of an execution.

        Args:
            request (str): The execution identifier.

        Returns:
            RequestInfo: The execution's status, dates, file counts and the
            rest of the data the service returns.

        Raises:
            MimiqConnectionError: If the connection is not authenticated or
                the service refuses the request.
        """
        self.checkAuth()

        endpoint = f"request/{request}"

        response = self.session.get(self.get_api_url(endpoint))

        if response.status_code != 200:
            raise MimiqConnectionError(
                f"Failed to retrieve execution details for {request}. Server responded with {response.status_code}"
            )

        return RequestInfo(response.json())

    def requests(self, **kwargs):
        """Fetch the list of the user's executions.

        Args:
            **kwargs: Query parameters added to the request URL as
                ``?key=value&...``, used to filter or page the list.

        Returns:
            RequestInfoList: The executions.

        Raises:
            MimiqConnectionError: If the connection is not authenticated or
                the service refuses the request.
        """
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
            raise MimiqConnectionError(
                f"Failed to retrieve the list of requests. Server responded with {response.status_code}"
            )

        return RequestInfoList(response.json()["executions"]["docs"])

    def isJobDone(self, request):
        """Return True if the execution is no longer ``NEW`` or ``RUNNING``.

        That is, it finished successfully, failed or was canceled. Each call
        queries the service.

        Args:
            request (str): The execution identifier.
        """
        infos = self.requestInfo(request)
        status = infos.status
        return status != "NEW" and status != "RUNNING"

    def isJobFailed(self, request):
        """Return True if the execution's status is ``ERROR``.

        Args:
            request (str): The execution identifier.
        """
        infos = self.requestInfo(request)
        status = infos.status
        return status == "ERROR"

    def isJobStarted(self, request):
        """Return True if the execution's status is no longer ``NEW``.

        Args:
            request (str): The execution identifier.
        """
        infos = self.requestInfo(request)
        status = infos.status
        return status != "NEW"

    def isJobCanceled(self, request):
        """Return True if the execution's status is ``CANCELED``.

        Args:
            request (str): The execution identifier.
        """
        infos = self.requestInfo(request)
        status = infos.status
        return status == "CANCELED"

    def stopExecution(self, request):
        """Ask the service to stop an execution.

        An execution that has not started yet is canceled at once; a running
        one is sent a stop signal.

        Args:
            request (str): The execution identifier.

        Raises:
            MimiqConnectionError: If the connection is not authenticated or
                the service refuses the request.
        """
        self.checkAuth()

        endpoint = f"stop-execution/{request}"
        response = self.session.post(self.get_api_url(endpoint))

        if response.status_code != 200:
            raise MimiqConnectionError(
                f"Failed to stop the execution {request}. Server responded with {response.status_code}."
            )

        return None

    def deleteFiles(self, request):
        """Delete an execution's uploaded and result files from the service.

        Args:
            request (str): The execution identifier.

        Raises:
            MimiqConnectionError: If the connection is not authenticated or
                the service refuses the request.
        """
        self.checkAuth()

        endpoint = f"delete-files/{request}"
        response = self.session.post(self.get_api_url(endpoint))

        if response.status_code != 200:
            raise MimiqConnectionError(
                f"Failed to delete the files for {request}. Server responded with {response.status_code}."
            )

        return None

    def downloadFile(self, request, index, filetype, destdir):
        """Download one uploaded or result file of an execution.

        Args:
            request (str): The execution identifier.
            index (int): The position of the file, starting from 0.
            filetype (str): ``"uploads"`` or ``"results"``.
            destdir (str): The directory to write to, created if missing.

        Returns:
            str: The name of the written file, as given by the service.

        Raises:
            MimiqConnectionError: If the connection is not authenticated, the
                download fails, or the service gives no file name.
        """
        self.checkAuth()

        endpoint = f"files/{request}/{index}"
        url = self.get_api_url(endpoint) + f"?source={filetype}"

        response = self.session.get(url)

        if response.status_code >= 300:
            raise MimiqConnectionError(
                f"Failed to retrieve {filetype} files for {request}. Server responded with {response.status_code}"
            )

        filename = re.findall(
            'filename="(.+)"', response.headers.get("Content-Disposition", "")
        )

        # Should never happen, but just in case.
        # If it does, we can't do anything about it here. We need to patch the server
        if not filename:
            raise MimiqConnectionError(
                "Something went wrong. Server is missing the filename"
            )
        filename = filename[0]

        # Create directory if it doesn't exist
        if not os.path.exists(destdir):
            os.makedirs(destdir)

        # at this point we should have a valid filename and a valid directory
        # so we write everything to the file
        with open(os.path.join(destdir, filename), "wb") as f:
            f.write(response.content)

        return filename

    def downloadFiles(self, request, source, destdir=None):
        """Download all uploaded or result files of an execution.

        Args:
            request (str): The execution identifier.
            source (str): ``"uploads"`` for the input files, anything else
                for the result files.
            destdir (str, optional): The directory to write to, created if
                missing. Defaults to None (a directory named after
                ``request`` in the current directory).

        Returns:
            list[str]: The names of the written files.

        Raises:
            MimiqConnectionError: If the connection is not authenticated or a
                download fails.
        """
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
        """Download the uploaded input files for a given request.

        Args:
            request: The execution identifier.
            **kwargs: Keyword arguments passed to :meth:`downloadFiles`, such
                as ``destdir``.

        Returns:
            list[str]: The names of the downloaded files.
        """
        return self.downloadFiles(request, "uploads", **kwargs)

    def downloadResults(self, request, **kwargs):
        """Download the result files for a given request.

        Args:
            request: The execution identifier.
            **kwargs: Keyword arguments passed to :meth:`downloadFiles`, such
                as ``destdir``.

        Returns:
            list[str]: The names of the downloaded files.
        """
        return self.downloadFiles(request, "results", **kwargs)
