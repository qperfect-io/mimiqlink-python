# MIMIQ Link Python

[![Build Status](https://github.com/qperfect-io/mimiqlink-python/workflows/Test/badge.svg)](https://github.com/qperfect-io/mimiqlink-python/actions)
[![PyPI version](https://badge.fury.io/py/mimiqlink.svg)](https://pypi.org/project/mimiqlink/)
[![Python versions](https://img.shields.io/pypi/pyversions/mimiqlink.svg)](https://pypi.org/project/mimiqlink/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

**MIMIQ Link** provides secure authentication and connection management for QPerfect's MIMIQ Virtual Quantum Computer. It handles all communication between Python environments and MIMIQ's remote execution services.

Part of the [MIMIQ](https://qperfect.io) ecosystem by [QPerfect](https://qperfect.io).

## Overview

MIMIQ Link offers flexible authentication methods to connect to MIMIQ's cloud services:

- 🌐 **Browser-based authentication**
- 🔑 **Token-based access** - Save and reuse authentication tokens
- 🔐 **Credential-based login** - Direct username/password authentication
- 🔄 **Automatic session management** - Token refresh and connection handling
- 🏢 **Multi-environment support** - Connect to different MIMIQ instances
- 📦 **Job management** - Submit, monitor, and retrieve quantum circuit execution results

## Installation

### From PyPI

```bash
pip install mimiqlink
```

### From GitHub

```bash
pip install "mimiqlink @ git+https://github.com/qperfect-io/mimiqlink-python.git"
```

### Requirements

- Python 3.8 or higher
- Supported on Linux, macOS, and Windows

> **Note:** Most users should install [mimiqcircuits](https://github.com/qperfect-io/mimiqcircuits-python) which includes this package and provides the full quantum circuit building experience.

## Quick Start

### Basic Connection

```python
import mimiqlink

# Create connection object
conn = mimiqlink.MimiqConnection()

# Connect using browser authentication (recommended)
conn.connect()
```

### Connection with Credentials

```python
import mimiqlink

conn = mimiqlink.MimiqConnection()

# Connect with username and password
conn.connectUser("your.email@example.com", "yourpassword")
```

> ⚠️ **Security Warning:** Avoid hardcoding credentials in your scripts. Use environment variables or secure configuration files instead.

## Authentication Methods

### Method 1: Browser Authentication (Recommended)

This method provides the most secure authentication flow:

```python
import mimiqlink

conn = mimiqlink.MimiqConnection()
conn.connect()  # Opens browser for secure login
```

This will:

1. Open your default web browser
2. Direct you to MIMIQ's login page
3. Securely authenticate your session
4. Return control to your Python script

### Method 2: Token-Based Authentication

Save your authentication token for reuse:

```python
import mimiqlink

# First time: authenticate and the token is saved automatically
conn = mimiqlink.MimiqConnection()
conn.savetoken("qperfect.json")
```

Then load the token in future sessions:

```python
import mimiqlink

conn = MimiqConnection().loadtoken(filepath="qperfect.json")
```

### Method 3: Credential-Based Authentication

For automated workflows where browser interaction isn't possible:

```python
import mimiqlink
import os

# Using environment variables (recommended)
conn = mimiqlink.MimiqConnection()
conn.connectUser(
    os.environ.get("MIMIQ_EMAIL"),
    os.environ.get("MIMIQ_PASSWORD")
)
```

## Working with Files and Jobs

### Submitting a Job

```python
import mimiqlink

conn = mimiqlink.MimiqConnection()
conn.connect()

# Submit a job with circuit files
conn.request(
    name="My Quantum Job",
    label="experiment-001",
    files=["circuit.qasm", "data.json"]
)
```

### Downloading Results

```python
import mimiqlink

conn = mimiqlink.MimiqConnection()
conn.connect()

# Download specific files from a job
job_data = conn.downloadFiles(
    executionRequestId="job-12345",
    fileId="1",
    downloadPath="./results"
)

# Download all job files
all_files = conn.downloadjobFiles(
    executionRequestId="job-12345"
)
```

### Checking Job Status

```python
import mimiqlink

conn = mimiqlink.MimiqConnection()
conn.connect()

# Get job status and information
status = conn.getJobStatus("job-12345")
print(f"Job status: {status}")
```

## Connection Configuration

### Custom MIMIQ Instance

Connect to a specific MIMIQ instance (useful for on-premises deployments):

```python
import mimiqlink

conn = mimiqlink.MimiqConnection(url="https://custom-mimiq.example.com/api")
conn.connect()
```

### Connection Timeout

Set custom timeout for API requests:

```python
import mimiqlink

conn = mimiqlink.MimiqConnection(timeout=60)  # 60 seconds
conn.connect()
```

## Usage with MIMIQ Circuits

MIMIQ Link is typically used through the MIMIQ Circuits package:

```python
from mimiqcircuits import *

# MimiqConnection from mimiqcircuits uses mimiqlink internally
conn = MimiqConnection()
conn.connect()

# Build and execute a circuit
circuit = Circuit()
circuit.push(GateH(), 0)
circuit.push(GateCX(), 0, 1)
circuit.push(Measure(), range(2), range(2))

# Execute on MIMIQ cloud
job = conn.execute(circuit, algorithm="auto", nsamples=1000)
results = conn.get_results(job)
```

## Security Best Practices

1. **Never commit credentials** to version control
2. **Use environment variables** for automated systems:

```python
import os
import mimiqlink

conn = mimiqlink.MimiqConnection()
conn.connectUser(
    os.getenv("MIMIQ_EMAIL"),
    os.getenv("MIMIQ_PASSWORD")
)
```

3. **Protect token files** - treat them like passwords
4. **Use browser authentication** when possible for maximum security
5. **Rotate tokens regularly** by re-authenticating

## Setting Up Environment Variables

### Linux/macOS

```bash
export MIMIQ_EMAIL="your.email@example.com"
export MIMIQ_PASSWORD="yourpassword"
```

### Windows (Command Prompt)

```cmd
set MIMIQ_EMAIL=your.email@example.com
set MIMIQ_PASSWORD=yourpassword
```

### Windows (PowerShell)

```powershell
$env:MIMIQ_EMAIL="your.email@example.com"
$env:MIMIQ_PASSWORD="yourpassword"
```

### Using a `.env` File

Create a `.env` file (and add it to `.gitignore`):

```
MIMIQ_EMAIL=your.email@example.com
MIMIQ_PASSWORD=yourpassword
```

Then use `python-dotenv`:

```python
from dotenv import load_dotenv
import os
import mimiqlink

load_dotenv()

conn = mimiqlink.MimiqConnection()
conn.connectUser(os.getenv("MIMIQ_EMAIL"), os.getenv("MIMIQ_PASSWORD"))
```

## Troubleshooting

### Token Expired

If your token has expired, simply reconnect:

```python
conn = mimiqlink.MimiqConnection()
conn.connect()  # This will refresh your token
```

### Checking Connection Status

```python
import mimiqlink

conn = mimiqlink.MimiqConnection()
conn.connect()

# Verify connection is active
if conn.isOpen():
    print("Successfully connected to MIMIQ")
else:
    print("Connection failed")
```

## API Reference

### MimiqConnection Class

**Constructor:**

```python
MimiqConnection()
```

**Methods:**

- `connect()` - Browser-based authentication
- `connectUser(email, password)` - Credential-based authentication
- `request(name, label, files)` - Submit a new job
- `downloadFiles(executionRequestId, fileId, downloadPath)` - Download specific files
- `downloadjobFiles(executionRequestId)` - Download all job files
- `getJobStatus(jobId)` - Get job execution status
- `close()` - Close connection and clean up resources

## Related Packages

- **[mimiqcircuits-python](https://github.com/qperfect-io/mimiqcircuits-python)** - Full quantum circuit library (includes this package)
- **[MimiqLink.jl](https://github.com/qperfect-io/MimiqLink.jl)** - Julia version of this library
- **[MimiqCircuits.jl](https://github.com/qperfect-io/MimiqCircuits.jl)** - Julia quantum circuits library

## Access to MIMIQ

To use MIMIQ's remote services, you need an active subscription:

- 🌐 **[Register at qperfect.io](https://qperfect.io)** to get started
- 📧 Contact us at <contact@qperfect.io> for organizational subscriptions
- 🏢 If your organization has a subscription, contact your account administrator

## Contributing

We welcome contributions! Whether you're:

- 🐛 Fixing bugs
- 💡 Adding features
- 📝 Improving documentation
- ✨ Suggesting enhancements

Feel free to open issues or pull requests.

## Support

- 📧 **Email:** <mimiq.support@qperfect.io>
- 🐛 **Bug Reports:** [GitHub Issues](https://github.com/qperfect-io/mimiqlink-python/issues)
- 💬 **Discussions:** [GitHub Discussions](https://github.com/qperfect-io/mimiqcircuits-python/discussions)
- 🌐 **Website:** [qperfect.io](https://qperfect.io)

## COPYRIGHT

Copyright © 2022-2023 University of Strasbourg. All Rights Reserved.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

---

**Made with ❤️ by the QPerfect team**
