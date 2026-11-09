"""Operator-only native SQL Server backup restore and baseline inspection."""

import argparse
import csv
import hashlib
import json
import os
import tempfile
import time
import urllib.request
from pathlib import Path

import boto3
import pymssql

ROOT = Path(__file__).resolve().parents[2]
SEEDS = json.loads(Path(__file__).with_name("seeds.json").read_text())
REGION = os.environ.get("AWS_REGION", "us-east-1")
SECRET = os.environ.get("WWI_SECRET_NAME", "daiwt-02-sqlserver")
STACK = os.environ.get("WWI_STACK_NAME", "daiwt-02-sqlserver")


def quote_identifier(name):
    return "[" + name.replace("]", "]]") + "]"


def connect(database="master"):
    secret = json.loads(boto3.client("secretsmanager", region_name=REGION)
                        .get_secret_value(SecretId=SECRET)["SecretString"])
    options = {"server": secret["host"], "port": str(secret["port"]),
               "user": secret["username"], "password": secret["password"],
               "database": database, "autocommit": True, "encryption": "require",
               "login_timeout": 30, "timeout": 300, "as_dict": True}
    return pymssql.connect(**options)


def outputs():
    stack = boto3.client("cloudformation", region_name=REGION).describe_stacks(
        StackName=STACK)["Stacks"][0]
    return {o["OutputKey"]: o["OutputValue"] for o in stack["Outputs"]}


def upload_seeds(bucket):
    s3 = boto3.client("s3", region_name=REGION)
    for spec in SEEDS["databases"]:
        key = "seed/" + spec["file"]
        try:
            obj = s3.head_object(Bucket=bucket, Key=key)
            if obj.get("Metadata", {}).get("sha256") == spec["sha256"]:
                continue
        except s3.exceptions.ClientError as exc:
            if exc.response["Error"]["Code"] not in ("404", "NoSuchKey"):
                raise
        url = ("https://github.com/microsoft/sql-server-samples/releases/download/"
               "wide-world-importers-v1.0/" + spec["file"])
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / spec["file"]
            urllib.request.urlretrieve(url, path)
            if hashlib.sha256(path.read_bytes()).hexdigest() != spec["sha256"]:
                raise RuntimeError("Backup checksum mismatch: " + spec["file"])
            s3.upload_file(str(path), bucket, key,
                           ExtraArgs={"Metadata": {"sha256": spec["sha256"]},
                                      "Tagging": "project=daiwt&demo=02"})
        print("Uploaded", key, flush=True)


def wait_restore(cursor, task_id, timeout=3600):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        cursor.execute("EXEC msdb.dbo.rds_task_status @task_id=%s", (task_id,))
        task = cursor.fetchone()
        state = task["lifecycle"]
        if state != last:
            print("Restore", task_id, state, flush=True)
            last = state
        if state == "SUCCESS":
            return
        if state in ("ERROR", "CANCELLED", "CANCEL_REQUESTED"):
            raise RuntimeError(str(task["task_info"]))
        time.sleep(20)
    raise TimeoutError("Restore task exceeded one hour: " + str(task_id))


def restore(reset=False):
    bucket = outputs()["BackupBucket"]
    upload_seeds(bucket)
    with connect() as connection:
        cursor = connection.cursor()
        for spec in SEEDS["databases"]:
            database = spec["name"]
            cursor.execute("SELECT name,state_desc FROM sys.databases WHERE name=%s", (database,))
            existing = cursor.fetchone()
            if existing:
                if not reset:
                    if existing["state_desc"] != "ONLINE":
                        raise RuntimeError(database + " is not ONLINE; inspect native restore tasks "
                                           "before retrying or using confirmed reset")
                    print(database, "already exists; leaving unchanged", flush=True)
                    continue
                cursor.execute("EXEC msdb.dbo.rds_drop_database @db_name=%s", (database,))
            cursor.execute(
                "EXEC msdb.dbo.rds_restore_database @restore_db_name=%s, "
                "@s3_arn_to_restore_from=%s",
                (database, "arn:aws:s3:::" + bucket + "/seed/" + spec["file"]),
            )
            task = cursor.fetchone()
            wait_restore(cursor, task["task_id"])


def baseline():
    result = {"source": SEEDS["upstream"], "databases": {}}
    for spec in SEEDS["databases"]:
        database = spec["name"]
        with connect(database) as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT s.name AS schema_name,t.name AS table_name "
                           "FROM sys.tables t JOIN sys.schemas s ON t.schema_id=s.schema_id "
                           "WHERE t.is_ms_shipped=0 ORDER BY s.name,t.name")
            tables = list(cursor.fetchall())
            counts = {}
            for table in tables:
                name = table["schema_name"] + "." + table["table_name"]
                qualified = ".".join(quote_identifier(table[k])
                                     for k in ("schema_name", "table_name"))
                cursor.execute("SELECT COUNT_BIG(*) AS n FROM " + qualified)
                counts[name] = cursor.fetchone()["n"]
            result["databases"][database] = counts
    return result


def export_golden(directory):
    directory.mkdir(parents=True, exist_ok=True)
    counts = baseline()
    (directory / "row-counts.json").write_text(json.dumps(counts, indent=2) + "\n")
    queries = {
        "sale-by-day": "SELECT [Invoice Date Key],COUNT_BIG(*) AS SaleRows,"
                       "SUM([Total Including Tax]) AS TotalIncludingTax "
                       "FROM Fact.Sale GROUP BY [Invoice Date Key] ORDER BY [Invoice Date Key]",
        "customer-history": "SELECT [Customer Key],[WWI Customer ID],Customer,"
                            "[Valid From],[Valid To] FROM Dimension.Customer ORDER BY [Customer Key]",
    }
    with connect("WideWorldImportersDW") as connection:
        cursor = connection.cursor()
        for name, query in queries.items():
            cursor.execute(query)
            with (directory / (name + ".csv")).open("w", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=[d[0] for d in cursor.description],
                                        lineterminator="\n")
                writer.writeheader()
                writer.writerows(cursor.fetchall())
    print(json.dumps(counts, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("setup", "reset", "inspect", "export-golden"))
    parser.add_argument("--confirm-reset", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "parity" / "golden")
    args = parser.parse_args()
    if args.action == "reset" and not args.confirm_reset:
        parser.error("reset drops only WideWorldImporters and WideWorldImportersDW; "
                     "coordinate with all consumers and supply --confirm-reset")
    if args.action in ("setup", "reset"):
        restore(reset=args.action == "reset")
    elif args.action == "export-golden":
        export_golden(args.output)
    else:
        print(json.dumps(baseline(), indent=2))


if __name__ == "__main__":
    main()
