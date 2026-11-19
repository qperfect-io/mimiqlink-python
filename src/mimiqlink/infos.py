# FILE src/./request_info.py
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

from datetime import datetime
from tabulate import tabulate

def format_datetime(dt_str):
    """Format a timestamp or an ISO 8601 date as ``YYYY-MM-DD HH:MM:SS``.

    Numbers (or digit strings) are Unix timestamps, in milliseconds when
    above ``10**12`` and in seconds otherwise, shown in local time. Empty
    values and ``"None"`` give ``"Not available"``; values that cannot be
    parsed are returned unchanged.

    Examples:
        >>> format_datetime("2024-05-01T12:30:00Z")
        '2024-05-01 12:30:00'
        >>> format_datetime(None)
        'Not available'
    """
    if not dt_str or dt_str == "None":
        return "Not available"

    try:
        # Check if it's a timestamp (number)
        if isinstance(dt_str, (int, float)) or (
            isinstance(dt_str, str) and dt_str.isdigit()
        ):
            # Convert to integer timestamp if it's a string
            timestamp = int(dt_str) if isinstance(dt_str, str) else dt_str

            # Check if it's in milliseconds (13 digits typically)
            if timestamp > 1000000000000:  # Likely milliseconds
                timestamp = timestamp / 1000  # Convert to seconds

            # Convert timestamp to datetime
            from datetime import datetime

            dt = datetime.fromtimestamp(timestamp)
            return dt.strftime("%Y-%m-%d %H:%M:%S")

        # Try to parse ISO format if it's not a timestamp
        from datetime import datetime

        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    except (ValueError, TypeError):
        # If all conversion attempts fail, return as is
        return dt_str


class RequestInfo:
    """Details of one execution, as returned by the service.

    The properties read the common fields and fall back to ``"Unknown"`` (or
    0 for file counts) when the service does not send them. :meth:`get`
    reads any other field. In Jupyter it displays as a table.

    Args:
        data (dict): The execution data returned by the service.

    Examples:
        >>> from mimiqlink.infos import RequestInfo
        >>> info = RequestInfo({"_id": "abc123", "name": "mps", "status": "DONE"})
        >>> info.id, info.status
        ('abc123', 'DONE')
        >>> info.label
        'Unknown'
        >>> info.get("numberOfResultedFiles", 0)
        0
    """

    STATUS_COLORS = {
        "NEW": "#3498db",       # Blue
        "RUNNING": "#f39c12",   # Orange
        "DONE": "#2ecc71",      # Green
        "ERROR": "#e74c3c",     # Red
        "CANCELED": "#95a5a6",  # Gray
    }

    def __init__(self, data):
        self.data = data

    @property
    def id(self):
        """The execution identifier (``"_id"``)."""
        return self.data.get("_id", "Unknown")

    @property
    def name(self):
        """The execution name."""
        return self.data.get("name", "Unknown")

    @property
    def label(self):
        """The execution label."""
        return self.data.get("label", "Unknown")

    @property
    def status(self):
        """The execution status, such as ``"NEW"``, ``"RUNNING"``, ``"DONE"``, ``"ERROR"`` or ``"CANCELED"``."""
        return self.data.get("status", "Unknown")

    @property
    def user_email(self):
        """The email address of the user who submitted the execution."""
        return self.data.get("user", {}).get("email", "Unknown")

    @property
    def creation_date(self):
        """The creation date, formatted by :func:`format_datetime`."""
        return format_datetime(self.data.get("creationDate"))

    @property
    def running_date(self):
        """The date the execution started running, formatted by :func:`format_datetime`."""
        return format_datetime(self.data.get("runningDate"))

    @property
    def done_date(self):
        """The completion date, formatted by :func:`format_datetime`."""
        return format_datetime(self.data.get("doneDate"))

    @property
    def num_upload_files(self):
        """The number of uploaded files."""
        return self.data.get("numberOfUploadedFiles", 0)

    @property
    def num_result_files(self):
        """The number of result files."""
        return self.data.get("numberOfResultedFiles", 0)

    def get(self, key, default):
        """Return the field ``key`` of the execution data, or ``default`` if it is missing."""
        return self.data.get(key, default)

    def __repr__(self):
        """Return a single line string representation of the request info."""
        result = (
            f"Request {self.id} | Name: {self.name} | Label: {self.label} | "
            f"Status: {self.status} | User: {self.user_email} | "
            f"Created: {self.creation_date} | Running: {self.running_date} | "
            f"Completed: {self.done_date}"
        )

        if self.num_upload_files > 0 or self.num_result_files > 0:
            result += (
                f" | Files: {self.num_upload_files}/{self.num_result_files} (up/res)"
            )

        return result

    def _repr_html_(self):
        """
        Return an HTML representation of the request info.
        This will be automatically used by Jupyter notebooks.
        """
        status_color = self.STATUS_COLORS.get(self.status, "#95a5a6")

        html = f"""
        <div style="margin: 10px; padding: 10px; border: 1px solid #ddd; border-radius: 5px; max-width: 600px;">
            <h3 style="margin-top: 0; color: #333;">Request {self.id}</h3>
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 4px 10px 4px 0; font-weight: bold;">Name:</td>
                    <td>{self.name}</td>
                </tr>
                <tr>
                    <td style="padding: 4px 10px 4px 0; font-weight: bold;">Label:</td>
                    <td>{self.label}</td>
                </tr>
                <tr>
                    <td style="padding: 4px 10px 4px 0; font-weight: bold;">Status:</td>
                    <td><span style="background-color: {status_color}; color: white; padding: 2px 6px; border-radius: 3px;">{self.status}</span></td>
                </tr>
                <tr>
                    <td style="padding: 4px 10px 4px 0; font-weight: bold;">User Email:</td>
                    <td>{self.user_email}</td>
                </tr>
                <tr>
                    <td style="padding: 4px 10px 4px 0; font-weight: bold;">Created:</td>
                    <td>{self.creation_date}</td>
                </tr>
                <tr>
                    <td style="padding: 4px 10px 4px 0; font-weight: bold;">Running:</td>
                    <td>{self.running_date}</td>
                </tr>
                <tr>
                    <td style="padding: 4px 10px 4px 0; font-weight: bold;">Completed:</td>
                    <td>{self.done_date}</td>
                </tr>
        """

        if self.num_upload_files > 0:
            html += f"""
                <tr>
                    <td style="padding: 4px 10px 4px 0; font-weight: bold;">Uploaded Files:</td>
                    <td>{self.num_upload_files}</td>
                </tr>
            """

        if self.num_result_files > 0:
            html += f"""
                <tr>
                    <td style="padding: 4px 10px 4px 0; font-weight: bold;">Result Files:</td>
                    <td>{self.num_result_files}</td>
                </tr>
            """

        html += """
            </table>
        </div>
        """
        return html


