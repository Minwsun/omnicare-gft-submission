# Third-party notices

OmniCare uses open-source packages through their normal package managers. No dependency source code is vendored into this repository. The package manifests and lockfile remain the source of truth for the exact dependency graph.

## JavaScript / TypeScript dependencies

| Package | Version | License | Source |
| --- | --- | --- | --- |
| Next.js | 16.2.12 | MIT | https://github.com/vercel/next.js |
| React / React DOM | 19.2.4 | MIT | https://github.com/facebook/react |
| Prisma Client / Prisma | 6.18.0 | Apache-2.0 | https://github.com/prisma/prisma |
| Zod | 4.4.3 | MIT | https://github.com/colinhacks/zod |
| Argon2 Node bindings | 2.0.2 | MIT | https://github.com/napi-rs/node-rs |
| TypeScript | 5.x | Apache-2.0 | https://github.com/microsoft/TypeScript |
| Tailwind CSS | 4.x | MIT | https://github.com/tailwindlabs/tailwindcss |
| ESLint | 9.x | MIT | https://github.com/eslint/eslint |

## Python dependencies

| Package | Supported version | License | Source |
| --- | --- | --- | --- |
| FastAPI | 0.110 - 0.x | MIT | https://github.com/fastapi/fastapi |
| Uvicorn | 0.29 - 0.x | BSD-3-Clause | https://github.com/encode/uvicorn |
| Pydantic | 2.6 - 2.x | MIT | https://github.com/pydantic/pydantic |
| asyncpg | 0.29 - 0.x | Apache-2.0 | https://github.com/MagicStack/asyncpg |
| LangChain | 1.1 - 1.x | MIT | https://github.com/langchain-ai/langchain |
| LangGraph | 1.x | MIT | https://github.com/langchain-ai/langgraph |
| langchain-openai | 1.x | MIT | https://github.com/langchain-ai/langchain |
| langgraph-checkpoint-postgres | 3.x | MIT | https://github.com/langchain-ai/langgraph |
| psycopg | 3.2 - 3.x | LGPL-3.0-only | https://github.com/psycopg/psycopg |
| HTTPX | 0.27 - 0.x | BSD-3-Clause | https://github.com/encode/httpx |
| Tenacity | 8 - 9.x | Apache-2.0 | https://github.com/jd/tenacity |

Each package remains subject to its own license. Transitive notices are distributed by the corresponding package release and can be inspected after installation in `node_modules` or Python package metadata.
