# MimiqLink (`mimiqlink-python`)

Library for connecting to **QPerfect**'s remote services for the MIMIQ Emulator.

## Installation
pip install mimiqlink

## Usage

```python
import mimiqlink

conn = mimiqlink.MimiqConnection()
conn.connectuser("email","password")
conn.connect() #for authentication through MIMIQ service manually
conn.request("name","label",["file 1 name","file 2 name",...])
job=conn.downloadFiles("executionRequestId","1","uploads")
job=conn.downloadjobFiles("executionRequestId")
``` 

# COPYRIGHT

Copyright © 2023 University of Strasbourg. All Rights Reserved.

# AUTHORS

See the [AUTHORS.md](AUTHORS.md) file for a list of authors