# Host setup (macOS, Linux, Windows)

Goal: wired interface at `192.168.1.254/24` with **no gateway** (internet stays
on Wi-Fi), a TFTP server serving the recovery image under the versionless name,
UDP/69 allowed, and a packet capture ready. `sudo` always prompts interactively.
Never put a password in a command, file or chat.

Throughout: `REC=/ABS/path/openwrt-<VER>-mediatek-filogic-netcore_n60-pro-initramfs-recovery.itb`
and `NAME=openwrt-mediatek-filogic-netcore_n60-pro-initramfs-recovery.itb`.

## macOS

```sh
networksetup -listallhardwareports          # find the wired device, e.g. en7
networksetup -listnetworkserviceorder       # find its service name
sudo networksetup -setmanual "<Service name>" 192.168.1.254 255.255.255.0 ""   # "" = no router
route -n get default | grep interface       # must still be Wi-Fi (e.g. en0)

sudo mkdir -p /private/tftpboot
sudo cp "$REC" "/private/tftpboot/$NAME" && sudo chmod 644 "/private/tftpboot/$NAME"
sudo launchctl enable system/com.apple.tftpd
sudo launchctl bootstrap system /System/Library/LaunchDaemons/tftp.plist   # or: kickstart -k
sudo lsof -nP -iUDP:69

# capture (only frames NOT from your Mac)
MYMAC=$(ifconfig en7 | awk '/ether/{print $2}')
sudo tcpdump -i en7 -n -e "not ether src $MYMAC"
```

Undo afterwards: `sudo networksetup -setdhcp "<Service name>"` and
`sudo launchctl bootout system/com.apple.tftpd`.

## Linux (Debian/Ubuntu)

```sh
sudo apt install -y tftpd-hpa tcpdump curl
sudo nmcli con add type ethernet ifname <eth> con-name nx62 ip4 192.168.1.254/24   # no gw4
sudo nmcli con up nx62
ip route get 1.1.1.1                         # dev must be Wi-Fi, not <eth>

sudo mkdir -p /srv/tftp && sudo cp "$REC" "/srv/tftp/$NAME" && sudo chmod 644 "/srv/tftp/$NAME"
# /etc/default/tftpd-hpa: TFTP_DIRECTORY="/srv/tftp" TFTP_ADDRESS="0.0.0.0:69" TFTP_OPTIONS="--secure"
sudo systemctl restart tftpd-hpa
sudo ufw allow 69/udp                        # if ufw is active

MYMAC=$(cat /sys/class/net/<eth>/address)
sudo tcpdump -i <eth> -n -e "not ether src $MYMAC"
```

Undo: `sudo nmcli con delete nx62`, `sudo systemctl stop tftpd-hpa`.

## Windows

- PowerShell (admin): `New-NetIPAddress -InterfaceAlias "Ethernet 2" -IPAddress 192.168.1.254 -PrefixLength 24`
  (no `-DefaultGateway`). Check `Find-NetRoute -RemoteIPAddress 1.1.1.1` still uses Wi-Fi.
- TFTP: tftpd64, bound to 192.168.1.254, root folder containing `$NAME`; allow UDP 69 in Defender Firewall.
- Capture: Wireshark on the wired adapter, filter `arp || tftp`.
- Run the scripts in this skill from WSL2 (they are POSIX sh). `tftp-selftest.sh` needs `curl` with TFTP support.

## Then prove it

```sh
scripts/tftp-selftest.sh --image "$REC"      # TFTP_SELFTEST=PASS required
```
