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
"""What a `QhiveConnection` does against Quantum Hive and its Keycloak realm.

A job here is not created in one call: the client opens it, uploads the
circuits one file at a time, and only then commits it. Several tests below are
about that sequence holding together.

Every failure raises `MimiqConnectionError`, which derives from the builtin
`ConnectionError`.
"""

import json

import pytest

from mimiqlink import QhiveConnection, MimiqConnectionError


# -- authentication ---------------------------------------------------------


def test_credentials_authenticate(qhiveserver):
    connection = QhiveConnection(url=qhiveserver.url, auth_url=qhiveserver.authurl)
    connection.connect(qhiveserver.email, qhiveserver.password)

    assert connection.isOpen()
    assert connection.access_token == qhiveserver.accesstoken


def test_wrong_credentials_leave_the_connection_closed(qhiveserver):
    connection = QhiveConnection(url=qhiveserver.url, auth_url=qhiveserver.authurl)

    with pytest.raises(Exception):
        connection.connect(qhiveserver.email, "not the password")

    assert not connection.isOpen()


def test_a_token_pair_authenticates(qhiveserver):
    tokens = qhiveserver.issuetokens()

    connection = QhiveConnection(url=qhiveserver.url, auth_url=qhiveserver.authurl)
    connection.connect(tokens)

    assert connection.isOpen()


def test_closing_ends_the_session(qhive, qhiveserver):
    qhive.close()

    assert qhive.access_token is None
    assert qhiveserver.accesstoken is None


def test_a_stale_access_token_is_refreshed_and_the_call_retried(qhive, qhiveserver):
    jobid = qhiveserver.addjob(status="PROCESSED")
    issued = qhiveserver.issued

    # The next authenticated call is refused once, as it would be if the token
    # had expired between two calls.
    qhiveserver.expireonce = True

    assert qhive.requestInfo(jobid).status == "PROCESSED"
    assert qhiveserver.issued == issued + 1


def test_calls_before_connecting_are_refused(qhiveserver):
    connection = QhiveConnection(url=qhiveserver.url, auth_url=qhiveserver.authurl)

    with pytest.raises(MimiqConnectionError, match="Connection is not open"):
        connection.requestInfo("job-1")


def test_a_token_file_round_trips(qhive, qhiveserver, tmp_path):
    credentials = tmp_path / "qperfect.json"

    qhive.savetoken(str(credentials))

    assert json.loads(credentials.read_text())["url"] == qhiveserver.url

    connection = QhiveConnection(url=qhiveserver.url, auth_url=qhiveserver.authurl)
    connection.loadtoken(str(credentials))

    assert connection.isOpen()


def test_a_token_file_for_another_server_is_refused(qhive, tmp_path):
    credentials = tmp_path / "qperfect.json"
    qhive.savetoken(str(credentials))

    connection = QhiveConnection(
        url="https://elsewhere.test/api", auth_url="https://elsewhere.test/auth/"
    )

    with pytest.raises(MimiqConnectionError, match="does not match"):
        connection.loadtoken(str(credentials))


# -- requests ---------------------------------------------------------------


def test_a_request_uploads_the_circuits_and_commits(qhive, qhiveserver, tmp_path):
    circuits = tmp_path / "circuits.json"
    circuits.write_text("{}")
    request = tmp_path / "request.json"
    request.write_text("{}")
    circuit = tmp_path / "circuit-1.pb"
    circuit.write_bytes(b"a circuit")

    jobid = qhive.request(
        "CIRC", "a name", "a label", 30, [str(circuits), str(request), str(circuit)]
    )

    # The two descriptors travel with the job, every other file separately.
    assert list(qhiveserver.circuits[jobid]) == ["circuit-1.pb"]
    assert qhiveserver.committed == [jobid]
    assert qhiveserver.jobs[jobid]["status"] == "COMMITED"


def test_a_job_whose_upload_fails_is_never_committed(qhive, qhiveserver, tmp_path):
    circuit = tmp_path / "circuit-1.pb"
    circuit.write_bytes(b"a circuit")

    qhiveserver.refuseuploads = True

    with pytest.raises(MimiqConnectionError, match="Failed upload circuit file"):
        qhive.request("CIRC", "a name", "a label", 30, [str(circuit)])

    assert qhiveserver.committed == []


def test_request_details_come_back(qhive, qhiveserver):
    jobid = qhiveserver.addjob(status="PROCESSED")

    assert qhive.requestInfo(jobid).status == "PROCESSED"


def test_the_list_of_requests_comes_back(qhive, qhiveserver):
    qhiveserver.addjob(status="NEW")
    qhiveserver.addjob(status="SUCCESSFUL")

    assert len(qhive.requests()) == 2


# -- job status -------------------------------------------------------------


# A canceled job is reported as *not* done here, unlike `isjobdone` in
# MimiqLink.jl, which counts it as done. See MimiqLink.jl!2.
@pytest.mark.parametrize(
    "status, done, started, failed, canceled",
    [
        ("NEW", False, False, False, False),
        ("AUTHORIZED", False, True, False, False),
        ("COMMITED", False, True, False, False),
        ("PROCESSED", False, True, False, False),
        ("SUCCESSFUL", True, False, False, False),
        ("ERROR", True, False, True, False),
        ("CANCELED", False, False, False, True),
    ],
)
def test_the_status_predicates_agree_with_the_status(
    qhive, qhiveserver, status, done, started, failed, canceled
):
    jobid = qhiveserver.addjob(status=status)

    assert qhive.isJobDone(jobid) is done
    assert qhive.isJobStarted(jobid) is started
    assert qhive.isJobFailed(jobid) is failed
    assert qhive.isJobCanceled(jobid) is canceled


# -- controlling a job ------------------------------------------------------


def test_an_execution_can_be_stopped(qhive, qhiveserver):
    jobid = qhiveserver.addjob(status="PROCESSED")

    qhive.stopExecution(jobid)

    assert qhiveserver.jobs[jobid]["status"] == "CANCELED"


def test_the_files_of_a_finished_job_can_be_deleted(qhive, qhiveserver):
    jobid = qhiveserver.addjob(status="SUCCESSFUL", results=[("samples.pb", b"samples")])

    qhive.deleteFiles(jobid)

    assert qhiveserver.files[(jobid, "results")] == []


def test_the_files_of_a_running_job_are_kept(qhive, qhiveserver):
    jobid = qhiveserver.addjob(status="PROCESSED", results=[("samples.pb", b"samples")])

    with pytest.raises(MimiqConnectionError, match="not completed"):
        qhive.deleteFiles(jobid)


# -- downloads --------------------------------------------------------------


def test_results_are_downloaded_under_their_own_names(qhive, qhiveserver, tmp_path):
    jobid = qhiveserver.addjob(
        status="SUCCESSFUL",
        results=[("amplitudes.pb", b"amplitudes"), ("samples.pb", b"samples")],
    )

    names = qhive.downloadFiles(jobid, "results", destdir=str(tmp_path))

    assert names == ["amplitudes.pb", "samples.pb"]
    assert (tmp_path / "samples.pb").read_bytes() == b"samples"
