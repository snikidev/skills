# openchamber-cloud-remote

An Azure, GCP or AWS VM that acts as an OpenChamber Desktop remote instance and
only runs while it is being used. `ssh oc-remote` starts it from
stopped/deallocated and waits for SSH; a timer on the VM stops it after 30 idle
minutes.

**Provider and VM size are explicit choices.** The skill asks before doing
anything; the deploy scripts refuse to run without a provider argument and
`OC_VM_SIZE`. Recommended sizes and quota checks are in
[references/sizing.md](references/sizing.md).

What ships:

- `scripts/` — deploy, identity setup, wake-proxy install, idle-timer install
  and a read-only verify command. Every write script needs an explicit
  `--apply`.
- `references/` — Bicep and generic cloud-init, least-privilege role/policy
  notes, systemd units and the [deployment guide](references/deployment.md).

## Why this shape

OpenChamber's managed remote setup needs a reachable SSH host with Node.js,
bun and the `opencode` CLI. A VM left running 24/7 costs compute for nothing.
The local `ProxyCommand` turns a normal `ssh oc-remote` into a wake request, so
the user does not need a separate "start VM" step. The VM stops itself through
its own least-privilege identity. On Azure it calls `deallocate`: `stopped`
would keep billing for compute. The public IP is reserved on every cloud so the
SSH alias does not change across stops.

## Verified on

- Azure: Ubuntu 24.04, `Standard_D2s_v6` (2 vCPU, 8 GB) in UK South; Node
  v22.23.5, bun 1.4.5, opencode 1.19.6. Cold wake about 45 seconds; the VM
  accepted a self-deallocate (HTTP 202).
- GCP and AWS use the same design and scripts but have not been deployed in
  this setup. Check IAM conditions, image names and quotas in the target
  account before applying.

At UK South prices observed during setup, compute was about £0.088/hour, the
static IP about £0.0038/hour and the P4 disk about £4.80/month — roughly
£71.82/month if left on continuously. Wake-on-connect removes most of that.

## Install

Symlink the folder into your agent's skill directory so `git pull` keeps it
current:

```sh
mkdir -p ~/.config/opencode/skills
ln -s ~/src/snikidev-skills/skills/openchamber-cloud-remote \
  ~/.config/opencode/skills/openchamber-cloud-remote
```

It also works from OpenChamber's skills source setting or as a project skill in
`.opencode/skills/`. The folder name must match the `name:` in `SKILL.md`.

## Sources

- OpenChamber Desktop remote-instance setup (SSH managed install)
- [Azure managed identities for VM resources](https://learn.microsoft.com/entra/identity/managed-identities-azure-resources/how-to-configure-managed-identities)
- [GCP custom roles and IAM conditions](https://cloud.google.com/iam/docs/conditions-overview)
- [AWS instance profiles](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use_switch-role-ec2_instance-profiles.html)
