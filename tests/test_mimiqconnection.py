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
"""What a `MimiqConnection` does against the MIMIQ API.

Every failure raises `MimiqConnectionError`, which derives from the builtin
`ConnectionError`.
"""

import pytest

from mimiqlink import MimiqConnection, MimiqConnectionError


# -- authentication ---------------------------------------------------------


def test_a_token_authenticates_and_is_rotated(mimiqserver):
    token = mimiqserver.issuetokens()["refreshToken"]

    connection = MimiqConnection(mimiqserver.url)
    connection.connect(token)

    # The server issues a new pair on every refresh, so the token that opened
    # the connection is already spent.
    assert connection.refresh_token != token
    assert connection.isOpen()

    connection.close()


def test_credentials_authenticate(mimiqserver):
    connection = MimiqConnection(mimiqserver.url)
    connection.connect(mimiqserver.email, mimiqserver.password)

    assert connection.isOpen()

    connection.close()


def test_wrong_credentials_are_refused(mimiqserver):
    connection = MimiqConnection(mimiqserver.url)

    with pytest.raises(MimiqConnectionError, match="Wrong email or password"):
        connection.connect(mimiqserver.email, "not the password")

    assert not connection.isOpen()


def test_a_spent_token_is_refused(mimiqserver):
    spent = mimiqserver.issuetokens()["refreshToken"]
    mimiqserver.issuetokens()

    connection = MimiqConnection(mimiqserver.url)

    with pytest.raises(MimiqConnectionError):
        connection.connect(spent)


def test_every_refresh_carries_the_new_token(mimiq, mimiqserver):
    mimiq.refresh()
    mimiq.refresh()

    assert mimiq.refresh_token == mimiqserver.refreshtoken
    assert mimiq.session.headers["Authorization"] == f"Bearer {mimiqserver.accesstoken}"


def test_closing_ends_the_session(mimiqserver):
    connection = MimiqConnection(mimiqserver.url)
    connection.connect(mimiqserver.issuetokens()["refreshToken"])

    connection.close()

    assert not connection.isOpen()
    assert connection.access_token is None
    assert connection.refresh_token is None


def test_calls_before_connecting_are_refused(mimiqserver):
    connection = MimiqConnection(mimiqserver.url)

    with pytest.raises(MimiqConnectionError, match="Not yet authenticated"):
        connection.requestInfo("job-1")


def test_the_api_lives_under_the_url(mimiqserver):
    connection = MimiqConnection(mimiqserver.url)

    assert connection.get_api_url() == f"{mimiqserver.url}/api"
    assert connection.get_api_url("request", "job-1") == f"{mimiqserver.url}/api/request/job-1"


# -- requests ---------------------------------------------------------------


def test_a_request_uploads_every_file(mimiq, mimiqserver, tmp_path):
    circuit = tmp_path / "circuit.pb"
    circuit.write_bytes(b"a circuit")
    parameters = tmp_path / "parameters.json"
    parameters.write_text("{}")

    jobid = mimiq.request("CIRC", "a name", "a label", 30, [str(circuit), str(parameters)])

    assert jobid in mimiqserver.jobs
    assert mimiqserver.lastupload == [
        ("name", ""),
        ("label", ""),
        ("emulatorType", ""),
        ("timeout", ""),
        ("uploads", "circuit.pb"),
        ("uploads", "parameters.json"),
    ]


def test_an_open_file_is_uploaded_under_its_own_name(mimiq, mimiqserver, tmp_path):
    circuit = tmp_path / "circuit.pb"
    circuit.write_bytes(b"a circuit")

    with open(circuit, "rb") as handle:
        mimiq.request("CIRC", "a name", "a label", 30, [handle])

    assert ("uploads", "circuit.pb") in mimiqserver.lastupload


def test_a_rejected_request_raises(mimiq, mimiqserver):
    mimiqserver.accesstoken = "some other token"

    with pytest.raises(MimiqConnectionError, match="File upload failed"):
        mimiq.request("CIRC", "a name", "a label", 30, [])


def test_request_details_come_back(mimiq, mimiqserver):
    jobid = mimiqserver.addjob(status="RUNNING")

    infos = mimiq.requestInfo(jobid)

    assert infos.id == jobid
    assert infos.status == "RUNNING"
    assert infos.user_email == mimiqserver.email


def test_an_unknown_request_raises(mimiq):
    with pytest.raises(MimiqConnectionError, match="Failed to retrieve execution details"):
        mimiq.requestInfo("no-such-job")


