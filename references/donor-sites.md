# Choosing a Reality donor site (dest / SNI)

The Reality "target" (also called dest) and SNI are the real website your
server pretends to be. A probe that does not have the correct keys is
forwarded to that site, which is the point of the camouflage.

## Requirements

- TLS 1.3 and HTTP/2
- A real landing page, **not** a 301/302 redirect
- Ideally not negotiating post-quantum TLS (X25519MLKEM768), because many
  current clients fail that handshake with `tls: unknown certificate`
- A large, unremarkable site — not your own domain, not a tiny site that
  might change certificates without warning

## How to test (on the VM, after 3x-ui is installed)

```bash
curl -I https://www.microsoft.com
# Reject the host if you see 301/302.

# Official binary path varies slightly by arch; tab-complete under /usr/local/x-ui/bin/
sudo /usr/local/x-ui/bin/xray-linux-amd64 tls ping www.microsoft.com
# If the output says "TLS Post-Quantum key exchange: true", pick another donor.
```

Country-localised names like `www.microsoft.co.uk` usually redirect and
break the handshake. Amazon properties have been observed to break Reality
donors after they were widely reused; do not assume a popular choice from an
old guide still works.

## Defaults used by this skill

- `REALITY_DEST=www.microsoft.com:443`
- `REALITY_SNI=www.microsoft.com`

Other names that have been reasonable starting points (re-test every time):
`www.asus.com`, `www.samsung.com`, `www.cisco.com`, `www.amd.com`,
`www.nvidia.com`.

Leave `mldsa65` and min/max client version fields empty. Regenerating Reality
keys or recreating the inbound silently invalidates any `vless://` link you
already exported — Reality will look like a dead connection because invalid
clients are proxied to the real donor site.
