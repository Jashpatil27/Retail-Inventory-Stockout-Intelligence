# Retail Inventory & Stockout Analytics

An end-to-end analytics project that takes raw retail sales data through a **Python + PostgreSQL** pipeline and turns it into a **3-page Power BI dashboard** showing stockout risk, overstock, and which products to reorder first.

**Stack:** Python · PostgreSQL · SQL · Power BI (DAX) · Argos Translate

---

## Business problem

A retailer loses revenue in two opposite ways: products run out (lost sales) or sit unsold on shelves (tied-up cash). This project answers three questions:

1. **How bad is the stockout problem, and where is it worst?** (by date, region, category)
2. **Which SKUs are overstocked or moving too slowly?**
3. **Which SKU–store combinations need replenishment first, and what action should be taken?**

---

## Dashboard preview

### Page 1: Inventory Command Center
KPI summary, stockout trend over time, risk distribution, regional performance and the top SKUs at risk.

<img width="1180" height="667" alt="inventory 1" src="https://github.com/user-attachments/assets/a79dc1f9-24a8-4300-8187-1869348aef7f" />


### Page 2: SKU & Store Analysis
Category-level demand and revenue, demand vs stock per SKU, and a list of slow-moving / overstocked products, with slicers for store, category and risk.

<img width="1182" height="670" alt="inventory 2" src="https://github.com/user-attachments/assets/208cf858-ef2a-4879-a4fa-e0f7f3360ef3" />


### Page 3: Replenishment Priorities
A prioritised reorder list with risk score, lead time and a recommended action for each SKU–store.

<img width="1172" height="670" alt="inventory 3" src="https://github.com/user-attachments/assets/0a6d3ba1-235c-4adb-8c2e-8602a82f0612" />


---

## Key findings

| Finding | Value |
|---|---|
| Total revenue analysed | **3.22bn** (assumed RUB, see notes) |
| Units sold | **~3M** |
| Overall stockout rate | **1.14%** |
| Average days of inventory | **31.27 days** |
| Estimated revenue lost to stockouts | **119.23M** |
| SKUs tracked | **~22K** |
| Highest stockout rates by region | **Digital (3.5%)** and **Online Shop (3.1%)**, roughly 3x the overall rate |
| Risk mix | **~72% Low risk**, **~24% Overstock risk**, only a small share Medium / High / Stocked out |
| Replenishment list | **168 High-risk** and **1,864 Medium-risk** SKU–store rows out of ~424K, so urgent action is concentrated in a very small group |
| Top revenue categories | Games - Ps3 (0.39bn), Games - Ps4 (0.33bn), Game Consoles (0.26bn) |

**Takeaway:** stockouts are rare overall but concentrated in online channels, while about a quarter of inventory is overstocked. Working capital is tied up in slow-moving items (for example, collector's editions of PC games) even as a small set of fast-moving SKUs needs emergency reorders.

---

## Tech stack

| Layer | Tools |
|---|---|
| Data source | Kaggle, [Predict Future Sales](https://www.kaggle.com/c/competitive-data-science-predict-future-sales) |
| Preparation & cleaning | Python (pandas), Argos Translate (Russian to English, run locally) |
| Storage & modelling | PostgreSQL, SQL |
| Analysis | Python (demand analysis, replenishment logic) |
| Visualisation | Power BI Desktop, DAX, star-schema data model |

---

## Pipeline

```
Kaggle CSVs
    │
    ▼
00_prepare_kaggle_data.py   → builds inventory dataset, translates product names,
    │                          categories and regions to English (cached locally)
    ▼
02_data_cleaning.py         → cleans and validates the data, loads it to PostgreSQL
    │
    ▼
03_demand_analysis.py       → rolling demand, days of inventory, stockout flags, risk class
    │
    ▼
04_replenishment_table.py   → risk score, lead time, recommended action per SKU–store
    │
    ▼
sql/03_sql_build.sql        → builds the reporting tables used by Power BI
    │
    ▼
Power BI dashboard          → 3 pages of KPIs, trends and priority lists
```

`01_db_connection.py` only tests the database connection.

---

## Data model (Power BI)

A star schema, with shared dimensions filtering three fact tables:

- **Fact tables:** `sales`, `powerbi_daily_snapshot`, `replenishment_priorities`
- **Dimensions:** `DimProduct` (product_id, product_name, category), `DimStore` (store_id, region), `DateTable`
- All relationships are **one-to-many, single direction**, from dimension to fact.

Slicing and grouping fields come from the dimensions, so filters flow correctly to every fact table (this fixed an early bug where Revenue by Category showed the same total for every category).

---

## Key metrics

| Metric | Definition |
|---|---|
| **Revenue** | `SUMX(sales, units × unit_price)` |
| **Units Sold** | Sum of units sold |
| **Stockout Rate** | Stockout days ÷ total SKU-day rows |
| **Days of Inventory** | Average days of stock remaining at the current demand rate |
| **Estimated Lost Revenue** | Expected demand × price on days a SKU was out of stock |
| **Risk tier / risk score** | Combines days of inventory, demand volatility and lead time (see `python/04_replenishment_table.py`) |

The DAX measures live in the `.pbix` file under the `dax measures` table.

---

## Repository structure

```
retail_inventory_project/
├── README.md
├── requirements.txt
├── .env.example
├── python/
│   ├── 00_prepare_kaggle_data.py
│   ├── 01_db_connection.py
│   ├── 02_data_cleaning.py
│   ├── 03_demand_analysis.py
│   └── 04_replenishment_table.py
├── sql/
│   └── 03_sql_build.sql
├── powerbi/
│   ├── Retail_inventory_report.pbix
│   └── theme.json
├── data/
│   ├── raw/translation_cache.json
│   └── sample/            # small sample files only
└── docs/
    └── screenshots/
```

---

## How to run

1. **Get the data.** Download the Kaggle *Predict Future Sales* files and place them in `data/raw/`.
2. **Install dependencies.**
   ```bash
   pip install -r requirements.txt
   ```
3. **Configure the database.** Copy `.env.example` to `.env` and fill in your PostgreSQL details.
4. **Run the pipeline in order.**
   ```bash
   python python/00_prepare_kaggle_data.py
   python python/02_data_cleaning.py
   python python/03_demand_analysis.py
   python python/04_replenishment_table.py
   ```
5. **Build the reporting tables** by running `sql/03_sql_build.sql` in PostgreSQL.
6. **Open `powerbi/Retail_inventory_report.pbix`**, update the data source to your database, and click **Refresh**.

The first run of step 4 downloads the Russian to English translation model for Argos Translate, and translations are cached in `data/raw/translation_cache.json`, so later runs are fast.

---

## Notes and assumptions

- **Currency:** the source data is from a Russian retailer, so amounts are assumed to be in **rubles (RUB)**. The dataset does not state the currency.
- **Translation:** product names, categories and regions were machine-translated. A few product names still contain brand names or mixed-language text.
- **Period:** the data covers January 2013 to October 2015.
- **Data size:** raw and processed CSVs are not included because of size. Use the Kaggle link above.

---

## Possible improvements

- Forecast demand with a time-series model instead of a rolling average
- Optimise reorder quantities using safety stock and lead-time variability
- Schedule the pipeline (Airflow or cron) and enable automatic Power BI refresh
- Add unit tests for the risk-scoring logic

---

## Author

**Jash Patil**
Aspiring data analyst · Python · SQL · Power BI