class RequestInfoList:
    """A list of executions, as returned by ``requests()``.

    It supports ``len``, indexing and iteration over :class:`RequestInfo`
    items. Printed, it shows a status summary and a table of identifiers,
    labels and statuses; in Jupyter it displays as a table.

    Args:
        data_list (list[dict]): The execution data returned by the service.

    Examples:
        >>> from mimiqlink.infos import RequestInfoList
        >>> jobs = RequestInfoList([
        ...     {"_id": "a1", "status": "DONE"},
        ...     {"_id": "b2", "status": "ERROR"},
        ...     {"_id": "c3", "status": "DONE"},
        ... ])
        >>> len(jobs), jobs[1].id
        (3, 'b2')
        >>> jobs.status_counts
        {'DONE': 2, 'ERROR': 1}
    """

    def __init__(self, data_list):
        self.requests = [RequestInfo(data) for data in data_list]

    def __len__(self):
        """Return the number of requests in the list."""
        return len(self.requests)

    def __getitem__(self, idx):
        """Get the request at the specified index."""
        return self.requests[idx]

    def __iter__(self):
        """Return an iterator over the requests."""
        return iter(self.requests)

    @property
    def status_counts(self):
        """A dictionary mapping each status to its number of executions."""
        counts = {}
        for req in self.requests:
            status = req.status
            counts[status] = counts.get(status, 0) + 1
        return counts

    def __repr__(self):
        """Return a string representation of the request list."""
        if not self.requests:
            return "No requests available"

        summary = f"Total: {len(self.requests)} requests - "
        status_parts = [
            f"{self.status_counts.get(label)} {label}"
            for label in self.status_counts
        ]

        summary += ", ".join(status_parts)
        header = ["ID","LABEL", "STATUS"]
        rows = [ [req.id, req.label[:18], req.status] for req in self.requests ]

        return f"{summary}\n{tabulate(rows, headers=header)}"

    def _repr_html_(self):
        """
        Return an HTML representation of the request list as a table.
        This will be automatically used by Jupyter notebooks.
        """
        if not self.requests:
            return "<p>No requests available</p>"

        # Summary section
        status_summary = " | ".join(
            f"{status}: <b>{count}</b>" for status, count in self.status_counts.items()
        )

        html = f"""
        <div style="margin: 10px; padding: 10px; border: 1px solid #ddd; border-radius: 5px; max-width: 100%;">
            <h2 style="margin-top: 0; color: #333;">Request Summary</h2>
            <p>Total: <b>{len(self.requests)}</b> requests ({status_summary})</p>
            <div style="max-height: 800px; overflow-y: auto; overflow-x: auto;">
                <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                    <thead>
                        <tr style="background-color: #f8f9fa; border-bottom: 2px solid #ddd;">
                            <th style="text-align: left; padding: 8px; white-space: nowrap;">ID</th>
                            <th style="text-align: left; padding: 8px; white-space: nowrap;">Name</th>
                            <th style="text-align: left; padding: 8px; white-space: nowrap;">Label</th>
                            <th style="text-align: center; padding: 8px; white-space: nowrap;">Status</th>
                            <th style="text-align: left; padding: 8px; white-space: nowrap;">User Email</th>
                            <th style="text-align: left; padding: 8px; white-space: nowrap;">Created</th>
                            <th style="text-align: left; padding: 8px; white-space: nowrap;">Running</th>
                            <th style="text-align: left; padding: 8px; white-space: nowrap;">Completed</th>
                            <th style="text-align: center; padding: 8px; white-space: nowrap;">Upload Files</th>
                            <th style="text-align: center; padding: 8px; white-space: nowrap;">Result Files</th>
                        </tr>
                    </thead>
                    <tbody>
        """

        # Add each request as a row in the table
        for i, req in enumerate(self.requests):
            status_color = RequestInfo.STATUS_COLORS.get(req.status, "#95a5a6")
            row_style = "background-color: #f8f8f8;" if i % 2 == 0 else ""

            html += f"""
                        <tr style="{row_style}">
                            <td style="padding: 8px; border-bottom: 1px solid #ddd;">{req.id}</td>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd;">{req.name}</td>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd;">{req.label}</td>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd; text-align: center;"><span style="background-color: {status_color}; color: white; padding: 2px 6px; border-radius: 3px;">{req.status}</span></td>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd;">{req.user_email}</td>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd;">{req.creation_date}</td>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd;">{req.running_date}</td>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd;">{req.done_date}</td>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd; text-align: center;">{req.num_upload_files}</td>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd; text-align: center;">{req.num_result_files}</td>
                        </tr>
            """

        html += """
                    </tbody>
                </table>
            </div>
        </div>
        """

        return html
