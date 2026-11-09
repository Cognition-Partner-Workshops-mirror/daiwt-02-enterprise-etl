# Legacy warehouse baseline

`golden/` is an inspection export of the original Microsoft WideWorldImporters
v1.0 Standard backups pinned in `deployment/rds/seeds.json`, restored into SQL
Server. It is not output from executing the expanded SSIS or Oracle estate.

| Export | Contents |
| --- | --- |
| `golden/row-counts.json` | Exact `COUNT_BIG(*)` for every non-system table: 48 OLTP tables and 29 warehouse tables |
| `golden/sale-by-day.csv` | Warehouse sale row counts and tax-inclusive totals by invoice date |
| `golden/customer-history.csv` | Warehouse customer surrogate/business keys, names and validity dates, including the unknown member |

The complete historical baseline remains the pinned warehouse `.bak` in the
stack's private S3 bucket, not only these selected CSV extracts. The OLTP backup
is its paired source snapshot. All sample identities and transactions are
fictional; the upstream MIT licence and attribution apply.

To refresh the exports from an unchanged restored pair:

```bash
python3 deployment/rds/estate.py export-golden
```

Reset requires exclusive access to both databases. Coordinate with shared
consumers before `python3 deployment/rds/estate.py reset --confirm-reset`.
