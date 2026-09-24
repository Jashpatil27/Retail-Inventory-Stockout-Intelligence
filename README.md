# Retail Inventory & Stockout Intelligence

PostgreSQL + Python + Power BI + DAX portfolio project.

## Folder structure
```
retail_inventory_project/
├── data/
│   └── raw/                     <- put sales_raw.csv, products_raw.csv,
│                                    stores_raw.csv, suppliers_raw.csv here
├── sql/
│   ├── 01_schema.sql            <- creates all tables
│   ├── 02_core_business_questions.sql
│   └── 03_sql_build.sql         <- aggregates, rolling avg, risk, snapshot table
├── python/
│   ├── 01_db_connection.py      <- shared DB connection helper
│   ├── 02_data_cleaning.py      <- cleans CSVs + simulates inventory + loads to DB
│   ├── 03_demand_analysis.py    <- rolling demand baseline + anomaly detection
│   └── 04_replenishment_table.py<- builds the final risk-scored priority table
└── requirements.txt
```

## 1. Get the dataset
Download the Kaggle "Predict Future Sales" competition data (or any retail
transaction dataset with sale_id, date, store_id, product_id, units,
unit_price). Place the raw CSVs in `data/raw/`. Since this dataset has no
true stock-on-hand, `02_data_cleaning.py` **simulates** an inventory layer —
this is called out explicitly so it's never mistaken for real stock data.

## 2. Set up PostgreSQL
Install PostgreSQL locally (or use a free-tier cloud instance, e.g. Supabase,
Neon, or Render). Create a database:
```sql
CREATE DATABASE retail_inventory;
```
Then run the schema:
```bash
psql -U postgres -d retail_inventory -f sql/01_schema.sql
```

## 3. Connect Python to PostgreSQL
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Create a `.env` file in the project root (never commit this to GitHub):
   ```
   DB_HOST=localhost
   DB_PORT=5432
   DB_NAME=retail_inventory
   DB_USER=postgres
   DB_PASSWORD=your_password
   ```
3. Test the connection:
   ```bash
   cd python
   python 01_db_connection.py
   # Expected output: "Connected successfully to: retail_inventory"
   ```
   Under the hood this uses SQLAlchemy's `create_engine()` with a
   `postgresql+psycopg2://user:password@host:port/dbname` connection string —
   the standard way to bridge Python and PostgreSQL. `pandas.read_sql()` and
   `DataFrame.to_sql()` both accept this engine directly, so every script
   after this one reads/writes to Postgres through plain pandas calls.

## 4. Run the pipeline in order
```bash
cd python
python 02_data_cleaning.py        # clean raw CSVs, simulate inventory, load to DB
python 03_demand_analysis.py      # build demand profiles, flag anomalies
python 04_replenishment_table.py  # build the risk-scored replenishment table
```
Then run the SQL build layer against the now-populated database:
```bash
psql -U postgres -d retail_inventory -f ../sql/03_sql_build.sql
psql -U postgres -d retail_inventory -f ../sql/02_core_business_questions.sql
```

## 5. Data cleaning summary (what `02_data_cleaning.py` actually does)
- **Sales**: parses dates, drops duplicate `sale_id`s, removes rows with
  zero/negative units or price, caps extreme outlier quantities at the
  99.5th percentile, drops rows with missing store/product keys.
- **Products**: trims whitespace, title-cases categories, fills missing
  `cost` with the category median, drops rows with no `product_id`.
- **Stores / Suppliers**: trims whitespace, standardizes region names,
  fills missing `lead_time_days` with the median, drops orphan rows.
- **Inventory (simulated)**: since the raw dataset has no stock-on-hand,
  each product-store starts at an assumed initial stock, subtracts daily
  units sold, and triggers a restock once stock drops below a reorder
  point. This assumption is documented so it's never presented as real
  observed inventory.

## 6. Connect Power BI
In Power BI Desktop: **Get Data → PostgreSQL database** → enter host/port/
database → point it at `powerbi_daily_snapshot` and `replenishment_priorities`
(both created by the SQL/Python scripts above) as your primary data sources,
then build the 3 report pages and DAX measures from the project blueprint.

## 7. Important note on "Estimated Lost Revenue"
This figure is a **modeled estimate** (historical average demand × stockout
days × average price), not observed revenue loss. Label it as such
everywhere it appears — in SQL comments, Python docstrings, and on the
Power BI assumptions page.
