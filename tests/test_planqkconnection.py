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
"""The token refresher of `PlanqkConnection`, with the PlanQK token endpoint
replaced by a stub."""

import threading
import time

from mimiqlink import PlanqkConnection
from mimiqlink.planqkconnection import JWTtoken


def test_closing_stops_the_refresher(monkeypatch):
    monkeypatch.setattr(
        PlanqkConnection,
        "get_planqk_token",
        lambda self, key, secret: JWTtoken("token", "", "Bearer", 3600),
    )
    connection = PlanqkConnection(consumer_key="key", consumer_secret="secret")
    connection.connect()

    # Let the refresher enter its sleep loop, where it takes the lock every second.
    time.sleep(1.5)
    closer = threading.Thread(target=connection.close, daemon=True)
    closer.start()
    closer.join(timeout=5)

    assert not closer.is_alive()
    assert not connection.isOpen()
