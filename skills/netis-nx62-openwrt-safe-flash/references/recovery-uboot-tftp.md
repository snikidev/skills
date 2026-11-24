# Recovery via the OpenWrt U-Boot TFTP path

Facts below are from OpenWrt's U-Boot patch for this board:
`package/boot/uboot-mediatek/patches/462-add-netcore-n60-pro.patch`
(default environment `defenvs/netcore_n60-pro_env`).

## The numbers U-Boot uses

| Setting | Value |
|---|---|
| Router IP (`ipaddr`) | `192.168.1.1` |
| TFTP server it asks (`serverip`) | `192.168.1.254` |
| Recovery file (`bootfile`) | `openwrt-mediatek-filogic-netcore_n60-pro-initramfs-recovery.itb` |
| Sysupgrade file (`bootfile_upg`) | `openwrt-mediatek-filogic-netcore_n60-pro-squashfs-sysupgrade.itb` |
| FIP file (`bootfile_fip`) | `openwrt-mediatek-filogic-netcore_n60-pro-bl31-uboot.fip` |
| BL2 file (`bootfile_bl2`) | `openwrt-mediatek-filogic-netcore_n60-pro-preloader.bin` |
| Load address | `0x46000000` |
| Ethernet in U-Boot | gmac0 → MT7531 switch (1G LAN ports) |

Note the TFTP names have **no version number**. Rename (copy) the verified
versioned file to that exact name in the TFTP root.

## How it ends up asking for TFTP

`boot_ubi` tries the production system in UBI, then a recovery volume, then
falls through to `boot_tftp_forever`: an endless loop of
`tftpboot $loadaddr $bootfile` and boot. So with an empty/erased `ubi`, or a
broken install, the router keeps requesting the recovery file from
192.168.1.254. The wired link going up and down every ~30 s is that loop
restarting.

**While BL2 and FIP are intact, an empty or broken UBI is not a brick.** You can
retry as often as needed.

## Which port

U-Boot only drives the MT7531 switch. In OpenWrt's DTS, `lan1` is the 2.5G port
on a separate PHY and WAN is on the second GMAC, so neither is expected to work
in U-Boot. Use one of the **1G LAN ports** (field reports: LAN4 works when LAN1
did not). This is inferred from the DTS; physical port labels on the case can
differ, so trust the packet capture, not the label.

## Reset button

On the very first boot of the OpenWrt U-Boot (default environment) it runs
`_firstboot` → `boot_first`, which starts TFTP recovery if the reset button is
held. After the environment is saved, later boots go straight to the default
boot command (which still falls back to TFTP when nothing bootable is found).
The "hold reset ~10 s while powering on" trick is therefore only confirmed for
the first boot. Treat it as best-effort later.

## Serial console (the real safety net)

UART is 115200 8N1 (`stdout-path = "serial0:115200n8"`). With a 3.3 V USB-UART
adapter you get the U-Boot boot menu, which can TFTP-boot recovery, write the
sysupgrade image to NAND, or rewrite FIP. Pin location is not documented here;
check the OpenWrt wiki device page before opening the case. Never use a 5 V
adapter.

## What still works after each step

| State | Recoverable by | Notes |
|---|---|---|
| Stock, FIP written, not rebooted | Rewrite stock FIP from backup (`mtd write <backup>/mtd4_FIP.bin FIP`) | Fully reversible |
| ubi erased, rebooted | TFTP recovery (automatic) | Normal, expected |
| Recovery booted, sysupgrade failed | TFTP recovery again | Re-run step 14 |
| Final OpenWrt broken | OpenWrt failsafe, or TFTP recovery | |
| FIP corrupted | UART + BootROM / vendor tools | Hard; why FIP readback is verified before reboot |
| BL2 corrupted | UART + MediaTek BootROM download tools | Hardest; this skill never writes BL2 |

## Going back to stock (not tested here)

You have the full backup. The theoretical route is: from OpenWrt recovery,
restore the stock `ubi` and then the stock FIP using `mtd write` with the
partitions read-write. This has **not** been verified on hardware: raw NAND
dumps of UBI can misbehave if the flash has gained bad blocks, and FIP is
read-only in OpenWrt (needs `kmod-mtd-rw`). Get help (OpenWrt forum thread for
the N60 Pro) and preferably a UART adapter before attempting it. This skill
does not automate it.
