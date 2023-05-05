# MimiqLink (`mimiqlink-python`)

Library for connecting to **QPerfect**'s remote services for the MIMIQ Emulator.

## Installation
pip install mimiqlink

## Usage

```python
import mimiqlink

conn = mimiqlink.MimiqConnection()
conn.connectUser("email","password")
conn.connect() #for authentication through MIMIQ service manually
conn.request("name","label",["file 1 name","file 2 name",...])
job=conn.downloadFiles("executionRequestId","1","uploads")
job=conn.downloadjobFiles("executionRequestId")
``` 

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
