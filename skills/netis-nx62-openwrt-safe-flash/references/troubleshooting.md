# Troubleshooting

Rule zero: when something unexpected happens, **stop, do not power-cycle, and
report the exact output**. Most problems are fixable; panicked retries are what
turn them into bricks.

## Before any write

| Symptom | Cause | Fix |
|---|---|---|
| `INSPECT_RESULT=MISMATCH` | Different board/firmware layout, or not an NX62/N60 Pro | **Stop.** Do not flash. Post the `/proc/mtd` output to the OpenWrt forum thread. |
| `IMAGES_VERIFY=FAIL` | Corrupt download, wrong release, or wrong device (e.g. `netcore_n60` without `-pro`) | Re-download from downloads.openwrt.org for the chosen release. |
| `BACKUP_RESULT=FAIL` on one partition | Flaky SSH or NAND read error | Re-run into a **new** directory. If the same partition fails repeatedly, stop. |
| Whole-chip slice mismatch warning | NAND bad block handling or unexpected layout | Investigate before flashing; the per-partition dumps are what you restore from. |
| SSH: `no matching host key type` | Old Dropbear on stock | Add `-o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa` |
| SSH: `REMOTE HOST IDENTIFICATION HAS CHANGED` | Expected between stock / recovery / OpenWrt | The scripts use separate known_hosts files per phase in `~/nx62-flash/`. For manual ssh: `ssh-keygen -R 192.168.1.1`. |
| `scp` fails against Dropbear | No SFTP server on the router | Use `scp -O` (the scripts do). |
| Lost internet on the host | Gateway set on the wired interface, or it took DHCP | Remove the gateway; see host-setup.md. |

## After `mtd write ... FIP`

- **Readback mismatch:** do **not** reboot. The stock system is still running.
  Retry the write, or restore the stock FIP from your backup
  (`mtd write /tmp/mtd4_FIP.bin FIP` after uploading and hash-checking it).
- **`mtd: ... read-only`:** you are not on stock firmware, or the stock build
  locks FIP. Stop; this skill does not unlock partitions.

## After `mtd erase ubi` + reboot

- **Link flaps every ~30 s, no TFTP RRQ in the capture:** wrong port. Move the
  cable to another 1G LAN port (LAN4 is the field-reported good one; avoid the
  2.5G ports). See recovery-uboot-tftp.md.
- **RRQ seen, transfer stalls / repeats:** server not honoring blksize 1468,
  firewall dropping UDP, or wrong filename. Re-run `tftp-selftest.sh`.
- **Nothing at all on the wire:** wrong interface in the capture, cable in WAN,
  or `192.168.1.254` on the wrong interface.
- **No PHY link at all, ever:** FIP or BL2 problem. Stop. This needs UART.
  Do not keep power-cycling.

## In recovery

- Recovery SSH: `root`, no password, new host key.
- `sysupgrade -T` rejects the image: wrong image (check you used
  `...-squashfs-sysupgrade.itb` for `netcore_n60-pro`). Do not force it.
- SSH drops during `sysupgrade -n`: expected. Wait 3 minutes before judging.

## After sysupgrade

- Boots back into recovery (RAM root, no overlay): the `fit` volume was not
  written. Re-run step 14.
- Wi-Fi missing or MACs look random: factory calibration not read. Compare
  `/sys/class/net/*/address` with the MACs `verify-backup.sh` printed.
  **Never** "fix" this by writing the factory partition.
