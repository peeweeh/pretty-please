# Remote access via SSM port-forward

The demo binds to `localhost:9000` on the sandbox EC2 (`i-00ce4ae955b4915f4`).
The security group does **not** expose port 9000, so the easiest path from
another laptop is an SSM tunnel — no SG change required.

---

## Prereqs (one-time on the other computer)

1. **AWS CLI v2** installed.
2. **Session Manager plugin** installed:
   - macOS: `brew install --cask session-manager-plugin`
   - Linux: see https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html
3. **AWS credentials** for the sandbox account (540045617450) under any profile name.
   Easiest: SSO login.
   ```bash
   aws configure sso
   # SSO start URL + region (ap-southeast-1) + AdministratorAccess role
   ```
   Then alias the resulting profile to something short, e.g. `eonar_dev003`,
   in `~/.aws/config`:
   ```ini
   [profile eonar_dev003]
   sso_session = tsquared
   sso_account_id = 540045617450
   sso_role_name = AdministratorAccess
   region = ap-southeast-1
   ```

---

## Start the tunnel

```bash
aws ssm start-session \
  --target i-00ce4ae955b4915f4 \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["9000"],"localPortNumber":["9000"]}' \
  --region ap-southeast-1 \
  --profile eonar_dev003
```

Leave that terminal open. Then on the laptop:

```
http://localhost:9000
```

Stop with `Ctrl+C`.

---

## Make sure the demo is actually running on the EC2

If `http://localhost:9000` returns nothing once the tunnel is up, the container
probably isn't running. From the EC2 (or via SSM RunShellScript):

```bash
cd ~/pretty-please
docker compose ps
# If not up:
DOCKER_BUILDKIT=0 docker compose up -d
```

> **Build gotcha:** sandbox has Docker buildx 0.12.1 but Compose v2 wants ≥0.17
> for BuildKit. Always prefix builds with `DOCKER_BUILDKIT=0`. The image is
> already cached as `pretty-please-app:latest` so a plain `docker compose up -d`
> should just start.

---

## Quick remote check (without tunneling)

To confirm the app is alive on the EC2 from another machine:

```bash
aws ssm send-command \
  --instance-ids i-00ce4ae955b4915f4 \
  --document-name AWS-RunShellScript \
  --region ap-southeast-1 \
  --profile eonar_dev003 \
  --parameters 'commands=["curl -sf -o /dev/null -w \"HTTP %{http_code}\\n\" http://localhost:9000/ || echo DOWN"]' \
  --output json --no-cli-pager | jq -r '.Command.CommandId'

# Then with that command id:
aws ssm get-command-invocation \
  --command-id <ID> \
  --instance-id i-00ce4ae955b4915f4 \
  --region ap-southeast-1 \
  --profile eonar_dev003 \
  --output json --no-cli-pager | jq -r '"Status: \(.Status)\n\(.StandardOutputContent)"'
```

Expected: `HTTP 200`.

---

## Alternative: open port 9000 in the SG (if SSM is overkill)

Only do this if you actually want the public URL, e.g. for a demo to someone
who doesn't have AWS access:

```bash
MYIP=$(curl -s ifconfig.me)
aws ec2 authorize-security-group-ingress \
  --region ap-southeast-1 \
  --profile eonar_dev003 \
  --group-name eonar-sandbox-ec2-sg \
  --protocol tcp --port 9000 \
  --cidr ${MYIP}/32
```

Then use `http://52.220.182.114:9000`.

Revoke afterwards:

```bash
aws ec2 revoke-security-group-ingress \
  --region ap-southeast-1 \
  --profile eonar_dev003 \
  --group-name eonar-sandbox-ec2-sg \
  --protocol tcp --port 9000 \
  --cidr ${MYIP}/32
```

---

## Reference

| Field | Value |
|---|---|
| Account | `540045617450` |
| Region | `ap-southeast-1` |
| Instance | `i-00ce4ae955b4915f4` (eonar sandbox EC2) |
| EIP | `52.220.182.114` |
| Container port | `9000` (host) → `8000` (container) |
| Repo path on EC2 | `/home/dev003/pretty-please` |
