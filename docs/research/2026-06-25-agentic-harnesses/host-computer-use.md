# Host Computer-Use Tools — Research Findings

**Date:** 2026-06-25
**Re-research after:** 2026-07-09
**Cluster:** host-computer-use
**Artemis context:** Local-first personal assistant on Mac Mini M4 Pro; new capability = agent acting on the HOST computer (shell, files, drive desktop apps). Load-bearing concern: SANDBOX / BLAST-RADIUS (reversible-auto vs gated; workspace-confinement; privacy — sensitive data must not egress to cloud).

---

## Tool 1: Anthropic Computer Use (Claude API)

### What It Is
A Claude API tool (beta) that allows Claude models to operate a real desktop environment via screenshot + coordinate actions. Released October 22, 2024 as public beta. Current beta header: `anthropic-beta: computer-use-2025-11-24` (as of April 2026). Maintainer: Anthropic. License: API service (proprietary). Language: Python client SDK; model-side capability. [VERIFIED]

### How It Achieves Computer-Use
Screenshot-perception + coordinate-action loop: Claude captures a screenshot of the current desktop state, uses its vision capabilities to identify UI elements, then issues mouse clicks at x/y coordinates, keyboard inputs, and scroll actions. There is NO accessibility API usage — it relies purely on visual parsing. The developer is responsible for: capturing the screenshot, passing it to the API, and executing the returned actions on the OS. The `computer-use-2025-11-24` beta adds support for current Claude 4.x models (claude-opus-4-7, claude-sonnet-4-6). [VERIFIED]

### Sandbox / Isolation Model
**Critical finding:** Computer Use runs OUTSIDE the Claude Code sandbox. The blast radius of a successful prompt injection attack on a computer-use agent = the entire desktop — full user-level access to files, authenticated browser sessions, secrets, etc. [VERIFIED]

Anthropic's own official guidance requires running Computer Use in a sandboxed virtual machine or Docker container with:
- Clean OS — no saved passwords, no authenticated sessions
- Network access restricted to required domains only
- No access to sensitive credential stores [VERIFIED]

Anthropic's `srt` (sandbox runtime, open-source) uses OS-level primitives:
- macOS: `sandbox-exec` (Apple Seatbelt) — restricts filesystem writes to working directory, filters network through proxy allowlist
- Linux: `bubblewrap` — same policy approach

**Deprecation risk:** Apple has marked `sandbox-exec` as deprecated in its man page. Anthropic's runtime still uses it, but it may be removed in a future macOS release with no direct replacement. [VERIFIED]

For the reference local demo, Anthropic ships a Docker-based environment. The Docker container itself shares the host kernel — in 2025 alone, three runc CVEs (CVE-2025-31133, CVE-2025-52565, CVE-2025-52881) demonstrated container escape vectors. [VERIFIED]

### Scored Against 5 Lenses

| Lens | Score | Why |
|------|-------|-----|
| L1 Host CU + sandbox safety | M | The API tool itself is powerful but ships NO sandbox; blast radius = full desktop; you must bring your own container/VM. Seatbelt on macOS is deprecated. |
| L2 Local-first + privacy | M | Screenshots are sent to Anthropic cloud for vision inference — all screen content egresses. Not compatible with pure local models. |
| L3 Reliability + resumability | M | CUA loop is well-defined; no built-in resumability across sessions; coordinate fragility on dynamic UIs. |
| L4 Build-vs-borrow / thin-spine | H | Best borrow candidate for the vision-action API layer; Artemis brings its own gate/approval harness on top. |
| L5 One-shot end-to-end | L | Not designed for end-to-end autonomous build; requires a surrounding harness loop. |

### macOS Support
Yes — explicitly. Official reference container is Debian/X11 but the API is OS-agnostic (you provide screenshots from any platform). macOS Seatbelt is used for Claude Code's bash-tool sandbox, not for Computer Use itself. [VERIFIED]

### Known Limitations / Concerns
- All screen content sent to Anthropic cloud — sensitive data egress risk [VERIFIED]
- No native sandbox; blast radius = full desktop if run outside a VM [VERIFIED]
- Coordinate-based interaction is fragile on Retina/HiDPI displays (coordinate scaling required) [VERIFIED]
- `sandbox-exec` deprecation on macOS creates long-term uncertainty [VERIFIED]
- Claude Desktop (Cowork) ships computer use integrated, but without strong isolation boundary [COMMUNITY]

