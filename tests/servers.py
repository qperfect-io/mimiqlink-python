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
"""Stand-ins for the servers this library talks to.

Each class below answers the subset of an API that the client actually calls,
and keeps the state that makes the answers interesting: which token is current,
which jobs exist, which files they produced. Tests drive the real client
against them, so a change in how the client talks to a server shows up here as
a failing test instead of in someone's session.

Both servers are installed into a ``responses`` mock, which intercepts
``requests`` at the transport: no sockets, no ports, no threads to shut down.

The one rule worth remembering when adding a route: register the more specific
pattern first, since the first match wins.
"""

import json
import re
from urllib.parse import parse_qs, urlparse

import responses


def multipartnames(request):
    """The ``(field, filename)`` pairs of a multipart body, in the order sent.

    Only the names are recovered, which is all a test needs to state what the
    client uploaded and under which field.
    """
    body = request.body
    body = body if isinstance(body, bytes) else str(body).encode()

    pairs = re.findall(rb'name="([^"]+)"(?:; filename="([^"]+)")?', body)

    return [(name.decode(), filename.decode()) for name, filename in pairs]


def _query(request, key, default=None):
    """Read a single query parameter out of a request URL."""
    return parse_qs(urlparse(request.url).query).get(key, [default])[0]


def _pathparts(request):
    return urlparse(request.url).path.strip("/").split("/")


def _json(status, payload):
    return (status, {}, json.dumps(payload))


class MimiqServer:
    """The MIMIQ cloud API, as much of it as the client uses.

    Tokens rotate on every refresh, exactly like the real server: a refresh
    token works once and the client is expected to keep the new one.
    """

    def __init__(self, url="https://mimiq.test"):
        self.url = url
        self.email = "john.doe@example.com"
        self.password = "johnspassword"

        self.issued = 0
        self.accesstoken = None
        self.refreshtoken = None

        self.jobs = {}
        self.files = {}

        self.limits = {
            "enabledExecutionTime": False,
            "enabledMaxExecutions": False,
            "enabledMaxTimeout": False,
        }

        # Set by the route that creates a job, so a test can state what the
        # client put in the multipart body.
        self.lastupload = []

    # -- state ---------------------------------------------------------------

    def issuetokens(self):
        """Issue a fresh pair, invalidating the previous one."""
        self.issued += 1
        self.accesstoken = f"access-{self.issued}"
        self.refreshtoken = f"refresh-{self.issued}"

        return {"token": self.accesstoken, "refreshToken": self.refreshtoken}

    def addjob(self, status="NEW", uploads=(), results=(), **fields):
        """Add a job to the server and return its identifier.

        ``uploads`` and ``results`` are ``(filename, content)`` pairs, and the
        counts the client reads back are derived from them.
        """
        jobid = fields.pop("jobid", f"job-{len(self.jobs) + 1}")

        self.jobs[jobid] = {
            "_id": jobid,
            "name": "circuit",
            "label": "a label",
            "status": status,
            "user": {"email": self.email},
            "creationDate": "2026-01-01T00:00:00.000Z",
            "numberOfUploadedFiles": len(uploads),
            "numberOfResultedFiles": len(results),
            **fields,
        }

        self.files[(jobid, "uploads")] = list(uploads)
        self.files[(jobid, "results")] = list(results)

        return jobid

    # -- routes --------------------------------------------------------------

    def install(self, mock):
        """Register every route on a ``responses`` mock and return the server."""
        api = re.escape(self.url) + "/api"

        mock.add_callback(responses.POST, f"{self.url}/api/sign-in", self._signin)
        mock.add_callback(
            responses.POST, f"{self.url}/api/access-token", self._accesstoken
        )
        mock.add_callback(responses.GET, f"{self.url}/api/users/limits", self._userlimits)
        mock.add_callback(
            responses.POST, re.compile(api + r"/stop-execution/[^/?]+$"), self._stop
        )
        mock.add_callback(
            responses.POST, re.compile(api + r"/delete-files/[^/?]+$"), self._deletefiles
        )
        mock.add_callback(
            responses.GET, re.compile(api + r"/files/[^/]+/\d+"), self._downloadfile
        )
        mock.add_callback(
            responses.GET, re.compile(api + r"/request/[^/?]+$"), self._job
        )
        mock.add_callback(responses.POST, f"{self.url}/api/request", self._newjob)
        mock.add_callback(responses.GET, f"{self.url}/api/request", self._joblist)

        return self

    def _authorized(self, request):
        return request.headers.get("Authorization") == f"Bearer {self.accesstoken}"

    def _signin(self, request):
        credentials = json.loads(request.body)

        if (
            credentials.get("email") != self.email
            or credentials.get("password") != self.password
        ):
            return _json(401, {"message": "Wrong email or password"})

        return _json(200, self.issuetokens())

    def _accesstoken(self, request):
        if json.loads(request.body).get("refreshToken") != self.refreshtoken:
            return _json(401, {"message": "The refresh token is no longer valid"})

        return _json(200, self.issuetokens())

    def _userlimits(self, request):
        if not self._authorized(request):
            return _json(401, {"message": "Unauthorized"})

        return _json(200, self.limits)

    def _newjob(self, request):
        if not self._authorized(request):
            return _json(401, {"message": "Unauthorized"})

        self.lastupload = multipartnames(request)
        uploads = [(name, b"") for _, name in self.lastupload if name]

        return _json(200, {"executionRequestId": self.addjob(uploads=uploads)})

    def _job(self, request):
        jobid = _pathparts(request)[-1]

        if jobid not in self.jobs:
            return _json(404, {"message": f"No request with id {jobid}"})

        return _json(200, self.jobs[jobid])

    def _joblist(self, request):
        status = _query(request, "status")
        docs = [
            job
            for job in self.jobs.values()
            if status is None or job["status"] == status
        ]

        return _json(200, {"executions": {"docs": docs}})

    def _stop(self, request):
        jobid = _pathparts(request)[-1]

        if jobid not in self.jobs:
            return _json(404, {"message": f"No request with id {jobid}"})

        self.jobs[jobid]["status"] = "CANCELED"

        return _json(200, {})

    def _deletefiles(self, request):
        jobid = _pathparts(request)[-1]

        if jobid not in self.jobs:
            return _json(404, {"message": f"No request with id {jobid}"})

        self.files[(jobid, "uploads")] = []
        self.files[(jobid, "results")] = []

        return _json(200, {})

    def _downloadfile(self, request):
        parts = _pathparts(request)
        jobid, index = parts[-2], int(parts[-1])
        source = _query(request, "source", "results")

        files = self.files.get((jobid, source), [])

        if index >= len(files):
            return _json(404, {"message": "No such file"})

        name, content = files[index]
        headers = {"Content-Disposition": f'attachment; filename="{name}"'}

        return (200, headers, content)


