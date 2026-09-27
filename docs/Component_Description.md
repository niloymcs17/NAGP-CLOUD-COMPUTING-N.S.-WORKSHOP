# Component description — insurance portal

Region **us-east-1 (N. Virginia)**. One VPC, three tiers, two Availability Zones. Names are as they appear in the console.

Owns the purpose, security, and high availability of each component. Network layout is in [`Cloud_Architecture.md`](Cloud_Architecture.md), trade-offs in [`Assumptions.md`](Assumptions.md), bonus evidence in [`Bonus_Points.md`](Bonus_Points.md).

---

## Summary

| Service | Resource | Purpose in the architecture |
|---|---|---|
| IAM | groups + `ec2-instance-role`, `lambda-execution-role` | Least-privilege access for people and workloads |
| VPC | `insurance-portal-vpc` | Isolated network, `10.0.0.0/16`, six subnets |
| Internet Gateway | `insurance-portal-igw` | Public path for the load balancer |
| NAT Gateway | conceptual, not deployed | Production outbound path for private subnets |
| ELB | `insurance-portal-alb` | Only public entry to the website |
| Auto Scaling | `insurance-portal-asg` | Peak and off-peak capacity for the app tier |
| EC2 | Amazon Linux 2023 instances | Flask upload app on gunicorn port 80 |
| S3 | `insurance-portal-uploads-file` | Stores uploaded documents, emits the event |
| Lambda | `process-uploaded-file` | Reads metadata, writes the row into RDS |
| VPC endpoints | `s3-gateway-endpoint`, `secretsmanager-endpoint` | Private access to S3 and Secrets Manager |
| RDS | `insurance-portal-db` | MySQL store for upload metadata |
| Secrets Manager | `insurance-portal-db-credentials` | Database username and password |
| CloudWatch | logs, dashboard, alarm | Evidence of each invocation, plus monitoring |

---

## IAM

**Purpose.** People sign in as IAM users belonging to a group: `Developers` for the app services, `NetworkAdmins` for the VPC, `DBAdmins` for RDS. Workloads use roles instead of keys:

| Role | Used by | Permissions |
|---|---|---|
| `ec2-instance-role` | EC2 app instances | `s3:PutObject` on the uploads bucket |
| `lambda-execution-role` | `process-uploaded-file` | VPC network interfaces, CloudWatch Logs, `s3:GetObject` on the uploads bucket, `secretsmanager:GetSecretValue` on `insurance-portal-db-*` |

**Security.** Policies attach to groups, not individual users. The root account has MFA, no access keys, and no daily use. Both roles are scoped to the resources above, and no long-lived keys exist on any instance or in any function.

**High availability.** Global AWS service; nothing to design.

---

## Amazon VPC — `insurance-portal-vpc`

**Purpose.** One `10.0.0.0/16` network with six subnets across two AZs: public for the load balancer, private-app for EC2 and Lambda, private-db for the database. DNS resolution and DNS hostnames are on, which the Secrets Manager interface endpoint needs for private DNS.

**Security.** The database subnets have no internet route at all. Security groups reference other security groups rather than open CIDR ranges, and per-tier network ACLs add a second, stateless check.

**High availability.** Every tier has a subnet in us-east-1a and one in us-east-1b, so losing a zone leaves each tier with capacity.

---

## Internet gateway and NAT gateway

**Purpose.** `insurance-portal-igw` carries traffic for the public subnets, which is how users reach the load balancer. A NAT gateway is the production outbound path for private instances.

**Security.** `private-db-route-table` has no internet route, so the database tier can neither be reached from the internet nor initiate traffic outward.

**Note.** The NAT gateway is drawn on the diagram but **not deployed**, being outside the Free Tier. `private-app-route-table` sends `0.0.0.0/0` to the internet gateway instead, which serves EC2 but not Lambda; the VPC endpoints below cover that gap.

---

## Application Load Balancer — `insurance-portal-alb`

**Purpose.** The single public entry point: internet-facing, in both public subnets, HTTP listener on port 80 forwarding to target group `app-target-group`, health checks on `GET /`.

**Security.** `alb-sg` accepts HTTP 80 from the internet, as the assignment requires; TLS is out of scope. The instances behind it are in private subnets, unreachable from the internet.

**High availability.** Nodes in both public subnets, and traffic goes only to targets passing the health check, so a failed instance leaves rotation automatically.

---

## Auto Scaling group — `insurance-portal-asg`

**Purpose.** Runs the app tier from launch template `insurance-portal-it` (Amazon Linux 2023, `ec2-app-sg`, instance profile `ec2-instance-role`), so no instance is built by hand. Desired capacity 2, maximum 4. A target-tracking policy on average CPU utilization at **50%** adds instances at peak and removes them afterward, meeting the peak and off-peak requirement.

**Security.** Instances accept HTTP 80 from `alb-sg` only, never from the internet. The instance role allows `s3:PutObject` on `insurance-portal-uploads-file` and nothing else, so no credentials sit on disk.

**High availability.** Instances spread across both private-app subnets; ELB health checks run alongside EC2 status checks, and unhealthy instances are replaced automatically.

