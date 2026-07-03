# JS Fetcher Provisioning

This provisions the binary used by the JS-rendering fallback fetcher described in
[ADR-040](../adr/ADR-040-js-rendering-fetcher.md). The reserved in-isolate binary path is:

```text
/opt/chromium_headless_shell/chrome-headless-shell
```

Use `chrome-headless-shell`, not full `chrome`. The spike in `poc/wsl2_browser/` found that full
Chrome opens background Google-service connections that churn against the sandbox allowlist and
blow the timeout; `chrome-headless-shell` avoids that path.

Pinned artifact:

- Chrome-for-Testing: `149.0.7827.55`
- Playwright chrome-headless-shell build: `1228`
- Chrome-for-Testing Linux x64 archive:
  `https://cdn.playwright.dev/builds/cft/149.0.7827.55/linux64/chrome-headless-shell-linux64.zip`
- Archive SHA-256: `410c9407d5de3fea80d9398666be06f2aa09154a3fa7b327dc254e336bb4c4b7`
- Linux x64 binary SHA-256:
  `670ba079b75107746ba41abad131180a31a7c7219aa1bd4061fb471f4535d541`

Run these from Windows PowerShell:

```powershell
wsl.exe -d Ubuntu -- sudo apt-get install -y python3.12-venv
wsl.exe -d Ubuntu -- sudo python3 -m venv /opt/pwvenv
wsl.exe -d Ubuntu -- sudo /opt/pwvenv/bin/pip install playwright
wsl.exe -d Ubuntu -- sudo /opt/pwvenv/bin/playwright install chromium
wsl.exe -d Ubuntu -- sudo /opt/pwvenv/bin/playwright install-deps chromium
```

Confirm the pinned headless-shell build was downloaded. Stop if this check fails; do not copy a
different build into the reserved path.

```powershell
wsl.exe -d Ubuntu -- sudo test -d /root/.cache/ms-playwright/chromium_headless_shell-1228
```

Copy the headless shell to the world-readable path used by the fetch isolate. The isolate drops to
uid `4000`, so it cannot read Playwright's root-owned cache directly.

```powershell
wsl.exe -d Ubuntu -- sudo mkdir -p /opt/chromium_headless_shell
wsl.exe -d Ubuntu -- sudo cp -r /root/.cache/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-linux64/. /opt/chromium_headless_shell/
wsl.exe -d Ubuntu -- sudo chmod -R a+rX /opt/chromium_headless_shell
```

Verify the copied binary checksum:

```powershell
wsl.exe -d Ubuntu -- sh -c "echo '670ba079b75107746ba41abad131180a31a7c7219aa1bd4061fb471f4535d541  /opt/chromium_headless_shell/chrome-headless-shell' | sha256sum -c -"
```

Optional version sanity check:

```powershell
wsl.exe -d Ubuntu -- /opt/chromium_headless_shell/chrome-headless-shell --version
```

If invoking from Git Bash instead of PowerShell, set `MSYS_NO_PATHCONV=1` for each `wsl.exe` call so
Unix paths such as `/opt/chromium_headless_shell` are not rewritten before WSL receives them.
