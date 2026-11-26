import os
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn


with TemporaryDirectory() as root:
    os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(root, "playwright.db"))
    uvicorn.run("apps.insurance_claims.api:app", host="127.0.0.1", port=8128,
                proxy_headers=False, access_log=False)
