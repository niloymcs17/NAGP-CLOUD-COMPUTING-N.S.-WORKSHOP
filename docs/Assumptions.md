# Scope and assumptions — insurance portal

Insurance portal MVP for the cloud computing workshop. Owns the reasoning: what was in and out of scope, which trade-off was taken at each decision point, and the resulting limitations.

What was built is in [`Component_Description.md`](Component_Description.md) (per service) and [`Cloud_Architecture.md`](Cloud_Architecture.md) (network and flows); bonus evidence in [`Bonus_Points.md`](Bonus_Points.md).

---

## Summary

| Area | Decision | Main reason |
|---|---|---|
| Account | One new Free Tier account | Assignment requirement; cost |
| Region | Single region, **us-east-1**, two Availability Zones | Meets the HA requirement without cross-region cost or complexity |
| NAT gateway | Drawn on the diagram, **not deployed** | Not in the Free Tier; the assignment allows an IGW route instead |
| Private AWS access | S3 gateway and Secrets Manager interface VPC endpoints | Lambda has a private IP only and cannot use the IGW route |
| Database | RDS **MySQL 8.0**, `db.t3.micro`, 10 GB gp2, single-AZ | Free Tier eligible; simple schema; lightweight driver |
| Protocol | **HTTP** on port 80 only | Assignment requirement; TLS out of scope |
| Secrets | Secrets Manager, **rotation off** | Bonus needs fetch, not rotation; rotation adds cost and failure modes |
| Application | Single upload form, no login | MVP scope from the brief |

---

## 1. Scope

**In scope**

- One VPC, six subnets (public, private-app, private-db), two Availability Zones.
- Internet-facing ALB in front of an Auto Scaling group of EC2 instances running a Flask upload app.
- S3 bucket for uploads, with an event notification that triggers Lambda.
- Lambda reads object metadata and inserts a row into RDS MySQL.
- Database access restricted to Lambda; no public access to RDS.
- IAM groups and least-privilege roles, security groups, network ACLs.
- Bonus: Secrets Manager credentials, CloudWatch dashboard and alarm.

**Out of scope**

- HTTPS/TLS, custom domains, Route 53, ACM certificates.
- Authentication, authorization, per-user file access.
- Virus scanning, content inspection, file-type allowlists.
- Multi-region deployment, disaster recovery, cross-region replication.
- CI/CD and infrastructure as code — every resource was created by hand in the console.
- AWS WAF, Shield Advanced, GuardDuty.
- Centralized EC2 application logging (section 10).

---

## 2. Free Tier and cost constraints

The design is bounded by the AWS Free Tier, which drove:

- **NAT gateway not deployed.** Billed per hour plus per GB and not in the Free Tier (section 4).
- **Small instances.** Free Tier eligible EC2 types; RDS `db.t3.micro` (or `db.t2.micro`) with 10 GB gp2.
- **Single-AZ RDS.** Multi-AZ doubles the instance cost. The subnet group still spans both private-db subnets, so it can be enabled later without network changes.
- **Auto Scaling capped at 4 instances**, so a load test cannot run up an unbounded bill.
- **One billable exception: `secretsmanager-endpoint`**, billed hourly per subnet, plus a small monthly charge for the secret. Accepted because the bonus item requires them; the endpoint is deleted during cleanup.
- **`s3-gateway-endpoint`** has no hourly charge and is kept.

---

## 3. Single-region deployment

- All resources are in **us-east-1**, chosen for the widest service and Free Tier availability.
- HA comes from spreading every tier across **us-east-1a** and **us-east-1b** ([`Cloud_Architecture.md`](Cloud_Architecture.md) section 6).
- **Limitation:** a full regional outage takes the portal offline. There is no cross-region S3 replication, RDS read replica, or DNS failover. Production would add a second region with Cross-Region Replication, a read replica, and Route 53 failover.

---

## 4. Networking simplifications

**NAT gateway is conceptual only.** The assignment allows private subnets to route to the internet gateway since NAT is not in the Free Tier, but still asks for NAT on the diagram. So:

- NAT is **drawn** in a public subnet, labelled "Not deployed (Free Tier)".
- `private-app-route-table` sends `0.0.0.0/0` to `insurance-portal-igw` as a stand-in.
- `private-db-route-table` has **no** internet route; the database tier cannot reach or be reached from the internet.

**Cost of that substitution.** The stand-in works for EC2 but not Lambda, so two VPC endpoints were needed to keep the serverless path working at all ([`Cloud_Architecture.md`](Cloud_Architecture.md) section 5). This is the one place where the Free Tier choice added components instead of removing them.

**No bastion host.** Schema setup used the app instance with temporary access, since removed (section 9).

---

## 5. Database engine selection

**Engine: Amazon RDS for MySQL 8.0.**