def test_requests_can_be_filtered(mimiq, mimiqserver):
    mimiqserver.addjob(status="NEW")
    mimiqserver.addjob(status="DONE")

    assert len(mimiq.requests()) == 2
    assert len(mimiq.requests(status="DONE")) == 1


# -- job status -------------------------------------------------------------


@pytest.mark.parametrize(
    "status, done, started, failed, canceled",
    [
        ("NEW", False, False, False, False),
        ("RUNNING", False, True, False, False),
        ("DONE", True, True, False, False),
        ("ERROR", True, True, True, False),
        ("CANCELED", True, True, False, True),
    ],
)
def test_the_status_predicates_agree_with_the_status(
    mimiq, mimiqserver, status, done, started, failed, canceled
):
    jobid = mimiqserver.addjob(status=status)

    assert mimiq.isJobDone(jobid) is done
    assert mimiq.isJobStarted(jobid) is started
    assert mimiq.isJobFailed(jobid) is failed
    assert mimiq.isJobCanceled(jobid) is canceled


# -- controlling a job ------------------------------------------------------


def test_an_execution_can_be_stopped(mimiq, mimiqserver):
    jobid = mimiqserver.addjob(status="RUNNING")

    mimiq.stopExecution(jobid)

    assert mimiqserver.jobs[jobid]["status"] == "CANCELED"


def test_stopping_an_unknown_execution_raises(mimiq):
    with pytest.raises(MimiqConnectionError, match="Failed to stop the execution"):
        mimiq.stopExecution("no-such-job")


def test_files_can_be_deleted(mimiq, mimiqserver):
    jobid = mimiqserver.addjob(status="DONE", results=[("results.pb", b"results")])

    mimiq.deleteFiles(jobid)

    assert mimiqserver.files[(jobid, "results")] == []


def test_deleting_the_files_of_an_unknown_job_raises(mimiq):
    with pytest.raises(MimiqConnectionError, match="Failed to delete the files"):
        mimiq.deleteFiles("no-such-job")


# -- downloads --------------------------------------------------------------


def test_results_are_downloaded_under_their_own_names(mimiq, mimiqserver, tmp_path):
    jobid = mimiqserver.addjob(
        status="DONE",
        results=[("amplitudes.pb", b"amplitudes"), ("samples.pb", b"samples")],
    )

    names = mimiq.downloadResults(jobid, destdir=str(tmp_path))

    assert names == ["amplitudes.pb", "samples.pb"]
    assert (tmp_path / "amplitudes.pb").read_bytes() == b"amplitudes"


def test_uploaded_files_are_downloaded_too(mimiq, mimiqserver, tmp_path):
    jobid = mimiqserver.addjob(status="DONE", uploads=[("circuit.pb", b"a circuit")])

    names = mimiq.downloadJobFiles(jobid, destdir=str(tmp_path))

    assert names == ["circuit.pb"]
    assert (tmp_path / "circuit.pb").read_bytes() == b"a circuit"


def test_a_job_without_files_downloads_nothing(mimiq, mimiqserver, tmp_path):
    jobid = mimiqserver.addjob(status="DONE")

    assert mimiq.downloadResults(jobid, destdir=str(tmp_path)) == []


# -- user limits ------------------------------------------------------------


def test_exceeded_limits_are_reported(mimiqserver, caplog):
    mimiqserver.limits = {
        "enabledExecutionTime": True,
        "usedExecutionTime": 120,
        "maxExecutionTime": 60,
        "enabledMaxExecutions": True,
        "usedExecutions": 11,
        "maxExecutions": 10,
        "enabledMaxTimeout": False,
    }

    connection = MimiqConnection(mimiqserver.url)
    connection.connect(mimiqserver.issuetokens()["refreshToken"])

    assert "computing time limit" in caplog.text
    assert "number of executions limit" in caplog.text

    connection.close()


# -- the exception ----------------------------------------------------------


def test_the_library_raises_one_exception(mimiqserver):
    """Both halves of the library used to raise a different class of the same
    name. Catching either name, or the builtin, must now catch everything."""
    from mimiqlink.abstractconnection import ConnectionError as OldName

    connection = MimiqConnection(mimiqserver.url)

    assert OldName is MimiqConnectionError
    assert issubclass(MimiqConnectionError, ConnectionError)

    # A failure from AbstractConnection and one from the authentication path.
    with pytest.raises(ConnectionError):
        connection.requestInfo("job-1")

    with pytest.raises(ConnectionError):
        connection.connect(mimiqserver.email, "not the password")
