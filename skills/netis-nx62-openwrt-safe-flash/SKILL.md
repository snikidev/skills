---
name: netis-nx62-openwrt-safe-flash
description: >-
  Extra-safe, strictly step-by-step guide for installing OpenWrt on a Netis NX62
  (same board as the Netcore N60 Pro, MediaTek MT7986A, OpenWrt id
  netcore_n60-pro) from stock firmware using the upstream FIP + TFTP recovery
  method. Stops after every step with a progress list and waits for the user;
  verifies the full MTD backup (especially factory/Wi-Fi calibration) three
  times, including by the user; never writes BL2, factory or u-boot-env; every
  flash write is dry-run by default and needs a phrase typed by the user in
  their own terminal. Use when someone wants OpenWrt on a Netis NX62 / Netcore
  N60 Pro, or is mid-flash and stuck (no TFTP request, link flapping, backup
  doubts). Do not use for other routers, including the non-Pro Netcore N60.
---

# Netis NX62 / Netcore N60 Pro → OpenWrt, the careful way

You are a co-pilot, not the pilot. The user owns every decision. Flashing a
router wrong can brick it permanently, and the factory partition (Wi-Fi
calibration + MACs) cannot be downloaded again if it is lost.

## Non-negotiable rules

1. **One step at a time.** Never combine steps, never run ahead, never "save
   time" by batching commands.
2. **Step card + STOP at every step.** Use the exact format in "Step protocol"
   below, then stop and wait. Continue only on an explicit go-ahead for *that*
   step ("go", "yes, step 6", "continue"). Silence, "ok?" or a question is not
   a go-ahead.
3. **Update after every step.** After the user (or a script) finishes a step,
   report what happened, show the evidence (the PASS/FAIL lines), run
   `scripts/steps.sh done <N>`, and print the refreshed progress list.
4. **Any FAIL, MISMATCH, error or surprise = stop.** Explain it, point to
   `references/troubleshooting.md`, and do not suggest workarounds that skip a
   check. Never edit a script to make a check pass.
5. **Destructive commands are typed by the user.** Only `scripts/flash-step.sh
   ... --execute` changes the router, and it requires a phrase typed in an
   interactive terminal. Never run it yourself, never pipe or fake the phrase,
   never hand the user raw `mtd write` / `mtd erase` / `ubiformat` commands
   instead. You may run read-only scripts (inspect, backup, verify, preflight,
   dry runs) when the user agrees.
6. **Never write `bl2`/preloader, `factory`, `u-boot-env`/`orig-env`, or a
   whole-chip dump**, and never format UBI by number. The upstream OpenWrt
   method does not need any of that. If the user asks, explain why not (see
   `references/comparison-notes.md`) and decline.
7. **No secrets.** `sudo` prompts interactively. Never put a password in a
   command, script, file or chat. If the user pastes one, do not repeat or store it.
8. **Wired only, stable power.** Router and computer on mains (laptop plugged
   in), no extension leads that get kicked, no thunderstorms, no "while I'm on
   a call". Never over Wi-Fi, never remotely.

## Step protocol (print this at every step)

```
━━ STEP <N>/<15>: <title> ━━
What it does:   <one or two plain sentences>
Risk:           <none / read-only / reversible / POINT OF NO RETURN>
You will run:   <exact command(s), or "nothing - I run read-only checks">
Success looks like: <the PASS line / observable result>
If it fails:    <what we do: stop and look at X>

Progress:
<output of scripts/steps.sh list>

⏸ Waiting for you. Reply "go" to start step <N>, or ask anything.
```

After the step:

```
✅/❌ STEP <N> result: <PASS/FAIL + key evidence lines>
<what this means in one sentence>
<scripts/steps.sh done N output, i.e. the updated list>
Next up: STEP <N+1>: <title>. ⏸ Say "go" when ready.
```

Setup once: `export NX62_WORK="$HOME/nx62-flash"` (state, markers, known_hosts
live there). Optional: `NX62_SSH_KEY=~/.ssh/nx62_key` to avoid password prompts.
Scripts are in this skill's `scripts/` folder; host scripts are POSIX sh
(macOS, Linux, WSL). `router-inspect.sh` runs on the router via `ssh ... 'sh -s' <`.

## The steps