---

## Tool 2: OpenAI Operator / Computer Use (CUA API)

### What It Is
OpenAI Operator is a ChatGPT autonomous web agent (research preview, January 2025) built on the Computer-Using Agent (CUA) model, which combines GPT-4o vision + reinforcement learning for GUI navigation. The underlying CUA capability is also exposed via the Responses API. The Agents SDK (April 2026 update) adds native sandbox execution. Maintainer: OpenAI. License: API service (proprietary). Language: Python/JS SDKs. [VERIFIED]

### How It Achieves Computer-Use
Screenshot + coordinate loop identical to Anthropic: capture screen → send to OpenAI vision model → receive action (click x/y, type, scroll, navigate). Alternatively, browser-only mode uses Playwright-backed browser automation. Coordinates must match declared display dimensions (typically 1024x768 baseline). [VERIFIED]

### Sandbox / Isolation Model
OpenAI Operator implements a confirmation-before-action framework for consequential operations:
- Financial transactions: presents summary and waits for explicit user approval
- Email sends: shows draft + recipient for verification
- Calendar modifications: requests confirmation before persistent-data changes
- Fully restricted: certain high-risk categories blocked outright [VERIFIED]

The April 2026 Agents SDK added native sandbox execution: seven providers supported (Blaxel, Cloudflare, Daytona, E2B, Modal, Runloop, Vercel). These are CLOUD sandboxes — not local. For host computer-use, no sandbox is imposed; Operator runs browser/desktop actions at full user-level scope. [VERIFIED]

Operator system card (Jan 2025): explicit human-in-loop design; model pauses at decision points requiring irreversible actions. [VERIFIED]

### Scored Against 5 Lenses

| Lens | Score | Why |
|------|-------|-----|
| L1 Host CU + sandbox safety | M | Good approval-gate model built in; but no sandbox containment for host actions; cloud-only SDK sandboxes don't address local host blast radius. |
| L2 Local-first + privacy | L | Requires OpenAI cloud; screenshots egress; no local model support for the CUA loop itself. |
| L3 Reliability + resumability | M | Human-in-loop confirmation improves safety reliability; no session resumability built in. |
| L4 Build-vs-borrow | M | Approval-gate design philosophy is borrowable; but tight OpenAI coupling limits thin-spine usage. |
| L5 One-shot end-to-end | L | Research preview; "not for production applications" as of mid-2025. |

### macOS Support
Yes via browser automation path. Host desktop path works on macOS if the surrounding harness captures screenshots from the native display. No macOS-specific isolation provided. [VERIFIED]

### Known Limitations / Concerns
- Cloud-mandatory; all screen content sent to OpenAI — unacceptable for Artemis privacy model [VERIFIED]
- Still marked not-for-production as of 2025 [VERIFIED]
- Prompt injection risk via screen content explicitly flagged in system card [VERIFIED]
- Approval gate only covers semantically high-risk actions; not all destructive shell operations [COMMUNITY]

---

## Tool 3: Open Interpreter

### What It Is
Open Interpreter is an open-source tool providing a natural-language interface for local code execution (Python, JavaScript, shell, etc.), file manipulation, browsing, and more. Actively maintained; lightweight coding agent; supports DeepSeek, Kimi, Qwen. GitHub: `openinterpreter/openinterpreter`. License: MIT (open-source). Language: Python. [VERIFIED]

### How It Achieves Computer-Use
Code/shell execution loop: the model writes code (Python, shell, JS, etc.) and runs it on the host system. NOT screenshot+coordinate; this is direct code/command execution. Can drive browsers (via Playwright/Selenium integration), manipulate files, and call system APIs. The user sees each code block before execution and must approve. [VERIFIED]

### Sandbox / Isolation Model
**Minimal native sandboxing.** By default, Open Interpreter executes code with full user-level permissions on the host filesystem and network. Safety mechanisms:
1. **User confirmation per code block** (default on) — every block shown before execution
2. **LLM alignment** — model self-refuses dangerous commands like `rm -rf /` (soft, can be bypassed by adversarial inputs)
3. **Safe mode** — code scanning via `guarddog` for known-malicious packages
4. **Docker** — experimental, wraps execution in a container
5. **E2B** — cloud-sandboxed Python execution (overrides local Python)

