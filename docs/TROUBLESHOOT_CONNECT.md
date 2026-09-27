# Reconnect to EC2 or RDS

Temporary access for setup and debugging. The running design stays closed: RDS is not public, and only `lambda-sg` may use port 3306. Region **us-east-1 (N. Virginia)**.

| Item | Value |
|---|---|
| EC2 security group | `ec2-app-sg` |
| EC2 username | `ec2-user` |
| Public subnet ACL | `public-nacl` |
| RDS security group | `rds-sg` |
| RDS instance | `insurance-portal-db` |
| Database name | `insurance_portal` |
| Master username | `<UserName>` |
| Secret name | `insurance-portal-db-credentials` |
| EC2 Instance Connect range | `18.206.107.24/29` |

The browser **Connect** button comes from `18.206.107.24/29`, not your home IP, so a rule for "My IP" does not allow it. When finished, remove every rule in [Revert](#revert).

---

## Connect to the EC2 instance

**EC2 → Instances → your instance → Connect → EC2 Instance Connect**, username `ec2-user`. Both openings below are required, and the network ACL is checked before the security group.

### 1. Security group

**EC2 → Security Groups → `ec2-app-sg` → Edit inbound rules → Add rule**

| Type | Port | Source |
|---|---|---|
| SSH | 22 | `18.206.107.24/29` |

Check the instance **Security** tab to confirm `ec2-app-sg` is the group actually attached — a rule on any other group has no effect.

### 2. Network ACL

From the instance **Networking** tab, open the Network ACL for that subnet; for an app instance in a public subnet that is `public-nacl`.

**Inbound rules → Edit inbound rules → Add new rule**

| Rule number | Type | Port | Source | Allow/Deny |
|---|---|---|---|---|
| 120 | SSH | 22 | `18.206.107.24/29` | Allow |

Use a free rule number — reusing `100` or `110` is rejected. Leave outbound alone; it already allows all traffic.

### If the button still fails

| What you see | Cause | Fix |
|---|---|---|
| Yellow banner: **Port 22 (SSH) is not authorized** | `ec2-app-sg` has no SSH rule from `18.206.107.24/29` | Add the security-group rule above, on the group attached to this instance |
| **Error establishing SSH connection to your instance** | `public-nacl` has no inbound rule for port 22 | Add rule `120`, then reconnect |
| Instance has no public IPv4 | Browser EC2 Instance Connect cannot reach it | The instance must be in a public subnet with auto-assign public IPv4 |

---

## Connect to the database

Do this from the EC2 shell above. Your laptop cannot reach RDS: public access is off and the database subnets have no internet route.

### 1. Let the app instance reach RDS

**EC2 → Security Groups → `rds-sg` → Edit inbound rules → Add rule**

| Type | Port | Source |
|---|---|---|
| MySQL/Aurora | 3306 | `ec2-app-sg` |

Keep the existing rule whose source is `lambda-sg`.

The database ACL already allows 3306 from `10.0.11.0/24` and `10.0.12.0/24`, so an app instance in either range needs no ACL change. A timeout from any other subnet means the database ACL is dropping the packet.

### 2. Open a MySQL session

Copy the endpoint from **RDS → `insurance-portal-db` → Connectivity & security**.

```bash
sudo dnf install -y mariadb105
mysql -h YOUR_RDS_ENDPOINT -P 3306 -u <UserName> -p
```

`-p` goes last with nothing after it. At `Enter password:`, type the master password from **Secrets Manager → `insurance-portal-db-credentials` → Retrieve secret value** — characters do not appear as you type, and it should not be pasted into the command.

### 3. Schema commands

The initial database name cannot be changed after the RDS instance is created, so both database and table come from SQL. Run `code/database/schema.sql`, which is idempotent and safe to re-run:

```bash
mysql -h YOUR_RDS_ENDPOINT -u <UserName> -p < schema.sql
```

If the file is not on the instance, paste its contents into the MySQL session instead. Then `SHOW DATABASES;` and `SELECT * FROM uploaded_files ORDER BY upload_timestamp DESC LIMIT 5;` confirm the schema and any rows Lambda has written.

### If MySQL fails

| What you see | Cause | Fix |
|---|---|---|
| `Access denied for user '<UserName>' ... (using password: NO)` | No password was sent | Re-run with `-p` and type the password at the prompt; a blank Enter causes this |
| `Access denied ... (using password: YES)` | Username or password does not match the RDS master user | Use the values from the secret, as set when the database was created — not a different secret |
| Connection times out | `rds-sg` has no rule from `ec2-app-sg`, or the database ACL does not allow this subnet | Add the 3306 rule; confirm the instance private IP is inside `10.0.11.0/24` or `10.0.12.0/24` |

---

## Revert

Remove only the temporary rules, leaving the permanent ones:

1. **`rds-sg`:** delete inbound MySQL `3306` from `ec2-app-sg`. Keep `3306` from `lambda-sg`.
2. **`ec2-app-sg`:** delete inbound SSH `22` from `18.206.107.24/29`. Keep HTTP `80` from `alb-sg`.
3. **`public-nacl`:** delete inbound rule `120`. Keep rule `100` (HTTP 80) and rule `110` (ephemeral ports).

Afterwards the browser Connect button fails again and the EC2 app tier cannot log in to MySQL. Lambda still can.