### Step 0 — Orientation and consent (risk: none)
Explain in plain words: what will change (bootloader FIP, then the whole
firmware), what never changes (BL2, factory), the one point of no return
(step 12), that while BL2 + FIP are intact a failed install is recoverable via
TFTP, and that a USB-UART adapter (3.3 V) is the only rescue for deeper
damage. Ask: do they have 60–90 undisturbed minutes, a wired computer, the
router's power supply? Get an explicit "I understand the risk, go".

### Step 1 — Identify the device and release (risk: none)
User reads the label: must say **Netis NX62** (V1) or **Netcore N60 Pro**. Not
N60 (non-Pro), not NX30/NX31/NX32. Pick the release from
https://downloads.openwrt.org/ (`.versions.json` → `stable_version`; 25.12.x or
newer has `netcore_n60-pro`; 24.10 does not). Write the version down; it is
passed explicitly to every script.

### Step 2 — Download and verify images (risk: none)
Download into one absolute folder from
`https://downloads.openwrt.org/releases/<VER>/targets/mediatek/filogic/`:
`...-netcore_n60-pro-bl31-uboot.fip`, `...-initramfs-recovery.itb`,
`...-squashfs-sysupgrade.itb`. Do not download "factory" images from anywhere
else. Then:
`scripts/verify-images.sh --dir /ABS/dir --version <VER> --fetch` →
`IMAGES_VERIFY=PASS` required. Read the three "Use:" paths back to the user.

### Step 3 — Host network (risk: none to the router)
Per `references/host-setup.md`: wired `192.168.1.254/24`, **no gateway**,
cable from the computer to a **1G LAN port** (not WAN, not the 2.5G LAN1).
Confirm internet still works over Wi-Fi.

### Step 4 — SSH into stock and inspect (risk: read-only)
`ssh useradmin@192.168.1.1` (web-panel password; reset + wizard if forgotten).
Then `ssh useradmin@192.168.1.1 'sh -s' < scripts/router-inspect.sh`.
Need `INSPECT_RESULT=OK` (bl2 1M, u-boot-env 512K, factory 2M, fip 2M, ubi
122.5M by name). Any MISMATCH → stop for good; this is not the expected board.

### Step 5 — Full MTD backup (risk: read-only)
`scripts/backup-mtd.sh --router useradmin@192.168.1.1 --out /ABS/nx62-backup-<date>`
→ `BACKUP_RESULT=PASS`. State the absolute path out loud. It dumps every
partition including the whole chip, checks size vs `/proc/mtd`, compares
router-side and host-side hashes, writes SHA256SUMS.

### Step 6 — Backup check #1 (risk: none)
`scripts/verify-backup.sh /ABS/nx62-backup-<date>` → `BACKUP_VERIFY=PASS`.
Read out: the absolute path, the factory/bl2/fip/whole-chip filenames and
sizes, and the factory MACs. Ask the user to compare the MACs with the router
label (they are often off by one; wildly different or all `ff` is a red flag).

### Step 7 — Backup check #2: second copy (risk: none)
User copies the whole folder to a second place that survives this computer
(USB drive, another machine, cloud folder). Then
`scripts/verify-backup.sh /ABS/primary /ABS/second-copy` → both PASS,
SHA256SUMS identical, ideally "different filesystems". A same-filesystem
warning means it is not really a second copy: ask them to fix it.

### Step 8 — Backup check #3: the user checks (risk: none)
Say clearly: "Before anything is written, please look yourself." Print both
absolute paths and the file list. Then the user runs, in their own terminal,
`scripts/verify-backup.sh --user-confirm /ABS/primary /ABS/second-copy` and
types `BACKUPS CHECKED`. Do not continue until it records the confirmation.

### Step 9 — Recovery plan, power, TFTP self-test (risk: none)
Walk through `references/recovery-uboot-tftp.md` with the user: what happens
after step 12, what the capture should show, which port, what to do if nothing
comes. Confirm power is stable. Set up the TFTP server (host-setup.md) and run
`scripts/tftp-selftest.sh --image /ABS/...-initramfs-recovery.itb` →
`TFTP_SELFTEST=PASS`. Have the packet-capture command ready in a second window.

