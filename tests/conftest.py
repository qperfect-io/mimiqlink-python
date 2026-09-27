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
"""Fixtures shared by the test suite.

Every fixture here hands back a server already answering and, where useful, a
client already connected to it, so a test can open with the thing it is about.
"""

import pytest
import responses

from mimiqlink import MimiqConnection, QhiveConnection

from tests.servers import MimiqServer, QhiveServer


@pytest.fixture
def mock():
    """A ``responses`` mock with no route registered yet."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mocked:
        yield mocked


@pytest.fixture
def mimiqserver(mock):
    return MimiqServer().install(mock)


@pytest.fixture
def mimiq(mimiqserver):
    """A connection authenticated against the MIMIQ server.

    The refresher thread is left running, as a real session would leave it, and
    torn down by ``close`` once the test returns. Its interval is 15 minutes,
    so it never fires during a test.
    """
    connection = MimiqConnection(mimiqserver.url)
    connection.connect(mimiqserver.issuetokens()["refreshToken"])

    yield connection

    connection.close()


@pytest.fixture
def qhiveserver(mock):
    return QhiveServer().install(mock)


@pytest.fixture
def qhive(qhiveserver):
    """A connection authenticated against the Quantum Hive server."""
    connection = QhiveConnection(url=qhiveserver.url, auth_url=qhiveserver.authurl)
    connection.connect(qhiveserver.email, qhiveserver.password)

    return connection