class QhiveServer:
    """The Quantum Hive API and the Keycloak realm in front of it.

    Set ``expireonce`` to answer the next authenticated call with a 401, which
    is how a test states that an access token went stale without waiting for one
    to actually expire.
    """

    def __init__(self, url="https://qhive.test/api", authurl="https://qhive.test/auth/"):
        self.url = url
        self.authurl = authurl
        self.realm = "qhive"

        self.email = "john.doe@example.com"
        self.password = "johnspassword"

        self.issued = 0
        self.accesstoken = None
        self.refreshtoken = None

        # When set, the next authenticated call is refused once.
        self.expireonce = False

        # When set, every circuit upload is refused.
        self.refuseuploads = False

        self.jobs = {}
        self.files = {}
        self.circuits = {}

        self.committed = []

    # -- state ---------------------------------------------------------------

    def issuetokens(self):
        self.issued += 1
        self.accesstoken = f"access-{self.issued}"
        self.refreshtoken = f"refresh-{self.issued}"

        return {
            "access_token": self.accesstoken,
            "refresh_token": self.refreshtoken,
            "expires_in": 300,
            "token_type": "Bearer",
        }

    def addjob(self, status="AUTHORIZED", results=(), **fields):
        jobid = fields.pop("jobid", f"job-{len(self.jobs) + 1}")

        self.jobs[jobid] = {
            "_id": jobid,
            "algorithm": "circuit",
            "label": "a label",
            "status": status,
            **fields,
        }

        self.files[(jobid, "results")] = list(results)
        self.circuits[jobid] = {}

        return jobid

    # -- routes --------------------------------------------------------------

    def install(self, mock):
        oidc = f"{self.authurl}realms/{self.realm}/protocol/openid-connect"
        api = re.escape(self.url)

        mock.add_callback(responses.POST, f"{oidc}/token", self._token)
        mock.add_callback(responses.GET, f"{oidc}/userinfo", self._userinfo)
        mock.add_callback(responses.POST, f"{oidc}/logout", self._logout)

        mock.add_callback(
            responses.PATCH, re.compile(api + r"/jobs/[^/]+/commit$"), self._commit
        )
        mock.add_callback(
            responses.PATCH, re.compile(api + r"/jobs/[^/]+/cancel$"), self._cancel
        )
        mock.add_callback(
            responses.POST,
            re.compile(api + r"/files/[^/]+/circuit/[^/]+$"),
            self._uploadcircuit,
        )
        mock.add_callback(
            responses.DELETE, re.compile(api + r"/files/[^/?]+$"), self._deletefiles
        )
        mock.add_callback(
            responses.GET, re.compile(api + r"/files/[^/]+/[^/?]+$"), self._filelist
        )
        mock.add_callback(responses.GET, re.compile(api + r"/jobs/[^/?]+$"), self._job)
        mock.add_callback(responses.POST, f"{self.url}/jobs", self._newjob)
        mock.add_callback(responses.GET, f"{self.url}/jobs", self._joblist)

        mock.add_callback(
            responses.GET,
            re.compile(re.escape(self.url) + r"/download/[^/?]+$"),
            self._download,
        )

        return self

    def _authorized(self, request):
        if request.headers.get("Authorization") != f"Bearer {self.accesstoken}":
            return False

        if self.expireonce:
            self.expireonce = False
            return False

        return True

    def _token(self, request):
        form = parse_qs(request.body or "")
        grant = form.get("grant_type", [""])[0]

        if grant == "password":
            if (
                form.get("username", [""])[0] != self.email
                or form.get("password", [""])[0] != self.password
            ):
                return _json(401, {"error_description": "Invalid user credentials"})

        elif grant == "refresh_token":
            if form.get("refresh_token", [""])[0] != self.refreshtoken:
                return _json(400, {"error_description": "Invalid refresh token"})

        elif grant == "authorization_code":
            if form.get("code", [""])[0] != "the-code":
                return _json(400, {"error_description": "Invalid authorization code"})

        else:
            return _json(400, {"error_description": f"Unsupported grant {grant}"})

        return _json(200, self.issuetokens())

    def _userinfo(self, request):
        if request.headers.get("Authorization") != f"Bearer {self.accesstoken}":
            return _json(401, {"error_description": "Invalid token"})

        return _json(200, {"sub": "1234", "email": self.email})

    def _logout(self, request):
        self.accesstoken = None
        self.refreshtoken = None

        return (204, {}, "")

    def _newjob(self, request):
        if not self._authorized(request):
            return _json(401, {"error_description": "Expired token"})

        return (200, {}, self.addjob(status="NEW"))

    def _uploadcircuit(self, request):
        if not self._authorized(request):
            return _json(401, {"error_description": "Expired token"})

        parts = _pathparts(request)
        jobid, name = parts[-3], parts[-1]

        if self.refuseuploads:
            return _json(500, {"error_description": "Refused"})

        if jobid not in self.jobs:
            return _json(404, {"error_description": "No such job"})

        self.circuits[jobid][name] = request.body

        return (201, {}, "")

    def _commit(self, request):
        if not self._authorized(request):
            return _json(401, {"error_description": "Expired token"})

        jobid = _pathparts(request)[-2]
        self.committed.append(jobid)
        self.jobs[jobid]["status"] = "COMMITED"

        return _json(200, {})

    def _cancel(self, request):
        if not self._authorized(request):
            return _json(401, {"error_description": "Expired token"})

        self.jobs[_pathparts(request)[-2]]["status"] = "CANCELED"

        return _json(200, {})

    def _job(self, request):
        if not self._authorized(request):
            return _json(401, {"error_description": "Expired token"})

        jobid = _pathparts(request)[-1]

        if jobid not in self.jobs:
            return _json(404, {"error_description": "No such job"})

        return _json(200, self.jobs[jobid])

    def _joblist(self, request):
        if not self._authorized(request):
            return _json(401, {"error_description": "Expired token"})

        return _json(200, list(self.jobs.values()))

    def _deletefiles(self, request):
        if not self._authorized(request):
            return _json(401, {"error_description": "Expired token"})

        jobid = _pathparts(request)[-1]

        if self.jobs.get(jobid, {}).get("status") not in ("SUCCESSFUL", "ERROR"):
            # The API answers 200 to say it refused, and 202 once the files are
            # scheduled for deletion.
            return _json(200, {"error_description": "The job is not completed"})

        self.files[(jobid, "results")] = []

        return _json(202, {})

    def _filelist(self, request):
        if not self._authorized(request):
            return _json(401, {"error_description": "Expired token"})

        parts = _pathparts(request)
        jobid, source = parts[-2], parts[-1]

        files = self.files.get((jobid, source), [])

        return _json(200, [f"{self.url}/download/{name}" for name, _ in files])

    def _download(self, request):
        name = _pathparts(request)[-1]

        for files in self.files.values():
            for filename, content in files:
                if filename == name:
                    headers = {
                        "Content-Disposition": f'attachment; filename="{filename}"'
                    }
                    return (200, headers, content)

        return _json(404, {"error_description": "No such file"})