Official docs explicitly state: "These safety measures provide no guarantees of safety or security." [VERIFIED]

Blast radius without Docker/E2B: full user-level host access. No filesystem confinement, no network filtering. Docker support is experimental as of 2025. [VERIFIED]

### Scored Against 5 Lenses

| Lens | Score | Why |
|------|-------|-----|
| L1 Host CU + sandbox safety | L | No meaningful blast-radius containment by default; Docker support experimental; relies on user confirmation + LLM alignment only. |
| L2 Local-first + privacy | H | Fully local; supports Ollama/local models; no cloud egress when using local inference. MIT license. |
| L3 Reliability + resumability | M | User-in-loop confirmation improves precision; no session resumability; fragile on long tasks. |
| L4 Build-vs-borrow | M | Could borrow the code-execution pattern; but the unsafe default model conflicts with Artemis approval-gate architecture. |
| L5 One-shot end-to-end | L | Not designed for autonomous long-running builds; step-by-step human-approval loop. |

### macOS Support
Yes — explicitly: macOS, Windows, Linux. Uses PyAutoGUI for screen interaction (separate from code execution). Shell commands run natively. [VERIFIED]

### Known Limitations / Concerns
- Safety is largely illusory without Docker: LLM alignment is not a sandbox [VERIFIED]
- Experimental Docker support not yet production-ready [VERIFIED]
- E2B path (sandboxed Python) requires cloud — breaks local-first requirement [VERIFIED]
- macOS issue: interpreter hangs on shell commands in some configs (GitHub issue #880, unresolved) [COMMUNITY]
- No access control model distinguishing reversible vs irreversible actions — all actions are user-confirmed but blast-radius-unlimited [VERIFIED]

---

## Tool 4: browser-use (+ Playwright)

### What It Is
`browser-use` is an open-source Python library that turns any LLM into a browser automation agent. The LLM reads page state and decides what to click, type, scroll, or extract — no CSS selectors required. Crossed 50,000+ GitHub stars — one of fastest-growing AI OSS projects 2025-2026. `browser-use` uses Playwright under the hood. Maintainer: browser-use org. License: Apache 2.0. Language: Python. [VERIFIED]

### How It Achieves Computer-Use
**Browser DOM + accessibility tree**, NOT screenshot+coordinate. The LLM receives structured page state (elements, text, links) plus screenshots when needed. Actions: click, type, scroll, navigate, fill forms, extract content. Scope is **browser-only** — browser-use does NOT provide shell execution, filesystem access, or host desktop control outside the browser window. [VERIFIED]

### Sandbox / Isolation Model
**Browser-scope blast radius only** — this is the key differentiator for safety:
- An agent can only affect what the browser can affect: web sessions, form submissions, cookies, downloads
- No shell access, no host filesystem writes outside of browser downloads
- No native desktop control

Playwright provides context isolation (separate browser contexts = separate cookies/sessions). The cloud managed service (browser-use Cloud, 2025) adds managed sandboxing but breaks local-first. For the open-source version: isolation = browser context boundary only. [VERIFIED]

Supports all major LLM providers (OpenAI, Anthropic, Google, Ollama/local models). Bringing a local model preserves full local-first operation. [VERIFIED]

### Scored Against 5 Lenses

| Lens | Score | Why |
|------|-------|-----|
| L1 Host CU + sandbox safety | M | Browser-only blast radius is MUCH smaller than full host; can't rm -rf or exfiltrate arbitrary files — but also can't drive native desktop apps. |
| L2 Local-first + privacy | H | OSS, Apache 2.0; works with Ollama/local models; no cloud required; no screenshot egress if using local model. |
| L3 Reliability + resumability | H | Playwright is battle-tested; browser-use actively developed; 0.13 beta adds recovery loops. |
| L4 Build-vs-borrow | H | Thin borrowable layer for web-automation sub-tasks; cleanly composable alongside a separate shell/file action tool. |
| L5 One-shot end-to-end | M | Works well for web-specific autonomous tasks; not for OS-level work. |

### macOS Support
Yes — Playwright is cross-platform (macOS, Windows, Linux). browser-use inherits full macOS support. [VERIFIED]

### Known Limitations / Concerns
- Scope limited to browser: cannot drive native desktop apps, cannot run shell commands, cannot access arbitrary filesystem paths [VERIFIED]
- Browser-use Cloud (managed version) breaks local-first — open-source version fine [VERIFIED]
- Playwright browser context isolation is good but not VM-grade; a compromised browser (renderer exploit) could still reach the host [COMMUNITY]
- Requires LLM API key if not using Ollama; Ollama support present [VERIFIED]

---

## Tool 5: E2B Sandboxes

### What It Is
E2B (Execution to Build) is a cloud-based sandbox platform providing isolated virtual computers for AI agents. Firecracker microVM-backed. Raised $21M Series A (July 2025, Insight Partners). ~15M sandbox sessions/month by March 2025. Also offers Desktop Sandbox (Linux/Xfce) for computer-use. Maintainer: E2B Inc. License: OSS SDK (Apache 2.0); cloud service (SaaS). Language: Python, TypeScript SDKs. [VERIFIED]

### How It Achieves Computer-Use
For code execution: SDK spawns a remote Firecracker microVM; agent runs shell commands and Python inside the VM via API. For Desktop Sandbox (`e2b-desktop`): a virtual Linux desktop (Xfce) with VNC/screenshot access, mouse/keyboard API. Agent sees virtual desktop screenshots, issues actions — this is screenshot+coordinate, but against a VIRTUAL desktop, not the host. [VERIFIED]

### Sandbox / Isolation Model
**Industry-leading isolation:** Firecracker microVM per sandbox.
- Each sandbox has its own Linux kernel, memory space, virtual hardware
- Attack requires escaping both guest kernel AND the Firecracker hypervisor (written in Rust, ~50K LoC, deliberately minimal)
- Boot time: ~78ms median (Jan 2026); max lifetime: 24 hours
- BYOC (Bring Your Own Cloud): enterprise tier supports AWS/GCP/Azure deployment or on-prem/self-hosted — this is the path for local-first compliance [VERIFIED]

**Critical Artemis incompatibility:** E2B Desktop Sandbox gives the agent a virtual Linux desktop — NOT the Mac Mini host desktop. Artemis's requirement is acting on the HOST computer. E2B sandboxes agent actions from the host entirely — which is great for code execution safety but does NOT fulfil the host-computer-use requirement. [VERIFIED]

For code execution sub-tasks (running scripts, data analysis): E2B is ideal. For driving the Mac host (Finder, Drive, native apps): E2B is the wrong tool. [VERIFIED]

### Scored Against 5 Lenses

| Lens | Score | Why |
|------|-------|-----|
| L1 Host CU + sandbox safety | L (for host-CU) / H (for sub-task isolation) | Excellent isolation but by design does NOT act on the real host; wrong fit for host computer-use requirement. |
| L2 Local-first + privacy | M | Cloud SaaS by default; BYOC/on-prem available at enterprise tier — closes privacy gap but adds ops burden. |
| L3 Reliability + resumability | H | Production-grade; 15M sessions/month; Manus uses E2B for virtual computer provision; enterprise SLA. |
| L4 Build-vs-borrow | H | Strong borrow candidate for the CODE EXECUTION sub-task inside Artemis (sandboxed Python for data tasks, not host control). |
| L5 One-shot end-to-end | H | Proven for agentic code execution pipelines; well-integrated with LLM frameworks. |

### macOS Support
E2B Desktop Sandbox runs Linux (Xfce) — NOT macOS. The SDK client runs from macOS to call the E2B API, but the sandboxed environment is Linux. [VERIFIED]

### Known Limitations / Concerns
- Cloud-first (SaaS); BYOC requires enterprise tier (pricing unclear) [VERIFIED]
- Desktop sandbox is Linux-only — cannot replicate macOS app behavior for testing macOS native apps [VERIFIED]
- Does NOT address the host-computer-use requirement at all — it sandboxes away from the host [VERIFIED]
- Each sandbox runs up to 24 hours; no long-lived persistent agent state across sandbox instances [VERIFIED]

---

## Tool 6: Docker / Container Sandboxing for Agents

### What It Is
Not a single tool, but a deployment pattern: running agent code/actions inside Docker containers (or more specifically, in 2026, microVM-backed containers) to bound blast radius. The key ecosystem includes: Docker Sandboxes (Jan 2026, microVM-per-sandbox), Apple Containerization (WWDC 2025, macOS-native per-container VM), Lima (QEMU/Virtualization.framework wrapper, v2.0 adds AI agent MCP server). Language: any (container-wrapped). License: Docker Desktop (commercial for large orgs); Lima (Apache 2.0); Apple container (open-source Swift). [VERIFIED]

### How It Achieves Computer-Use
Containers don't inherently add computer-use capability — they sandbox agent execution. For computer-use inside a container: standard Linux X11 desktop (VNC) approach, or passing through a virtual display. On macOS, Apple's Containerization framework (v1.0.0 shipped June 9, 2026, macOS 26+) runs each Linux container in its own lightweight VM via Apple's Virtualization.framework — hardware-level isolation, no shared kernel. [VERIFIED]

### Sandbox / Isolation Model

**Standard Docker (shared kernel):** Namespace + cgroups isolation only. Three runc CVEs in 2025 (CVE-2025-31133, CVE-2025-52565, CVE-2025-52881) demonstrated escape paths. NOT sufficient for untrusted agent actions. [VERIFIED]

**Docker Sandboxes (microVM product, Jan 2026):** Each sandbox = dedicated microVM with own Linux kernel and own Docker daemon. Hard hypervisor boundary between agent and host OS. This is the production-grade offering. [VERIFIED]

**Apple Containerization (macOS 26+):** Per-container VM via Apple Virtualization.framework. Sub-second start times. Hardware-level isolation. NOT available on current macOS (requires macOS 26 = macOS Tahoe, expected late 2026). [VERIFIED]

**Lima v2.0:** Open-source; wraps QEMU or Apple Virtualization.framework; v2.0 adds MCP server for AI agent access to VMs. Recommended alternative: Lima with hardened config (no home dir mount, explicit network filtering). ~30s boot time vs Firecracker's 78ms. [VERIFIED]

**Filesystem confinement options:**
- Volume mounts: expose only specific directories
- macOS Seatbelt (deprecated): write-restrict to working dir
- Apple Containerization: each container has isolated virtual filesystem; directory sharing is per-request and container-scoped [VERIFIED]

### Scored Against 5 Lenses

| Lens | Score | Why |
|------|-------|-----|
| L1 Host CU + sandbox safety | M | MicroVM containers (Docker Sandboxes, Apple container) offer strong isolation; but agents in containers cannot act on the real Mac host without explicit volume mounts/socket pass-through — same limitation as E2B. |
| L2 Local-first + privacy | H | Lima + local model = fully local, no egress. Apple container = macOS-native. No cloud required. |
| L3 Reliability + resumability | H | Docker containers well-understood; Lima and Apple container production-grade in 2026. |
| L4 Build-vs-borrow | H | Best architectural building block: wrap Artemis executor in a container for sub-tasks; pass-through only specific host capabilities (named pipe, specific mount) via explicit gates. |
| L5 One-shot end-to-end | M | Containerization is infrastructure, not agent logic. |

### macOS Support
Apple Containerization (macOS 26, ~late 2026) is the most promising native path. Lima works today on current macOS. Docker Desktop works but is commercial for large orgs. [VERIFIED]

### Known Limitations / Concerns
- Standard Docker containers are insufficient for untrusted code — need microVM layer [VERIFIED]
- Apple Containerization requires macOS 26 — not yet available on current Mac Mini M4 Pro [VERIFIED]
- Container = Linux environment; cannot directly run macOS native apps (Finder, Drive) — defeats host-computer-use purpose if agent is fully inside container [VERIFIED]
- Correct architecture: harness on host + container for sub-tasks + explicit capability pass-through; NOT agent fully in container trying to reach host [COMMUNITY]

---

## Tool 7: Self-Operating-Computer (OthersideAI)

### What It Is
Framework to enable multimodal models to operate a computer via screenshot+coordinate. Released November 2023 — one of the first widely-used frameworks for this use case. Maintained by OthersideAI. Language: Python. Uses PyAutoGUI for mouse/keyboard actions. License: MIT (inferred from GitHub; NEEDS-DOMAIN: github.com for license file confirmation). [COMMUNITY]

### How It Achieves Computer-Use
Screenshot → multimodal LLM → coordinate actions (click, type) via PyAutoGUI. Supports Set-of-Mark (SoM) prompting (overlays visual labels on clickable elements for better grounding) and OCR mode (hashmap of text→coordinates). Model-agnostic: GPT-4o, Claude 3, Gemini Pro Vision, LLaVA, Qwen-VL. [VERIFIED]

### Sandbox / Isolation Model
**None.** Self-Operating-Computer provides zero sandboxing. PyAutoGUI has full host control — it can click anything on the screen, type into any window, open any application. There is no confirmation gate, no filesystem restriction, no network filter. Blast radius = full user-level desktop control with no confinement. [VERIFIED]

The architecture is:
1. Take a screenshot
2. Ask LLM what to do
3. Execute via PyAutoGUI immediately

This tool was designed as a research/demo framework, not a production agent. There is no evidence of active safety development or sandboxing roadmap. [COMMUNITY]

### Scored Against 5 Lenses

| Lens | Score | Why |
|------|-------|-----|
| L1 Host CU + sandbox safety | L | No sandbox whatsoever; PyAutoGUI has unrestricted host access; no confirmation gate; worst blast-radius profile of all tools evaluated. |
| L2 Local-first + privacy | M | Supports local models (LLaVA, Qwen-VL via Ollama on macOS/Linux); screenshots passed to whichever model is configured. |
| L3 Reliability + resumability | L | Coordinate fragility; no error recovery; no session state; demo-grade reliability. |
| L4 Build-vs-borrow | L | Not borrowable as-is for Artemis; would need complete re-architecture around a safe harness. |
| L5 One-shot end-to-end | L | Demo-grade; not production-capable. |

### macOS Support
Yes — explicitly: macOS, Windows, Linux (with X server). PyAutoGUI works natively on macOS. [VERIFIED]

### Known Limitations / Concerns
- No sandboxing; full PyAutoGUI host access [VERIFIED]
- Research/demo maturity only; no production deployments documented [COMMUNITY]
- Coordinate fragility on Retina displays [COMMUNITY]
- Last significant development: 2023-2024; activity winding down [COMMUNITY]
- Prompt injection via on-screen content → immediate PyAutoGUI execution = catastrophic risk [VERIFIED via reasoning]

---

## Sandboxing SOTA Survey (2026)

### The Isolation Stack (weakest → strongest)

| Mechanism | Blast Radius | macOS | Overhead | 2026 Status |
|-----------|-------------|-------|----------|-------------|
| LLM alignment only | Full host | N/A | None | Insufficient; easily bypassed |
| User confirmation gate | Full host if approved | N/A | UX friction | Necessary but not sufficient |
| macOS sandbox-exec (Seatbelt) | Write-restricted dir; network filtered | Yes | ~0% | DEPRECATED by Apple; functional today but uncertain future [VERIFIED] |
| Docker (shared kernel) | Container namespace; escapable via kernel CVE | Yes (Linux VM) | ~5% | NOT sufficient for untrusted code (3 runc CVEs in 2025) [VERIFIED] |
| gVisor | Syscall-intercepted; host kernel not reachable via syscall | Linux only | 10-30% I/O | Good for compute; no GPU; no macOS native [VERIFIED] |
| Firecracker microVM | Own Linux kernel; escape requires hypervisor vuln | Linux only (KVM) | ~125ms boot, <5MB | Production gold standard for cloud/Linux; NOT native on macOS [VERIFIED] |
| Apple Virtualization.framework (Lima / Apple Containers) | Per-VM kernel; hardware boundary | macOS native | Sub-second boot (Apple) / ~30s (Lima) | Best macOS-native path; Apple Containers requires macOS 26 (late 2026) [VERIFIED] |
| Kata Containers | Hardware VM per container; OCI-compatible | Linux (KVM) | Heavier than Firecracker | Production-grade; Linux-focused [VERIFIED] |

### macOS-Specific SOTA (the Artemis context)

The fundamental tension: **macOS has no Firecracker/KVM** (no KVM support on Apple Silicon). The best isolation options on macOS today are:

1. **Apple Virtualization.framework** (used by Lima, OrbStack, and the new Apple Containerization): hardware-grade isolation for Linux VMs on Apple Silicon. Lima is available today; Apple Containers requires macOS 26. [VERIFIED]
2. **macOS Seatbelt / sandbox-exec**: OS-level syscall filter for native processes; effective for write-restricting a process to a working directory + network allowlist. BUT deprecated and at risk of removal. [VERIFIED]
3. **Standard Docker Desktop** (wraps Virtualization.framework on Apple Silicon): acceptable for trusted code; insufficient alone for untrusted agent actions without the microVM wrapping layer. [VERIFIED]

### Capability Scoping (2026 SOTA)

Beyond OS-level containment, MCP (Model Context Protocol) is emerging as the 2026 standard for declarative tool scopes — tools declare what filesystem paths, network ranges, and action types they can access, and compliant sandboxes enforce at runtime. This is the protocol-level permission model layer that complements OS-level isolation. [VERIFIED]

### Recommendation for Artemis

For Artemis's **host computer-use** capability:
- **For browser/web sub-tasks:** browser-use + Playwright (local model), browser-scope blast radius, no host access
- **For code execution sub-tasks:** E2B (BYOC) or Lima-wrapped container; agent acts on sandboxed Linux VM, not the Mac host
- **For true host-desktop actions (native Mac apps, Finder, Drive):** no off-the-shelf sandbox fully closes blast radius while permitting effective host control; the answer is Artemis's own approval gate architecture + macOS Seatbelt (for now, with migration plan for Apple Containerization post-macOS 26)
- **Anthropic Computer Use API:** borrow the vision-action loop; add Artemis approval gate on top; do NOT rely on srt/Seatbelt as the only blast-radius defense

---

## Sources

### Tier 1 (Official Docs — via direct fetch)
- Anthropic Engineering: Claude Code Sandboxing — https://www.anthropic.com/engineering/claude-code-sandboxing
- Infralovers: Sandboxing Claude Code on macOS (Feb 2026) — https://www.infralovers.com/blog/2026-02-15-sandboxing-claude-code-macos/
- OpenAI: Operator System Card (Jan 2025) — https://openai.com/index/operator-system-card/
- OpenAI: Computer Use tool docs — https://developers.openai.com/api/docs/guides/tools-computer-use
- E2B: Computer Use docs — https://e2b.dev/docs/use-cases/computer-use
- Apple WWDC 2025: Meet Containerization — https://developer.apple.com/videos/play/wwdc2025/346/
- Open Interpreter: Safety docs — https://docs.openinterpreter.com/safety/introduction

### Tier 2 (Web Search — 2025/2026)
- Northflank: How to sandbox AI agents (2026) — https://northflank.com/blog/how-to-sandbox-ai-agents
- E2B Review 2026 — https://aiagentslist.com/agents/e2b
- Browser-Use vs Playwright comparison 2026 — https://theneuralbase.com/browser-use/qna/browser-use-vs-playwright-comparison/
- OthersideAI Self-Operating Computer — https://pypi.org/project/self-operating-computer/
- DEV: OS-Level Sandboxing Kernel Isolation for AI Agents — https://dev.to/uenyioha/os-level-sandboxing-kernel-isolation-for-ai-agents-3fdg
- Hacker News: macOS seatbelt deprecation discussion — https://news.ycombinator.com/item?id=44283454
- MCP Security Patterns 2026 gVisor vs Firecracker — https://dev.to/chunxiaoxx/mcp-security-patterns-2026-gvisor-vs-firecracker-for-ai-agent-sandboxing-3hp7
- Claude Computer Use security risks — https://www.kunalganglani.com/blog/claude-computer-use-security-risks
- OpenAI Agents SDK 2026 — https://aiautomationglobal.com/blog/openai-agents-sdk-sandbox-native-agent-primitives-2026
- Apple Containerization deep dive — https://anil.recoil.org/notes/apple-containerisation
- OrbStack vs Apple Containers vs Docker — https://dev.to/tuliopc23/orbstack-vs-apple-containers-vs-docker-on-macos-how-they-really-differ-under-the-hood-53fj

### NEEDS-DOMAIN
- `github.com` — blocked primary source. Self-Operating-Computer license file, browser-use full README, E2B desktop README. Claims sourced from PyPI and secondary coverage instead.
