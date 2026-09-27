# Insurance Portal — Source Code

Setup, build, and deployment instructions. The architecture is in [`../README.md`](../README.md), in full in [`../docs/Cloud_Architecture.md`](../docs/Cloud_Architecture.md).

## Contents

| Path | Purpose |
|---|---|
| `frontend/index.html` | Upload form (3 MB client-side limit) |
| `backend/app.py` | Flask app: `GET /` serves the form, `POST /upload` writes to S3 |
| `backend/requirements.txt` | Web app dependencies |
| `lambda/lambda_function.py` | Lambda `process-uploaded-file`: S3 metadata to RDS |
| `lambda/requirements.txt` | Lambda dependency (`pymysql`, deployed as a layer) |
| `deploy/user-data.sh` | EC2 launch template user data: installs and starts the app on port 80 |
| `database/schema.sql` | Creates database `insurance_portal` and table `uploaded_files` |
| `iam/ec2-instance-role-policy.json` | Inline policy for `ec2-instance-role` |
| `iam/lambda-execution-role-policy.json` | Inline policy for `lambda-execution-role` |
| `package.ps1` | Builds the Lambda ZIP, the layer ZIP, and the submission ZIP |

No credentials are stored here: EC2 uses its instance role, Lambda reads the database password from Secrets Manager at runtime.

## Dependencies

| Component | Runtime | Packages |
|---|---|---|
| Web app (EC2) | Python 3 on Amazon Linux 2023 | `flask==3.0.0`, `boto3==1.34.0`, `gunicorn==21.2.0` |
| Lambda | Python 3.12 | `pymysql==1.2.3` (layer); `boto3` is built into the runtime |
| Database | RDS MySQL 8.0 | — |

## Configuration

| Setting | Where | Value |
|---|---|---|
| `S3_BUCKET` | EC2 environment (set in user data) | `insurance-portal-uploads-file` |
| `DB_HOST` | Lambda environment variable | RDS endpoint of `insurance-portal-db` |
| `DB_NAME` | Lambda environment variable | `insurance_portal` |
| `DB_SECRET_NAME` | Lambda environment variable | `insurance-portal-db-credentials` |

The secret must be a JSON object with `username` and `password` keys — the "Credentials for Amazon RDS database" secret type produces this format.

---

## Setup

### 1. Run the web app locally (optional)

Requires Python 3.10+ and AWS credentials with `s3:PutObject` on the bucket (for example via `aws configure`).

```powershell
cd code\backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:S3_BUCKET = "insurance-portal-uploads-file"
python app.py
```

Open http://localhost:5000 and upload a file. `app.py` loads the form from `../frontend`, so keep `backend` and `frontend` side by side.

### 2. Build the deployment packages

From the `code` folder:

```powershell
.\package.ps1
```

