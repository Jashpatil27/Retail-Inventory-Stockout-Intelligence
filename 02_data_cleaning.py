"""
FILE: 02_data_cleaning.py
PROJECT: Retail Inventory & Stockout Intelligence
PURPOSE: Clean raw Kaggle sales/product/store CSVs with Pandas, then build
         the SIMULATED inventory layer (since raw transaction data has no
         true stock-on-hand), and load everything into PostgreSQL.

INPUT (expected in /data/raw/):
    sales_raw.csv     -> sale_id, date, store_id, product_id, units, unit_price
    products_raw.csv  -> product_id, category, brand, cost, supplier_id
    stores_raw.csv    -> store_id, region, store_type
    suppliers_raw.csv -> supplier_id, lead_time_days, minimum_order_qty

OUTPUT: cleaned tables loaded into PostgreSQL tables: sales, products,
        stores, suppliers, inventory (matches sql/01_schema.sql).
"""

import numpy as np
import pandas as pd
from pathlib import Path
from importlib import import_module

# Import the get_engine() helper from 01_db_connection.py
db_connection = import_module("01_db_connection")
get_engine = db_connection.get_engine


# ----------------------------------------------------------------------------
# STEP 1: Load raw CSVs
# ----------------------------------------------------------------------------
def load_raw_data(raw_dir=None):
    if raw_dir is None:
        raw_dir = Path(__file__).resolve().parent.parent / "data" / "raw"
    else:
        raw_dir = Path(raw_dir)
    sales = pd.read_csv(raw_dir / "sales_raw.csv")
    products = pd.read_csv(raw_dir / "products_raw.csv")
    stores = pd.read_csv(raw_dir / "stores_raw.csv")
    suppliers = pd.read_csv(raw_dir / "suppliers_raw.csv")
    return sales, products, stores, suppliers


# ----------------------------------------------------------------------------
# STEP 2: Clean the sales table
#   - parse dates, drop duplicates, remove negative/zero-price rows,
#     drop rows with missing keys, cap extreme outlier quantities.
# ----------------------------------------------------------------------------
def clean_sales(sales: pd.DataFrame) -> pd.DataFrame:
    sales = sales.copy()
    sales["date"] = pd.to_datetime(sales["date"], errors="coerce")
    sales = sales.dropna(subset=["date", "store_id", "product_id"])
    sales = sales.drop_duplicates(subset=["sale_id"])

    # Remove invalid transactions
    sales = sales[(sales["units"] > 0) & (sales["unit_price"] > 0)]

    # Cap extreme outliers at the 99.5th percentile (keeps genuine bulk
    # orders but removes data-entry errors like units = 99999)
    cap = sales["units"].quantile(0.995)
    sales["units"] = np.where(sales["units"] > cap, cap, sales["units"])

    sales = sales.rename(columns={"date": "sale_date"})
    return sales.reset_index(drop=True)


# ----------------------------------------------------------------------------
# STEP 3: Clean products / stores / suppliers
#   - trim whitespace, standardize category casing, fill missing cost
#     with category median, drop orphan foreign keys.
# ----------------------------------------------------------------------------
def clean_dimension_tables(products, stores, suppliers):
    products = products.copy()
    products["category"] = products["category"].str.strip().str.title()
    products["brand"] = products["brand"].str.strip()
    products["cost"] = products.groupby("category")["cost"].transform(
        lambda x: x.fillna(x.median())
    )
    products = products.dropna(subset=["product_id"])

    stores = stores.copy()
    stores["region"] = stores["region"].str.strip().str.title()
    stores = stores.dropna(subset=["store_id"])

    suppliers = suppliers.copy()
    suppliers["lead_time_days"] = suppliers["lead_time_days"].fillna(
        suppliers["lead_time_days"].median()
    )
    suppliers = suppliers.dropna(subset=["supplier_id"])

    return products, stores, suppliers


