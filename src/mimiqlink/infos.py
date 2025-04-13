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


def format_datetime(dt_str):
    """Format a datetime string or timestamp in a more readable way."""
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
    """Class to hold and display information about a MIMIQ request."""

    STATUS_COLORS = {
        "NEW": "#3498db",  # Blue
        "RUNNING": "#f39c12",  # Orange
        "DONE": "#2ecc71",  # Green
        "ERROR": "#e74c3c",  # Red
        "CANCELED": "#95a5a6",  # Gray
    }

    def __init__(self, data):
        """
        Initialize RequestInfo with a dictionary of request data.

        Args:
            data (dict): Dictionary containing request information
        """
        self.data = data

    @property
    def id(self):
        """Get the request ID."""
        return self.data.get("_id", "Unknown")

    @property
    def name(self):
        """Get the request name."""
        return self.data.get("name", "Unknown")

    @property
    def label(self):
        """Get the request label."""
        return self.data.get("label", "Unknown")

    @property
    def status(self):
        """Get the request status."""
        return self.data.get("status", "Unknown")

    @property
    def user_email(self):
        """Get the user email."""
        return self.data.get("user", {}).get("email", "Unknown")

    @property
    def creation_date(self):
        """Get the creation date."""
        return format_datetime(self.data.get("creationDate"))

    @property
    def running_date(self):
        """Get the running date."""
        return format_datetime(self.data.get("runningDate"))

    @property
    def done_date(self):
        """Get the completion date."""
        return format_datetime(self.data.get("doneDate"))

    @property
    def num_upload_files(self):
        """Get the number of uploaded files."""
        return self.data.get("numberOfUploadedFiles", 0)

    @property
    def num_result_files(self):
        """Get the number of result files."""
        return self.data.get("numberOfResultedFiles", 0)

    def get(self, key, default):
        """Get a specific attribute from the request data."""
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
    """Class to hold and display a list of MIMIQ requests."""

    def __init__(self, data_list):
        """
        Initialize RequestInfoList with a list of request data dictionaries.

        Args:
            data_list (list): List of dictionaries containing request information
        """
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
        """Get a dictionary with counts of each status."""
        counts = {}
        for req in self.requests:
            status = req.status
            counts[status] = counts.get(status, 0) + 1
        return counts

    def __repr__(self):
        """Return a string representation of the request list."""
        if not self.requests:
            return "No requests available"

        # Create summary line
        running_count = self.status_counts.get("RUNNING", 0)
        new_count = self.status_counts.get("NEW", 0)
        done_count = self.status_counts.get("DONE", 0)
        error_count = self.status_counts.get("ERROR", 0)
        canceled_count = self.status_counts.get("CANCELED", 0)

        summary = f"Total: {len(self.requests)} requests - "
        status_parts = []
        if new_count > 0:
            status_parts.append(f"{new_count} NEW")
        if running_count > 0:
            status_parts.append(f"{running_count} RUNNING")
        if done_count > 0:
            status_parts.append(f"{done_count} DONE")
        if error_count > 0:
            status_parts.append(f"{error_count} ERROR")
        if canceled_count > 0:
            status_parts.append(f"{canceled_count} CANCELED")

        summary += ", ".join(status_parts)

        # Format header line with wider ID column (24 characters + some padding)
        header = "ID                          LABEL                STATUS"

        # Create the result list with summary and header
        result = [summary, header, "-" * len(header)]

        # Add a single line for each request
        for req in self.requests:
            # Format each field with fixed width (ID width increased to 26)
            req_id = f"{req.id:<26}"
            label = f"{req.label[:18]:<18}" + ("..." if len(req.label) > 18 else "  ")
            status = f"{req.status:<8}"

            line = f"{req_id}{label}{status}"
            result.append(line)

        return "\n".join(result)

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
