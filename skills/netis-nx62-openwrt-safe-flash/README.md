# netis-nx62-openwrt-safe-flash

An agent skill (and a human-readable procedure) for putting OpenWrt on a
**Netis NX62 / Netcore N60 Pro** (MediaTek MT7986A, OpenWrt `netcore_n60-pro`)
with as many brakes as possible:

- strictly one step at a time, with a progress list and a stop after every step;
- the full flash backup verified three times: by script, against a second copy
  on another disk, and by you;
- the upstream OpenWrt method only: write FIP, erase ubi, TFTP recovery,
  sysupgrade. **No BL2 write, no factory write, no manual ubiformat**;
- every write is a dry run unless you add `--execute` **and** type a phrase in
  your own terminal.

> ⚠️ Flashing firmware can permanently brick your router. No warranty. If any
> check fails, stop and ask for help on the OpenWrt forum.

Start with [`SKILL.md`](SKILL.md). Why it differs from other guides:
[`references/comparison-notes.md`](references/comparison-notes.md).

## Credits

- Inspired by [brat-kuzma/netis-nx62-openwrt-skill](https://github.com/brat-kuzma/netis-nx62-openwrt-skill)
  (MIT), which pioneered the field-tested host setup, the TFTP self-test, the
  packet-capture gate and the LAN-port gotcha. The scripts here are new code.
- [SevenMaxs/netis-nx62-flash-tools](https://github.com/SevenMaxs/netis-nx62-flash-tools).
- Device facts from OpenWrt source: PR [#18138](https://github.com/openwrt/openwrt/pull/18138),
  `mt7986a-netcore-n60-pro.dts`, `uboot-mediatek` patch `462-add-netcore-n60-pro.patch`.
