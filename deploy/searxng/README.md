# GPU45 SearXNG

GPU45 uses a bare-metal SearXNG service bound to `127.0.0.1:8888` as the free search backend for the Research page and MCP web-search tools.

Install notes for Ubuntu 22.04/Python 3.10:

1. Create system user `searxng` and clone SearXNG to `/opt/searxng/searxng-src`.
2. Create `/opt/searxng/venv` and install `requirements.txt`, `requirements-server.txt`, and editable SearXNG with `--no-build-isolation`.
3. Python 3.10 needs `tomli` plus a `tomllib.py` compatibility shim in the venv site-packages because current SearXNG imports Python 3.11's `tomllib`.
4. Copy `settings.yml.example` to `/etc/searxng/settings.yml`, replace `secret_key`, and install `searxng.service` to `/etc/systemd/system/searxng.service`.
5. Enable and start with `systemctl enable --now searxng.service`.

SearXNG should not be exposed directly on the LAN. The Next.js appliance API proxies the needed search operations.
