# Wide World Importers enterprise data estate

Wide World Importers is a fictional wholesale distributor. This handover contains
the SQL Server order-processing and reporting databases, Oracle ERP definitions,
and the SSIS packages accumulated across finance, sales, procurement, inventory,
customer service and regional operations.

## Systems and consumers

| System | Purpose | Handover |
| --- | --- | --- |
| `WideWorldImporters` | SQL Server OLTP: customers, orders, invoices, suppliers, purchasing and inventory | Native database backup and SSDT project |
| `WideWorldImportersDW` | SQL Server dimensional warehouse for sales, inventory, finance and customer reporting | Native database backup with historical legacy output and SSDT project |
| `WideWorldImporters_Staging` | Expanded landing, quality, reference and control layer | SQL definitions only |
| Oracle `WWI_*` schemas | ERP, finance, procurement and reference data | PL/SQL definitions and synthetic file generator; no running Oracle instance |
| SSIS and SQL Agent | Extraction, reconciliation, SCD history, regional tax/currency rules and batch orchestration | Original `wwi-ssis/` plus expanded `ssis/` and `sqlserver/agent/`; tooling is not installed on the hosted database |

The daily batch is scheduled after overnight ERP extracts and inbound files
arrive. Hourly incremental loads serve sales and customer operations; inventory
has an intraday refresh. Weekly reference/maintenance and month-end finance-close
definitions are in `sqlserver/agent/`. These are inherited schedule definitions,
not jobs activated by the hosted setup. Finance uses aging, close and profitability
outputs; sales and operations use customer, order and stock reporting.

`config/estate-catalog.yaml` is the canonical expanded object catalog.
`docs/architecture/`, `docs/domain-model/`, `docs/inventories/` and
`docs/known-unvalidated-items.md` describe dependencies, business rules and
unvalidated runtime assumptions. Do not rename catalog objects. The expanded
estate remains source code; the hosted restore loads the original Microsoft
OLTP and warehouse snapshots, not the expanded Oracle-dependent batch.

## Rebuild the hosted legacy databases

Prerequisites: AWS CLI v2 authenticated to the development AWS account, Python
3.10+, and an operator IP allowed on TCP 1433. Credentials are generated and
stored in AWS Secrets Manager, never in this repository.

```bash
python3 -m pip install -r deployment/rds/requirements.txt
export AWS_REGION=us-east-1
export WWI_SECRET_NAME=daiwt-02-sqlserver

# Create any missing databases; leave existing ones intact.
python3 deployment/rds/estate.py setup
python3 deployment/rds/estate.py inspect

# Destructive to these TWO databases only. Coordinate with all shared consumers.
python3 deployment/rds/estate.py reset --confirm-reset

# Capture row counts, daily sales totals and customer SCD history.
python3 deployment/rds/estate.py export-golden
```

The restore fetches the pinned Microsoft WWI v1.0 **Standard** backups, checks
SHA-256, stages them in private S3 and waits for native RDS restore success.
The warehouse backup is the historical output baseline; setup does not execute
SSIS. `parity/golden/` contains inspection exports, while the complete warehouse
baseline is the `WideWorldImportersDW-Standard.bak` object in the stack's backup
bucket. Restoring the same pinned pair gives the same source and warehouse state.
Do not reset while downstream consumers are running.

To rebuild the AWS resources from scratch, use
`infrastructure/aws/sqlserver.yaml` (CloudFormation). Choose two public subnets
in the same VPC and pass your single operator IP, **not** an open CIDR:

```bash
export VPC_ID='<vpc-id>'
export SUBNET_IDS='<subnet-id-a>,<subnet-id-b>'
export CLIENT_CIDR="$(curl -fsSL https://checkip.amazonaws.com)/32"
aws cloudformation deploy --region "$AWS_REGION" \
  --stack-name daiwt-02-sqlserver \
  --template-file infrastructure/aws/sqlserver.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides VpcId="$VPC_ID" Subnets="$SUBNET_IDS" ClientCidr="$CLIENT_CIDR" \
  --tags project=daiwt demo=02 --no-fail-on-empty-changeset
python3 deployment/rds/estate.py setup
```

An operator with two outbound addresses can also pass
`AdditionalClientCidr='<second-ip>/32'`. Keep both addresses narrowly scoped;
an HTTPS IP-check service may report a different egress address from a database
connection. Update the stack's operator parameters before connecting from a
different machine.

SQL Server Express is single-AZ, `db.t3.micro`, with 20 GiB gp2 storage.
It does not run SQL Agent or SSIS. The instance and storage incur charges while
idle; S3 and the secret also have small standing charges. Stop/start the shared
instance only after coordinating with all consumers. RDS automatically restarts
stopped instances after seven days; storage charges continue while stopped.

Indicative us-east-1 on-demand standing cost at 730 running hours/month:

| Item | Approximate cost |
| --- | --- |
| Express `db.t3.micro`, licence included | $0.022/hour, $16.06/month |
| 20 GiB gp2 | $2.30/month |
| One public IPv4 address | $0.005/hour, $3.65/month |
| One Secrets Manager secret | $0.40/month plus API calls |
| Pinned backups in S3 | Less than $0.01/month |

Total is about $22.42/month while running, excluding transfers, excess CPU
credits, API calls and taxes. This is an estimate, not a billing cap.

## Offline estate checks and synthetic extracts

```bash
python3 -m pip install pyyaml
python3 validation/static/run_all_checks.py
python3 validation/checks/run_deep_checks.py
python3 validation/static/run_negative_fixtures.py
python3 validation/checks/run_check_fixtures.py
python3 -m unittest discover -s deployment/rds -p 'test_*.py'
python3 generators/generate.py --scale small
python3 generators/generate.py --self-check
```

The synthetic generator writes files only; generated extracts are not loaded by
the native restore. Oracle, SSIS execution and expanded procedures retain the
runtime caveats documented in the inherited handover. Offline checks do not
substitute for executing those systems.

## Heritage and licence

The original `wwi-ssdt/`, `wwi-dw-ssdt/`, `wwi-ssis/`, applications and sample
scripts come from Microsoft's
[WideWorldImporters](https://github.com/microsoft/sql-server-samples/tree/master/samples/databases/wide-world-importers)
sample under the MIT licence. See `LICENSE` and `ATTRIBUTION.md`. All customers,
employees, suppliers and financial transactions are fictional sample data.
