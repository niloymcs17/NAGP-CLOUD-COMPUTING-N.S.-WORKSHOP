import json
import logging
import os
import urllib.parse
from datetime import datetime

import boto3
import pymysql

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
secrets_client = boto3.client("secretsmanager")

DB_SECRET_NAME = os.environ.get("DB_SECRET_NAME", "insurance-portal-db-credentials")
DB_HOST = os.environ.get("DB_HOST")
DB_NAME = os.environ.get("DB_NAME", "insurance_portal")

_db_creds_cache = None


def get_db_credentials():
    global _db_creds_cache
    if _db_creds_cache is None:
        response = secrets_client.get_secret_value(SecretId=DB_SECRET_NAME)
        _db_creds_cache = json.loads(response["SecretString"])
        logger.info("Fetched DB credentials from Secrets Manager")
    return _db_creds_cache


def lambda_handler(event, context):
    record = event["Records"][0]
    bucket = record["s3"]["bucket"]["name"]
    key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])

    logger.info(f"Triggered for object: s3://{bucket}/{key}")

    head = s3.head_object(Bucket=bucket, Key=key)
    content_type = head.get("ContentType", "unknown")
    upload_timestamp = datetime.utcnow().isoformat()

    logger.info(f"File: {key}, Content-Type: {content_type}, Uploaded: {upload_timestamp}")

    creds = get_db_credentials()
    connection = pymysql.connect(
        host=DB_HOST,
        user=creds["username"],
        password=creds["password"],
        db=DB_NAME,
        connect_timeout=5,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO uploaded_files (file_name, content_type, upload_timestamp)
                VALUES (%s, %s, %s)
                """,
                (key, content_type, upload_timestamp),
            )
        connection.commit()
        logger.info("Record inserted into RDS successfully")
    finally:
        connection.close()

    return {
        "statusCode": 200,
        "body": json.dumps({
            "file_name": key,
            "content_type": content_type,
            "upload_timestamp": upload_timestamp,
        }),
    }
