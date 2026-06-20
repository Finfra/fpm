---
name: INSTALL
description: fpm install guide — cdf/sshf shell functions, hub server, Keyboard Maestro, air-gapped install
date: 2026-06-21
---

> 🌐 **English** | [한국어](INSTALL_ko.md)

# Requirements

* macOS (for the iTerm2 split / Finder / clipboard features of cdf/sshf). On Linux only plain `cd`/`ssh` works
* zsh
* (optional) iTerm2 — multi-pane split
* (optional) VS Code + `code` CLI — `cdfv`
* (optional) Python 3 — hub server
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

## 4. Keyboard Maestro (optional)

See `keyboard-maestro/README.md` — `.kmmacros` import + Accessibility permission.

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
