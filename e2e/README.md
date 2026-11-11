# Browser check

Opens every page of a running app, takes screenshots and prints JavaScript / HTTP errors.

    podman run --rm --network host \
      -v $PWD/e2e/screenshots.py:/shoot.py:ro,Z -v $PWD/e2e/shots:/shots:Z \
      mcr.microsoft.com/playwright/python:v1.49.0-noble \
      sh -c "pip install -q --break-system-packages playwright==1.49.0; python3 /shoot.py"

Expects the app on http://localhost:8000 with an open (no login) setup.