| Option considered | Outcome | Reason |
|---|---|---|
| RDS MySQL | **Chosen** | Free Tier eligible; simple relational schema; pure-Python `pymysql` packages easily as a Lambda layer |
| RDS PostgreSQL | Not chosen | Free Tier eligible and workable, but `psycopg2` needs compiled binaries matched to the Lambda runtime |
| Amazon Aurora | Not chosen | Not Free Tier eligible; its scaling and replication features are unnecessary for one metadata table |
| DynamoDB | Not chosen | The assignment explicitly requires Amazon RDS |

**Configuration assumptions**

- `db.t3.micro` (or `db.t2.micro`), 10 GB gp2, encryption at rest with the default KMS key.
- **Single-AZ** for cost (section 2). Backups use RDS defaults; no custom backup or point-in-time recovery testing.
- One table, `uploaded_files` in `insurance_portal` — columns in [`Component_Description.md`](Component_Description.md).
- Low volume: one short `INSERT` per upload, so Lambda opens a connection per invocation and RDS Proxy is not used.

---

## 6. Application assumptions

- **Single upload form**, no login: anyone reaching the ALB can upload.
- **3 MB cap** via `MAX_CONTENT_LENGTH`. The only other validation is a non-empty filename — no file-type allowlist, no virus scan.
- Files keep the browser-supplied Content-Type (fallback `application/octet-stream`). Lambda records whatever S3 holds and does not inspect contents.
- Uploads cannot be listed, downloaded, or deleted through the app, and duplicate filenames are not de-duplicated.
- The app tier **does not** write to the database. Only Lambda does, asynchronously, so a Lambda failure does not affect the user's upload response.
- The app runs under gunicorn on port 80, installed by user data on first boot. No container or AMI pipeline.

---

## 7. Scaling and high availability assumptions

- **`insurance-portal-asg`**: desired **2** (one per private-app subnet), maximum **4**.
- Target tracking on **average CPU utilization at 50%**, which is also a reasonable production setting.
- Peak handling is assumed CPU-driven; scaling is not tied to request count, upload volume, or Lambda activity.
- Lambda concurrency stays at the account default — no reserved or provisioned concurrency.

---

## 8. Secrets Manager

Credentials live in **`insurance-portal-db-credentials`**. Lambda reads them via `DB_SECRET_NAME`; the password is in neither code nor environment variables. **Automatic rotation is off.**

**Why rotation is disabled**

- The bonus requires *fetching* a secret and showing it in the Lambda logs, not rotating passwords.
- Rotation needs a rotation Lambda, a schedule, IAM, and usually VPC access to RDS — complexity, failure modes, and cost beyond the MVP.


---

## 9. Security simplifications

- **HTTP only** on port 80, as required, so browser-to-ALB traffic is unencrypted. Traffic to S3 and Secrets Manager uses HTTPS over the VPC endpoints.
- `alb-sg` accepts port 80 from `0.0.0.0/0`; no WAF, rate limiting, or IP allowlist.
- Lambda uses the RDS **master** credentials. Production would use a dedicated user with `INSERT` on `uploaded_files` only.
- **Temporary setup access, since removed:** a MySQL rule from `ec2-app-sg` to `rds-sg` and an SSH rule on the app instance, used to create `uploaded_files` and verify rows. Both were removed so only Lambda reaches RDS; [`TROUBLESHOOT_CONNECT.md`](TROUBLESHOOT_CONNECT.md) covers reopening and re-closing them.
- IAM users are grouped (`Developers`, `NetworkAdmins`, `DBAdmins`) with policies on the groups. `Developers` uses a custom least-privilege policy, but `NetworkAdmins` uses the managed `AmazonVPCFullAccess` for simplicity rather than a fully scoped custom policy.

---

## 10. Monitoring

- Lambda logs to **`/aws/lambda/process-uploaded-file`** (Content-Type, secret fetch, successful insert). No secret values are logged.
- EC2 logs stay on each instance at `/var/log/insurance-portal.log`, because the CloudWatch agent is not installed, and are lost when an instance is terminated.
- Beyond the bonus dashboard and alarm in [`Bonus_Points.md`](Bonus_Points.md).

---

## 11. Known limitations

- A us-east-1 regional outage takes the whole portal down (section 3).
- A database failure means downtime until RDS recovers the instance, since Multi-AZ is off (section 2).
- Uploads travel over plain HTTP, and anyone with the ALB URL can upload up to 3 MB (sections 6 and 9).
- If Lambda fails — for example, because the database is unavailable — the file remains in S3 without its metadata row. There is no dead-letter queue or retry beyond Lambda's built-in asynchronous retries.
- Private-app subnets have no working general internet egress for Lambda, so each new AWS service it needs requires another VPC endpoint or a NAT gateway.

---

## 12. Cleanup

Delete billable resources after recordings, in the order given by the cleanup section of [`code/README.md`](../code/README.md). The urgent one is **`secretsmanager-endpoint`**, billed per hour.