---

## Amazon EC2 — application tier

**Purpose.** Each instance runs the Flask backend (`backend/app.py`) and the upload form (`frontend/index.html`) behind gunicorn on port 80. User data installs Python, builds a virtual environment, writes the app files, and starts the server on first boot. `POST /upload` stores the file in S3 with the browser's Content-Type.

**Security.** The app reaches S3 through the instance role via boto3, so no access keys exist in code or on disk. Uploads are capped at 3 MB. The final security group has no SSH rule; the temporary SSH and MySQL rules used during setup were removed.

**High availability.** Instances are interchangeable, and the launch template makes every replacement identical, so the group can destroy and recreate them freely.

---

## Amazon S3 — `insurance-portal-uploads-file`

**Purpose.** Stores the uploaded documents and starts the serverless path: an object-created notification invokes `process-uploaded-file` on every new object.

**Security.** Block Public Access is on, so no public object URLs exist. Default encryption is SSE-S3. Writes come only from `ec2-instance-role` and metadata reads only from `lambda-execution-role`, both scoped to this bucket.

**High availability.** Regional service, replicated across AZs by default.

---

## AWS Lambda — `process-uploaded-file`

**Purpose.** The serverless processing step: Python 3.12 in both private-app subnets with `lambda-sg`, carrying a `pymysql` layer because that driver is not in the runtime. Per upload it reads object metadata with `head_object`, takes the Content-Type, loads the credentials from Secrets Manager, and inserts `file_name`, `content_type`, and `upload_timestamp` into `uploaded_files`. The timeout is 30 seconds, since a VPC cold start plus the Secrets Manager call plus the MySQL connection does not fit in the 3-second default.

**Security.** `lambda-execution-role` carries the whole permission set, with no access keys anywhere. The password is neither in the code nor in an environment variable — the function holds only the secret name, in `DB_SECRET_NAME`.

**High availability.** Attached to subnets in both zones, so an invocation can start in either. Lambda scales concurrency automatically.

---

## VPC endpoints

**Purpose.** Give the private-app subnets a path to AWS services that never leaves the AWS network: `s3-gateway-endpoint` for `head_object` from Lambda and `PutObject` from EC2, `secretsmanager-endpoint` for the database credentials. Both are required rather than optional — [`Cloud_Architecture.md`](Cloud_Architecture.md) section 5 gives the reason, placement, and cost model.

**Security.** This is the "private interfaces to PaaS resources" control. `lambda-sg` allows inbound HTTPS 443 from itself so the function can open a connection to the interface endpoint, which uses the same group. Traffic to S3 and Secrets Manager never crosses the public internet.

**High availability.** The interface endpoint has a network interface in each private-app subnet; the gateway endpoint is a route-table entry with no single point of failure.

---

## Amazon RDS — `insurance-portal-db`

**Purpose.** MySQL 8.0 holding upload metadata, in subnet group `insurance-portal-db-subnet-group` across both private-db subnets, with 10 GB of storage. Database `insurance_portal` has one table, defined in `code/database/schema.sql`:

| `uploaded_files` column | Type |
|---|---|
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` |
| `file_name` | `VARCHAR(255) NOT NULL` |
| `content_type` | `VARCHAR(100)` |
| `upload_timestamp` | `DATETIME NOT NULL` |
| `created_at` | `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` |

**Security.** Public access is off, so the endpoint does not answer from the internet. `rds-sg` allows 3306 from `lambda-sg` only — no rule from the app tier, none from `0.0.0.0/0`. The master password lives in Secrets Manager, not in any config file. Encryption at rest uses the default KMS key.

**High availability.** The subnet group spans both AZs, so a standby can be placed in the second one. Multi-AZ is off for cost ([`Assumptions.md`](Assumptions.md) section 2).

---

## AWS Secrets Manager — `insurance-portal-db-credentials`

**Purpose.** Holds the RDS username and password. Lambda fetches them at runtime instead of reading a hardcoded value, logging `Fetched DB credentials from Secrets Manager` — the evidence for the bonus item.

**Security.** Only `lambda-execution-role` can read it, and only for names matching `insurance-portal-db-*`. The value arrives through the interface endpoint, so the call stays inside the VPC. Rotation is off ([`Assumptions.md`](Assumptions.md) section 8).

**High availability.** Managed regional service, reached through an endpoint present in both private-app subnets.

---

## Amazon CloudWatch

**Purpose.** Operational visibility. Lambda writes a log stream per invocation to `/aws/lambda/process-uploaded-file`, carrying the Content-Type, the secret fetch, and the successful insert. The bonus dashboard `insurance-portal` and alarm `insurance-portal-db-low-free-storage` are specified in [`Bonus_Points.md`](Bonus_Points.md).

**Security.** Write permission comes from the managed policy on the Lambda role. No secret values are logged, only the fact that credentials were retrieved.

**High availability.** Managed regional service; nothing to design.

**Note.** EC2 logs to `/var/log/insurance-portal.log` on each instance and is not centralized, because the CloudWatch agent is not installed.
