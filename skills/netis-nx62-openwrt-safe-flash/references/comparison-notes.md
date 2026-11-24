# Comparison: brat-kuzma skill vs our earlier guide vs upstream OpenWrt

Sources compared (read 2026-11-24):

- **A** — [brat-kuzma/netis-nx62-openwrt-skill](https://github.com/brat-kuzma/netis-nx62-openwrt-skill) (MIT), commit `f046663`.
- **B** — our earlier Page "Netis NX62: OpenWrt + VLESS Router Setup" (task DEV-2, Nov 22 2026), built largely on A and
  [SevenMaxs/netis-nx62-flash-tools](https://github.com/SevenMaxs/netis-nx62-flash-tools).
- **U** — upstream OpenWrt: the device commit `db3eff1022` ("mediatek: filogic: add Netcore N60 Pro support", PR #18138),
  `mt7986a-netcore-n60-pro.dts`, `filogic.mk`, U-Boot patch `462-add-netcore-n60-pro.patch`,
  and the 25.12.6 `sha256sums` / `profiles.json`. The openwrt.org wiki page sits behind a bot challenge and could not be read.

## Where they agree (and U confirms)

| Fact | A | B | U |
|---|---|---|---|
| Device id `netcore_n60-pro`, target `mediatek/filogic`, MT7986A, 512 MB, 128 MB SPI-NAND | yes | yes | yes |
| Router `192.168.1.1`, TFTP server `192.168.1.254` | yes | yes | yes (`ipaddr`/`serverip`) |
| TFTP filename `openwrt-mediatek-filogic-netcore_n60-pro-initramfs-recovery.itb` | yes | yes | yes (`bootfile`) |
| Image names `-bl31-uboot.fip`, `-initramfs-recovery.itb`, `-squashfs-sysupgrade.itb`, `-preloader.bin` | yes | yes | yes |
| 25.12.6 sha256 values in B | – | yes | **match** official `sha256sums` |
| Stock SSH login `useradmin` + web password | yes | yes | yes |
| Stock: `mtd write <fip> FIP`, then `mtd erase ubi`, reboot, TFTP recovery | yes | yes | yes |
| Back up all MTD partitions first | yes | yes | yes ("Back up all mtd partitions before flashing") |
| OpenWrt partition order bl2 / u-boot-env / factory / fip / ubi | yes | yes | yes, with sizes 1M / 512K / 2M / 2M / 122.5M |

## Where they disagree or carry risk

1. **Writing BL2 (preloader) — the biggest one.** A and B both make writing the
   OpenWrt BL2 a mandatory step, done from recovery with `kmod-mtd-rw` and
   `insmod mtd-rw i_want_a_brick=1`. **U's own flash instructions never write
   BL2**: FIP, erase ubi, TFTP recovery, sysupgrade. The stock BL2 loads the
   OpenWrt FIP. In OpenWrt's DTS `bl2` is marked read-only on purpose. A
   corrupted BL2 is the one failure that needs UART/BootROM tools. **New skill:
   never writes BL2; refuses it outright.**
2. **Manual `ubiformat` + `ubimkvol` by partition number.** A and B run
   `ubidetach/ubiformat -y /dev/mtd4` and create `ubootenv`/`ubootenv2` with
   `-S 2` by hand. U does not: the OpenWrt U-Boot creates its env volumes
   itself (`ubi_create_env`, 1 MiB each, not the 2-LEB volumes A/B create), and
   `sysupgrade` (`fit_do_upgrade`) writes the `fit` volume. Hard-coding
   `/dev/mtd4` in a destructive command is exactly the kind of number that is
   different on stock (where mtd4 is FIP). B even added `|| true` after
   `ubidetach`, hiding errors. **New skill: no ubiformat at all; `sysupgrade -T`
   first, then `sysupgrade -n`.**
3. **Hard-coded mtd numbers in readback.** B verifies the FIP write with
   `dd if=/dev/mtd4` and BL2 with `dd if=/dev/mtd0` (with a comment to change
   it). **New skill: resolves the device from the name in live `/proc/mtd`.**
4. **Backup verification depth.** A and B: md5 only, router vs host; no size
   check against `/proc/mtd`; no second copy check; "copy it somewhere" as
   advice. **New skill:** size == `/proc/mtd`, router hash == host hash, sha256
   recorded, critical partitions present, factory not blank, MACs printed,
   every partition cross-checked against the whole-chip dump, a second copy on
   a different filesystem compared, then the **user** confirms by typing.
5. **SSH host-key checking off.** A's backup script uses
   `StrictHostKeyChecking=no` + `UserKnownHostsFile=/dev/null`. **New skill:**
   per-phase known_hosts files with `accept-new`.
6. **Host gateway.** U says set the PC to `192.168.1.254` with gateway
   `192.168.1.1`; A and B say **no gateway** so internet stays on Wi-Fi. Both
   work for TFTP; no gateway is safer for the host. Kept A/B's advice.
7. **Which LAN port.** A and B: "LAN4 works when LAN1 didn't" (field report).
   U's DTS explains why: U-Boot only drives the MT7531 switch; `lan1` is the
   2.5G port on a separate PHY. New skill: use a 1G LAN port, trust the capture.
8. **Reset-button recovery trigger.** A/B present "hold RESET ~10 s at power-on"
   as a general fallback. In U's U-Boot env the button is checked in
   `boot_first`, which runs on the first boot with the default env; later boots
   rely on the automatic TFTP fallback. Marked best-effort.
9. **Return to stock.** B describes writing stock `ubi` then `fip` from
   recovery, with `kmod-mtd-rw`, as a recipe. It is untested, would happen
   after A/B have replaced BL2 (stock FIP on OpenWrt BL2 is unverified), and
   raw UBI restores can break with new bad blocks. New skill documents it as
   untested and does not automate it.
10. **Small things.** B says LuCI at `https://192.168.1.1` in one place and
    `http://` elsewhere (default is http). A ships a `.skill` zip duplicate of
    the same content. Stock partition **sizes** are not shown in A or B; the new
    skill checks them against U's layout and stops on any mismatch.

## What the new skill keeps from A

The overall stock → FIP → erase ubi → TFTP recovery → sysupgrade flow, the
no-gateway host trick, the TFTP self-test with blksize 1468, the packet-capture
gate, `scp -O` for Dropbear, streaming dumps over SSH instead of to router RAM,
and the "never put a sudo password anywhere" rule. All scripts were written
from scratch.
