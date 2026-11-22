# Human step: buy a static ISP proxy

The agent can create the VM, install 3x-ui, and wire the Xray config. It must
**not** buy the proxy, enter payment details, or store the credentials in git.

If you want destination sites to see a UK ISP IP instead of the cloud VM's
datacentre IP, complete this step yourself and paste the SOCKS5 details back
to the agent (host, port, username, password). If you skip it, the VPN still
works; egress is the VM IP.

## What to buy

Use a **static / dedicated ISP proxy** (sometimes labelled "ISP Proxies" or
"Dedicated ISP"), not a rotating residential proxy billed per gigabyte.

Recommended starting point (as of November 2026; confirm live pricing):

- Provider: [IPRoyal ISP Proxies](https://iproyal.com/isp-proxies/)
- Product: Dedicated / static ISP, **UK, London**
- Duration: 30 days is enough to test (a 24-hour trial, around $1.80, is
  safer than a long commitment)
- Protocol: SOCKS5 with **UDP** support (IPRoyal's default SOCKS port is often
  `12324`)
- Auth: username/password (preferred if you might rebuild the VM) or an IP
  whitelist locked to the VM's single public IPv4

Price is typically a few dollars per IP per 30 days, not hundreds.

## What to avoid

- **Rotating residential proxies billed per GB.** These are the products that
  show figures like ~$800 for 200 GB. They are the wrong tool for a always-on
  personal VPN.
- **Decodo (formerly Smartproxy) Static Residential ISP plans** that restrict
  destination ports to `80`, `443`, `563`, `8443`, and `43`. That breaks
  non-web traffic (plain DNS, WebRTC STUN, SSH-over-VPN, and most UDP).
- Shared / rotating pools if you need a stable exit IP.

## After you have the details

Paste, do not commit:

```
PROXY_HOST=...
PROXY_PORT=12324
PROXY_USER=...
PROXY_PASS=...
```

The agent (or you) then runs `scripts/add-proxy-outbound.py` and
`scripts/verify-egress.sh`. A successful check shows `ipinfo.io` returning the
**proxy** IP and an ISP ASN, not the VM's cloud ASN. Also look at
[ipapi.is](https://api.ipapi.is/) (`is_datacenter` should be false) and
[Scamalytics](https://scamalytics.com/).

Bandwidth on a typical dedicated ISP product is capped (IPRoyal has been in
the region of 100 GB / 30 days per IP, then throttled). Do not run OS
updates, Steam, or torrents over the tunnel. Keep the use personal: provider
terms usually forbid resale or sharing with third parties. Review the
provider's current terms, including any jurisdiction clauses, before you pay.
