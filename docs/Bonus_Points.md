# Bonus Activities

Region **us-east-1**. All three bonus items are implemented. This document holds the evidence; the components themselves are described in [`Component_Description.md`](Component_Description.md).

## 1. AWS Secrets Manager

The RDS username and password live in the secret `insurance-portal-db-credentials` — not in `lambda/lambda_function.py` and not in a Lambda environment variable. The function holds only the secret name, in `DB_SECRET_NAME`.

On each object created in `insurance-portal-uploads-file`, `process-uploaded-file` calls `secretsmanager:GetSecretValue`, connects to MySQL with the returned credentials, and inserts the file name, content type, and upload time.

The log line proving the fetch, in log group `/aws/lambda/process-uploaded-file`:

```text
Fetched DB credentials from Secrets Manager
```

Rotation is off; see [`Assumptions.md`](Assumptions.md) section 8.

## 2. Private interfaces to PaaS resources

Two VPC endpoints keep the function's calls to S3 and Secrets Manager on the AWS network. They are required rather than optional, since a VPC-attached Lambda has a private IP only — [`Cloud_Architecture.md`](Cloud_Architecture.md) section 5 has the mechanism.

| Endpoint | Type | Evidence of private access |
|---|---|---|
| `s3-gateway-endpoint` | Gateway | `head_object` against `insurance-portal-uploads-file` succeeds from a subnet with no NAT gateway. On `private-app-route-table`. |
| `secretsmanager-endpoint` | Interface | `GetSecretValue` succeeds with private DNS on, so `secretsmanager.us-east-1.amazonaws.com` resolves to a private address inside the VPC. Both private-app subnets. |

RDS uses no endpoint: `insurance-portal-db` already has a private address, and `rds-sg` allows 3306 from `lambda-sg` only.

## 3. CloudWatch dashboard and alarm

### Alarm

| Setting | Value |
|---|---|
| Name | `insurance-portal-db-low-free-storage` |
| Metric | `FreeStorageSpace` on `insurance-portal-db` |
| Condition | Lower than `2147483648` bytes (2 GB) |
| Notification | SNS topic `insurance-portal-alarms` |

The volume is 10 GB with about 9 GB free, so the alarm stays **OK** once CloudWatch has a sample. **Insufficient data** right after creation just means the first sample has not arrived. Confirm the SNS subscription email so the topic can send mail.

### Dashboard

Name `insurance-portal`, three line widgets:

| Widget | What it shows |
|---|---|
| Lambda **Invocations**, **Errors**, **Successes** (`m1 - m2`) | One upload invokes `process-uploaded-file` once; successes is invocations minus errors. Use statistic **Sum** for whole-number counts. |
| RDS **FreeStorageSpace** | Free disk on `insurance-portal-db` in bytes — the same metric as the alarm |
| **ResourceCount** (`AWS/Usage`) | Account usage count for the selected resource; stays flat and does not track Auto Scaling |

EC2 capacity is not on this dashboard; it is visible on the Auto Scaling group itself.
