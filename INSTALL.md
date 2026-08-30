---
name: INSTALL
description: fpm install guide — cdf/sshf shell functions, hub server, update path, optional fbot/MCP components, air-gapped install
date: 2026.08.26
---

> 🌐 **English** | [한국어](INSTALL_ko.md)

# Supported platforms

| OS | Status | Shell | Notes |
| :--- | :--- | :--- | :--- |
| **macOS** | ✅ reference | zsh | Full feature set incl. iTerm2 split / Finder / clipboard |
| **Linux** | ✅ verified | bash·zsh | `cdf`/`sshf` fall back to plain `cd`/`ssh`; hub·SCAR·MCP identical |
| **Windows 11** | 🚧 in progress | **Git Bash** | See [below](#windows-11-git-bash). Some items are unverified |

**Post-install verification is the same everywhere:**

```bash
bash tdd/run-tdd.sh      # does it actually work on this machine (core + platform + deploy)
bash sh/check.sh         # is it installed correctly
```

⚠️ The two differ in purpose — `check.sh` asks *is it installed*, `tdd` asks *does it run on this OS*.
The three portability traps found on 2026-08-30 (nvm PATH, BSD `date`, hardcoded home path)
were caught by **none** of `check.sh`'s checks.

# Requirements

## Required — missing these makes the install silently incomplete

| Item | Minimum | Why required |
| :--- | :--- | :--- |
| **Claude Code** | installed & signed in | `install.sh` steps 6–7 call `claude plugin` / `claude mcp` to wire SCAR and MCP servers. **Without it the install "succeeds" while all SCAR is missing** |
| **bash** | 4.x+ | Execution shell for every script (Git Bash on Windows) |
| **git** | 2.x+ | The whole delivery chain sits on git |
| **python3** | 3.9+ | hub server, hooks, builders |
| **jq** | 1.6+ | Atomic updates of the aoa-mq queue — without it reminders fail to update silently |

⚠️ **If Claude Code was installed via nvm**, `which claude` may fail inside hooks/cron
(nvm fills PATH from shell init). `bash tdd/run-tdd.sh` checks this as `claude-cli-available`.

## Optional — only the matching feature is affected

* zsh — bash works too (`install.sh` picks the rc from `$SHELL`)
* iTerm2 — multi-pane split for `cdf`/`sshf` (macOS only); otherwise plain `cd`/`ssh`
* VS Code + `code` CLI — `cdfv`
* Node.js 18+ / `npx` — `/fpm-issue-map` diagram rendering. Affects **that command only**
* (optional) iTerm2 — multi-pane split
* (optional) VS Code + `code` CLI — `cdfv`
* (optional) Python 3 — hub server
* (optional) Node.js + `npx` — diagram rendering for `/fpm-issue-map`. Without it only that command is unavailable (everything else is unaffected)
* (optional) mermaid-cli (`mmdc`) installed globally — used first when present, so rendering starts instantly and works offline. `npm i -g @mermaid-js/mermaid-cli`
* (optional) Keyboard Maestro (paid) — macro integration

# Quick Install

```bash
git clone https://github.com/<you>/fpm.git ~/_git/fpm
cd ~/_git/fpm
bash sh/install.sh
source ~/.zshrc
```

What `sh/install.sh` does:

1. Adds an `FPM_BASE` export + a `sh/fpm.sh` bootstrap source line to `~/.zshrc` (marker-guarded — idempotent)
2. Creates `~/.info/__pmBasePath.txt` → `<repo>/projects`
3. Creates the `projects/` scaffold (`0`=home, `1`=repo)
4. Copies the `*_org.md` examples if `Servers.md`/`Projects.md` are missing
5. Prints hub server / KM guidance
6. Installs the `fpm-core` plugin (SCAR — hub/dashboard, etc.) via the `f-claude-plugins` marketplace (ON by default; skip with `--no-scar`)

# Air-gapped Install

In environments without internet access, `sh/install.sh` cannot reach the GitHub marketplace (`f-claude-plugins`) it uses by default. In that case, download the marketplace repository ahead of time on an internet-connected machine, move it to the air-gapped machine, and point the installer at the local copy as the marketplace source with the `--local` parameter.

```bash
# 1) On an internet-connected machine, clone the marketplace repository
git clone https://github.com/finfra/f-claude-plugins ~/_git/__all/f-claude-plugins

# 2) Copy the f-claude-plugins directory to the air-gapped machine (USB, internal network, etc.)

# 3) On the air-gapped machine, install with the local copy as the marketplace source
bash sh/install.sh --local /path/to/f-claude-plugins
```

* If you omit the path (`bash sh/install.sh --local`), it auto-discovers conventional locations (`~/_git/__all/f-claude-plugins`, `<repo>/../f-claude-plugins`, `./f-claude-plugins`).
* If the given path has no `marketplace.json` (or `.claude-plugin/marketplace.json`), the install aborts and prints guidance.
* `--local` takes precedence over the `FPM_MKT_REF` environment variable. If SCAR is not needed, you can install only the shell bootstrap with `--no-scar`.

# Post-install Setup

## 1. Project Mapping (cdf)

Edit the `setting Script` block in `Projects.md` with your own paths and run it, or write a path per line into the `projects/<number>` files:

```bash
echo "~/_git/myproj-web" > ~/_git/fpm/projects/11
```

```bash
cdf            # full list
cdf 11         # cd to the projects/11 path
cdf 11 12 13   # cd to the first, split the rest into iTerm2
cdff 11        # Finder
cdfc 11        # copy to clipboard
cdfv 11 12     # VS Code
```

## 2. Server Mapping (sshf)

Edit the table in `Servers.md`, and define Host aliases in the `# favorite` section of `~/.ssh/config`:

```sshconfig
# favorite
Host sg
    HostName host3.example.com
    Port 9922
    User youruser
```

```bash
sshf           # server list
sshf 3         # connect to the server with id=3
sshf gpu1      # connect by Name
sshf 1 2 3     # multiple → iTerm2 split
```

## 3. hub Server (optional)

HTML rendering + multi-project dashboard:

```bash
cd ~/_git/fpm/services/hub
python3 server.py
# → http://127.0.0.1:9876/hub
```

The memo box at the top of `/projects-map` is editable right in the browser (online editing) and auto-saves to `_note.md` in the project root (gitignored — never committed). On a fresh install the file does not exist yet: a placeholder message is shown, and the file is created on your first edit.

# Windows 11 (Git Bash)

> 🚧 **Partly unverified.** Design rationale: [`_doc_arch/windows-port-design.md`](_doc_arch/windows-port-design.md).
> After installing, `bash tdd/run-tdd.sh` runs the 8 `windows` cases and tells you what works.

## Why Git Bash rather than WSL2

What matters is **where Claude Code lives**. `sh/install.sh` invokes the `claude` CLI to wire up
the plugin and MCP servers, so fpm must sit on the **same filesystem as Claude Code**.

* Claude Code installed **natively on Windows** → **Git Bash** (default recommendation)
* Claude Code installed **inside WSL** → install there and follow the Linux instructions

Installing fpm in WSL while Claude Code runs on Windows makes the install *appear* to succeed
while hooks and MCP servers **never see that Claude** — it fails silently.

## 1) Prerequisites

```bash
# Update

Already installed and want the latest? fpm reaches your machine in **two layers**, and updating only one leaves you half-stale (`cdf` current but hub/hooks old, or the reverse). `sh/update.sh` does both in one shot:

```bash
cd ~/_git/fpm
bash sh/update.sh
```

| Layer | Where it lives | Source | What `update.sh` runs |
| :--- | :--- | :--- | :--- |
| **Shell** (`cdf`/`sshf`/hub) | `~/_git/fpm` (`$FPM_BASE`) | this repo | `git pull --ff-only` |
| **SCAR** (hooks/commands/agents/skills) | Claude Code plugin dir | `f-claude-plugins` marketplace | `claude plugin marketplace update` + `claude plugin update fpm-core@f-claude-plugins` |

```bash
bash sh/update.sh --shell-only   # git pull only
bash sh/update.sh --scar-only    # plugin only
```

* **Restart Claude Code** after a SCAR update — the plugin is loaded at startup.
* `claude` CLI not on `PATH`? The SCAR half is skipped with a warning (this is normal for shell-only users). Over non-interactive SSH prepend `export PATH="$HOME/.local/bin:$PATH"`.
* `git pull --ff-only` fails → your history diverged (this happens when the version scheme is reset). Back up `Projects.md`/`Servers.md`, re-clone, then `bash sh/install.sh --clean`.
* Re-running `bash sh/install.sh` is idempotent and also updates the plugin, so it works as an update path too. `sh/update.sh` is the narrower, faster one.

# Optional Components (fbot / MCP)

The repo also ships pieces that `sh/install.sh` does **not** wire up for you. They are inert until you configure them — a default install is unaffected if you skip this section.

| Component | Shipped at | Status |
| :--- | :--- | :--- |
| fpm MCP server | `mcp/server.py` | Register manually — see [mcp/README.md](mcp/README.md) |
| `aoa-mq` / `aoa-memory` MCP servers | `mcp/aoa-mq/`, `mcp/aoa-memory/` | Register manually (`claude mcp add`) |
| fbot hooks + role manuals | `plugins/fpm-core/hooks/fbot-*`, `plugins/fpm-core/data/fbot/` | Installed with the plugin, but **not self-contained** — see below |

⚠️ **The fbot hooks are not portable yet.** They resolve their datastore and MCP source from `~/_git/___common/…`, a path that no fpm install creates, and `fbot-tick.sh` defaults its interpreter to `/opt/homebrew/bin/python3` (macOS Homebrew only — absent on Linux). Point `AOA_MEMORY_DIR`, `AOA_MQ_DIR` and `FBOT_PYTHON` at real locations before enabling them, or leave fbot off. Tracked as a known limitation.

# Uninstall / Clean Reinstall

`sh/uninstall.sh` backs up the install traces and then removes them (idempotent):

```bash
bash sh/uninstall.sh
```

What gets removed:

1. The fpm block in `~/.zshrc` / `~/.bashrc` (`# >>> fpm functions >>>` ~ `# <<<`)
2. `~/.info/__pmBasePath.txt`

Backup location: `<repo>/_doc_work/z_done/fpm-uninstall-<datetime>/` (changeable via the `FPM_BACKUP_DIR` environment variable). User data such as `projects/`, `Projects.md`, and `Servers.md` is **preserved**; delete it manually after reviewing the backup if needed.

Clean reinstall (backup, remove, then reinstall) in one shot:

```bash
bash sh/install.sh --clean
```
