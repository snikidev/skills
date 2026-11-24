# NX62 / N60 Pro flash layout

128 MiB SPI-NAND (ESMT F50L1G41LB per the upstream commit), 128 KiB erase blocks.

## Layout as OpenWrt defines it

Source: `target/linux/mediatek/dts/mt7986a-netcore-n60-pro.dts` in openwrt/openwrt
(added in commit db3eff1022, PR #18138).

| Offset | Size (hex) | Size | Linux name (OpenWrt) | U-Boot name (OpenWrt) | Contents | This skill writes it? |
|---|---|---|---|---|---|---|
| 0x000000 | 0x00100000 | 1 MiB | `bl2` (read-only) | `bl2` | BL2 preloader, first code after BootROM | **Never** |
| 0x100000 | 0x00080000 | 512 KiB | `u-boot-env` | `orig-env` | Stock U-Boot environment (unused by OpenWrt U-Boot) | **Never** |
| 0x180000 | 0x00200000 | 2 MiB | `factory` (read-only) | `factory` | Wi-Fi calibration (EEPROM @0x0, 4 KiB) and MACs (@0x1fef20, @0x1fef26) | **Never** |
| 0x380000 | 0x00200000 | 2 MiB | `fip` (read-only) | `fip` | BL31 + U-Boot (FIP) | Yes, once, on stock (step 11) |
| 0x580000 | 0x07a80000 | 122.5 MiB | `ubi` | `ubi` | UBI: OpenWrt U-Boot env, kernel+rootfs (`fit`), `rootfs_data` | Erased on stock (step 12); filled by `sysupgrade` (step 14) |

Total = 0x08000000 = 128 MiB. `scripts/router-inspect.sh` checks these sizes
by name and refuses (`INSPECT_RESULT=MISMATCH`) if anything differs.

## What `/proc/mtd` shows

**Stock Netis firmware** (as reported by brat-kuzma's skill and our earlier guide;
names only, sizes **not** independently confirmed on hardware):

```
mtd0 "spi0.1"       whole chip, 0x08000000
mtd1 "BL2"
mtd2 "u-boot-env"
mtd3 "Factory"
mtd4 "FIP"
mtd5 "ubi"
```

**OpenWrt recovery / final OpenWrt** (from the DTS above):

```
mtd0 "bl2"  mtd1 "u-boot-env"  mtd2 "factory"  mtd3 "fip"  mtd4 "ubi"
```

Rules that follow from this:

- Numbers shift between stock and OpenWrt (`ubi` is mtd5 on stock, mtd4 in
  OpenWrt). Always address partitions **by name** and re-read `/proc/mtd`.
- Names differ in case (`FIP` vs `fip`, `Factory` vs `factory`). The scripts
  match case-insensitively but pass the exact name to `mtd`.
- Never write a whole-chip dump (`spi0.1`) onto a partition. It is for
  forensic/UART-level recovery only.
- `bl2`, `factory` and `fip` are read-only in OpenWrt's Linux on purpose.
  Needing `kmod-mtd-rw` / `i_want_a_brick=1` is a signal you are off the safe path.

## Why the factory partition matters most

It holds per-unit RF calibration and the MAC addresses. OpenWrt reads them at
boot (nvmem cells in the DTS; U-Boot's `ethaddr_factory` reads 0x1fe000+0xf20).
There is no download for it. Lose it and Wi-Fi performance/legality and the MACs
are gone for good. That is why the backup is verified three times and why the
skill refuses any command that targets it.
