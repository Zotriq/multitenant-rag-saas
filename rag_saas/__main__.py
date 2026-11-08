"""python -m rag_saas migrate | create-tenant "Company name" """

import os
import sys

from dotenv import load_dotenv

from .db import create_tenant, migrate

load_dotenv()
admin = os.environ["ADMIN_DATABASE_URL"]
cmd = sys.argv[1] if len(sys.argv) > 1 else ""
if cmd == "migrate":
    migrate(admin, int(os.getenv("EMBED_DIM", "1536")))
    print("Schema, RLS policies and rag_app role are ready.")
elif cmd == "create-tenant" and len(sys.argv) > 2:
    tenant_id, key = create_tenant(admin, sys.argv[2])
    print(f"tenant_id: {tenant_id}\napi_key:   {key}   (store it now, it is not shown again)")
else:
    sys.exit(__doc__)