### Step 10 — Preflight (risk: read-only)
`scripts/preflight.sh --router useradmin@192.168.1.1` → `PREFLIGHT=PASS`
(host IP, no gateway on the router link, ping, SSH, layout, /tmp space, all
earlier markers, backups still at their paths). Then dry runs:
`scripts/flash-step.sh fip --router useradmin@192.168.1.1 --image /ABS/...fip`
and `scripts/flash-step.sh erase-ubi --router useradmin@192.168.1.1`.
Read the "Would run" lines back to the user.

### Step 11 — Write FIP (risk: reversible until reboot)
User runs in their terminal:
`scripts/flash-step.sh fip --router useradmin@192.168.1.1 --image /ABS/...fip --execute`
It re-verifies the image, uploads, compares hashes, asks for `WRITE FIP`,
writes, reads back. Need `FIP_WRITE=PASS`. On readback mismatch: **do not
reboot**; restore FIP from backup (troubleshooting.md).

### Step 12 — Erase ubi + reboot (risk: POINT OF NO RETURN)
Re-state: after this, stock firmware is gone; recovery comes over TFTP. TFTP
server running, capture running. User runs
`scripts/flash-step.sh erase-ubi --router useradmin@192.168.1.1 --execute`,
types `ERASE UBI`, then `REBOOT`.

### Step 13 — Confirm recovery loaded (risk: none)
Capture must show the router's ARP for 192.168.1.254 and
`RRQ "openwrt-mediatek-filogic-netcore_n60-pro-initramfs-recovery.itb"`, then
data. Within ~1–2 min `ssh root@192.168.1.1` (no password) works and
`ssh root@192.168.1.1 'sh -s' < scripts/router-inspect.sh` shows
`compatible: netcore,n60-pro` and `INSPECT_RESULT=OK`. Link flapping every
~30 s with no RRQ → move the cable to another 1G LAN port. Do not continue
without a recovery shell.

### Step 14 — Sysupgrade (risk: writes UBI only)
Dry run first, then the user runs
`scripts/flash-step.sh sysupgrade --router root@192.168.1.1 --image /ABS/...-squashfs-sysupgrade.itb --execute`.
It confirms it is talking to the RAM recovery of a `netcore,n60-pro`, uploads,
compares hashes, runs `sysupgrade -T`, asks for `SYSUPGRADE`, runs
`sysupgrade -n`. The SSH drop is expected; wait 3 minutes.

### Step 15 — Verify and tidy up (risk: none)
`ssh root@192.168.1.1 'cat /etc/openwrt_release; mount | grep -E "overlay|/rom"; ip link'`:
want the release you chose, `/rom` squashfs and an `overlay` from UBI (not
tmpfs). Compare MACs with step 6. Set a root password (`passwd` or LuCI at
http://192.168.1.1). Undo the host static IP and stop TFTP. Remind the user to
keep both backup copies forever.

## References

- `references/partition-map.md` — layout, sizes, offsets, names on stock vs OpenWrt, why factory matters
- `references/recovery-uboot-tftp.md` — U-Boot TFTP facts from OpenWrt source, ports, reset button, UART, what is recoverable when
- `references/host-setup.md` — macOS / Linux / Windows static IP, TFTP, capture
- `references/troubleshooting.md` — symptom → cause → fix, before and after each write
- `references/comparison-notes.md` — how this differs from brat-kuzma's skill and our earlier guide, and why

## Scripts

| Script | Changes anything? | Purpose |
|---|---|---|
| `scripts/steps.sh` | local state only | progress: done / current / remaining; no skipping |
| `scripts/verify-images.sh` | no (downloads checksum files with `--fetch`) | sha256 vs official sums + profiles.json, file type, right device |
| `scripts/router-inspect.sh` | no (runs on router) | identity, tools, `/proc/mtd`, size check by name |
| `scripts/backup-mtd.sh` | no | stream every partition, size + router/host hash check |
| `scripts/verify-backup.sh` | no (writes markers) | checks #1–#3, second-copy compare, factory sanity, MACs |
| `scripts/tftp-selftest.sh` | no | proves the TFTP server serves the exact file and name |
| `scripts/preflight.sh` | no | go/no-go before writes |
| `scripts/flash-step.sh` | **yes, only with `--execute` + typed phrase** | FIP write, ubi erase + reboot, sysupgrade; refuses bl2/factory/env |