# ----------------------------------------------------------------------------
# STEP 4: Simulate the inventory layer.
# Logic: start each product-store with an assumed initial stock, subtract
# daily units sold, and add a periodic "receipt" (restock) whenever stock
# runs low. This is clearly a SIMULATION and must be labeled as such in
# the write-up / Power BI assumptions page.
# ----------------------------------------------------------------------------
def simulate_inventory(sales: pd.DataFrame, products: pd.DataFrame, suppliers: pd.DataFrame,
                        initial_stock: int = 30, reorder_point: int = 15,
                        reorder_qty: int = 80, default_lead_time: int = 10) -> pd.DataFrame:
    """
    Simulates daily stock with a REALISTIC lead-time gap: once stock drops
    below reorder_point, an order is placed but doesn't arrive until
    lead_time_days later (pulled from that product's supplier). This means
    stock CAN legitimately hit zero while waiting on a delayed order -- the
    earlier same-day-restock version never allowed a true stockout, which
    is why stockout_flag was always 0 downstream.

    NOTE: this still only steps through days that have a sales row for that
    product-store (not every calendar day). This is a simplification worth
    stating explicitly in your assumptions doc.
    """
    lead_time_map = (
        products.merge(suppliers, on="supplier_id", how="left")
        .set_index("product_id")["lead_time_days"]
        .to_dict()
    )

    daily = (
        sales.groupby(["product_id", "store_id", "sale_date"])["units"]
        .sum()
        .reset_index()
        .rename(columns={"units": "units_sold"})
    )

    records = []
    for (product_id, store_id), group in daily.groupby(["product_id", "store_id"]):
        group = group.sort_values("sale_date")
        lead_time_days = lead_time_map.get(product_id, default_lead_time)
        if pd.isna(lead_time_days):
            lead_time_days = default_lead_time

        stock = initial_stock
        pending_arrival = None  # date the next order lands, or None if no order in flight

        for _, row in group.iterrows():
            opening = stock
            receipts = 0

            # Order arrives once its lead time has passed
            if pending_arrival is not None and row["sale_date"] >= pending_arrival:
                receipts = reorder_qty
                pending_arrival = None

            stock = max(opening + receipts - row["units_sold"], 0)

            # Place a new order if stock is low and nothing is already in flight
            if stock < reorder_point and pending_arrival is None:
                pending_arrival = row["sale_date"] + pd.Timedelta(days=int(lead_time_days))

            records.append({
                "date": row["sale_date"],
                "store_id": store_id,
                "product_id": product_id,
                "opening_stock": opening,
                "receipts": receipts,
                "closing_stock": stock,
            })

    return pd.DataFrame(records)


# ----------------------------------------------------------------------------
# STEP 5: Load cleaned tables into PostgreSQL
# ----------------------------------------------------------------------------
def load_to_postgres(sales, products, stores, suppliers, inventory):
    engine = get_engine()
    suppliers.to_sql("suppliers", engine, if_exists="append", index=False)
    stores.to_sql("stores", engine, if_exists="append", index=False)
    products.to_sql("products", engine, if_exists="append", index=False)
    sales.to_sql("sales", engine, if_exists="append", index=False)
    inventory.to_sql("inventory", engine, if_exists="append", index=False)
    print("Load complete:",
          len(sales), "sales rows |",
          len(inventory), "inventory rows")


# ----------------------------------------------------------------------------
# MAIN: run the full cleaning + simulation + load pipeline
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    sales_raw, products_raw, stores_raw, suppliers_raw = load_raw_data()

    sales_clean = clean_sales(sales_raw)
    products_clean, stores_clean, suppliers_clean = clean_dimension_tables(
        products_raw, stores_raw, suppliers_raw
    )
    inventory_sim = simulate_inventory(sales_clean, products_clean, suppliers_clean)

    load_to_postgres(sales_clean, products_clean, stores_clean,
                      suppliers_clean, inventory_sim)