This writes to `code\dist\`:

- `lambda-function.zip` — the function code.
- `pymysql-layer.zip` — the layer, with `pymysql` under `python/` as Lambda expects.
- `insurance-portal-source.zip` — the source submission, without installed dependencies.

The Linux/macOS equivalent:

```bash
cd code
zip -j lambda-function.zip lambda/lambda_function.py
pip install -r lambda/requirements.txt -t python/
zip -r pymysql-layer.zip python
```

---

## Deployment (AWS Console, us-east-1)

### Step 1: Network prerequisites

Build the VPC first, per [`../docs/Cloud_Architecture.md`](../docs/Cloud_Architecture.md): `insurance-portal-vpc` with DNS resolution and DNS hostnames enabled, the six subnets and three route tables from section 2, and the four security groups from section 3. Later steps assume all of it exists.

### Step 2: S3 bucket

Create the private bucket `insurance-portal-uploads-file` with SSE-S3 encryption and Block Public Access on.

### Step 3: RDS database and secret

1. DB subnet group `insurance-portal-db-subnet-group` with both private-db subnets.
2. RDS MySQL 8.0 `insurance-portal-db`: `db.t3.micro`, 10 GB, **Public access: No**, security group `rds-sg`.
3. Secrets Manager secret `insurance-portal-db-credentials` (type: credentials for RDS) with the master username and password, rotation off.
4. From a host inside the VPC that can temporarily reach port 3306, run `database/schema.sql`:

   ```bash
   mysql -h <rds-endpoint> -u <username> -p < database/schema.sql
   ```

   Then remove the temporary access so only `lambda-sg` reaches RDS — [`../docs/TROUBLESHOOT_CONNECT.md`](../docs/TROUBLESHOOT_CONNECT.md) covers opening and reverting it.

### Step 4: IAM roles

- **`ec2-instance-role`** (trusted entity: EC2): attach `iam/ec2-instance-role-policy.json` inline.
- **`lambda-execution-role`** (trusted entity: Lambda): attach managed policy `AWSLambdaVPCAccessExecutionRole` plus `iam/lambda-execution-role-policy.json` inline.

### Step 5: Web tier (EC2 Auto Scaling behind ALB)

1. Launch template `insurance-portal-it`: Amazon Linux 2023, `t2.micro`/`t3.micro`, `ec2-app-sg`, instance profile `ec2-instance-role`, no public IP. Paste `deploy/user-data.sh` into **Advanced details → User data**.
2. Target group `app-target-group`: instances, HTTP 80, health check path `/`.
3. ALB `insurance-portal-alb`: internet-facing, both public subnets, `alb-sg`, listener HTTP 80 → `app-target-group`.
4. Auto Scaling group `insurance-portal-asg`: launch template `insurance-portal-it`, both private-app subnets, attached to `app-target-group`, ELB health checks on, desired 2 / min 2 / max 4, target tracking on average CPU utilization (50%).
5. Browse to the ALB DNS name and confirm the form loads.

`deploy/user-data.sh` embeds copies of `backend/app.py` and `frontend/index.html`. If you change either, update the matching block in the script and start an instance refresh on the Auto Scaling group.

On the instance the app runs from `/home/ec2-user/app/`, with gunicorn logging to `/var/log/insurance-portal.log`.

### Step 6: Lambda function

1. **Layers → Create layer**: `pymysql-layer`, upload `dist/pymysql-layer.zip`, compatible runtime Python 3.12.
2. **Create function** `process-uploaded-file`: Python 3.12, execution role `lambda-execution-role`.
3. **Code → Upload from → .zip file**: `dist/lambda-function.zip`, handler `lambda_function.lambda_handler`.
4. **Layers → Add a layer**: custom layer `pymysql-layer`.
5. **Configuration → General**: timeout **30 seconds**. The 3-second default is too short for a VPC cold start plus the Secrets Manager call plus the DB connection.
6. **Configuration → Environment variables**: `DB_HOST`, `DB_NAME`, `DB_SECRET_NAME` (see Configuration above).
7. **Configuration → VPC**: `insurance-portal-vpc`, both private-app subnets, security group `lambda-sg`.

### Step 7: VPC endpoints (required for Lambda)

Without these the function times out after logging the object key, having no public IP — see [`../docs/Cloud_Architecture.md`](../docs/Cloud_Architecture.md) section 5.

- **`s3-gateway-endpoint`**: service `com.amazonaws.us-east-1.s3`, type Gateway, route table `private-app-route-table`.
- **`secretsmanager-endpoint`**: service `com.amazonaws.us-east-1.secretsmanager`, type Interface, both private-app subnets, security group `lambda-sg`, private DNS enabled.

### Step 8: S3 trigger

Lambda → `process-uploaded-file` → **Add trigger** → S3, bucket `insurance-portal-uploads-file`, event type **All object create events**.

### Step 9: Verify end to end

1. Upload a file through the ALB URL; the page shows `File '<name>' uploaded successfully!`.
2. Confirm the object in the bucket.
3. In CloudWatch Logs `/aws/lambda/process-uploaded-file`, the latest stream shows:
   - `Triggered for object: s3://insurance-portal-uploads-file/<name>`
   - `File: <name>, Content-Type: <type>, Uploaded: <timestamp>`
   - `Fetched DB credentials from Secrets Manager` (on a cold start)
   - `Record inserted into RDS successfully`
4. Optionally query `SELECT * FROM uploaded_files ORDER BY upload_timestamp DESC LIMIT 5;` from inside the VPC.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| ALB returns 502/503 | Instances unhealthy: check `ec2-app-sg` allows 80 from `alb-sg`, and `/var/log/insurance-portal.log` on the instance |
| Upload returns 500 | `ec2-instance-role` missing `s3:PutObject`, or wrong `S3_BUCKET` |
| Lambda times out after the "Triggered" log | `s3-gateway-endpoint` missing from `private-app-route-table` |
| Lambda times out after the "Content-Type" log | `secretsmanager-endpoint` missing, private DNS off, or `lambda-sg` lacks the 443 self-rule |
| `No module named 'pymysql'` | Layer not attached, or ZIP lacks the top-level `python/` folder |
| MySQL connection timeout | `rds-sg` doesn't allow 3306 from `lambda-sg`, or wrong `DB_HOST` |
| `Unknown database` / table errors | `database/schema.sql` not run |

## Cleanup

Delete in this order, starting with the only hourly-billed resource:

1. `secretsmanager-endpoint`
2. The S3 trigger, then the bucket contents and the bucket
3. The Lambda function and the `pymysql-layer` layer
4. The Auto Scaling group, then the launch template
5. The ALB, then `app-target-group`
6. The RDS instance, then the DB subnet group
7. The secret `insurance-portal-db-credentials`
