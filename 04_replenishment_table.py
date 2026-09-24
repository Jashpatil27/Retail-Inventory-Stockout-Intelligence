"""
FILE: 04_replenishment_table.py
PROJECT: Retail Inventory & Stockout Intelligence
PURPOSE: Generate the final replenishment input table:
         SKU, store, current stock, average daily demand, days of inventory,
         demand volatility, supplier lead time, and a stockout risk score.
         This is the table Power BI Page 3 (Replenishment Priorities) reads.

INPUT: PostgreSQL tables -> inventory, demand_profiles, products, suppliers
OUTPUT: PostgreSQL table -> replenishment_priorities
"""

import pandas as pd
from importlib import import_module

db_connection = import_module("01_db_connection")
get_engine = db_connection.get_engine


# ----------------------------------------------------------------------------
# STEP 1: Pull the latest stock position per product-store
# ----------------------------------------------------------------------------
def load_latest_stock(engine) -> pd.DataFrame:
    query = """
        SELECT DISTINCT ON (product_id, store_id)
            product_id, store_id, closing_stock, date
        FROM inventory
        ORDER BY product_id, store_id, date DESC
    """
    return pd.read_sql(query, engine)


# ----------------------------------------------------------------------------
# STEP 2: Pull the latest demand profile (30-day avg + volatility) per SKU-store
# ----------------------------------------------------------------------------
def load_latest_demand(engine) -> pd.DataFrame:
    query = """
        SELECT DISTINCT ON (product_id, store_id)
            product_id, store_id, rolling_avg_30d, rolling_std_30d
        FROM demand_profiles
        ORDER BY product_id, store_id, sale_date DESC
    """
    return pd.read_sql(query, engine)


# ----------------------------------------------------------------------------
# STEP 3: Pull supplier lead times (joined through products)
# ----------------------------------------------------------------------------
def load_supplier_lead_times(engine) -> pd.DataFrame:
    query = """
        SELECT p.product_id, s.lead_time_days
        FROM products p
        JOIN suppliers s ON s.supplier_id = p.supplier_id
    """
    return pd.read_sql(query, engine)


# ----------------------------------------------------------------------------
# STEP 4: Combine everything and compute the Stockout Risk Score.
# Risk score weights:
#   - low days_of_inventory      -> higher risk
#   - high demand volatility     -> higher risk
#   - long supplier lead time    -> higher risk
# Score is normalized 0-100 for easy interpretation in Power BI.
# ----------------------------------------------------------------------------
def build_replenishment_table(stock, demand, lead_times) -> pd.DataFrame:
    df = stock.merge(demand, on=["product_id", "store_id"], how="left")
    df = df.merge(lead_times, on="product_id", how="left")

    df["avg_daily_demand"] = df["rolling_avg_30d"].fillna(0)
    df["demand_volatility"] = df["rolling_std_30d"].fillna(0)
    df["lead_time_days"] = df["lead_time_days"].fillna(df["lead_time_days"].median())

    df["days_of_inventory"] = (
        df["closing_stock"] / df["avg_daily_demand"].replace(0, pd.NA)
    ).fillna(999)  # 999 = effectively "no risk, no recent demand"

    # --- Risk score components, each normalized to 0-1 then weighted ---
    inv_risk = (1 / (1 + df["days_of_inventory"])).clip(0, 1)
    volatility_risk = (
        df["demand_volatility"] / df["demand_volatility"].max()
        if df["demand_volatility"].max() > 0 else 0
    )
    lead_time_risk = df["lead_time_days"] / df["lead_time_days"].max()

    df["stockout_risk_score"] = round(
        (0.5 * inv_risk + 0.3 * volatility_risk + 0.2 * lead_time_risk) * 100, 1
    )

    # --- Risk tier for easy filtering in Power BI ---
    df["risk_tier"] = pd.cut(
        df["stockout_risk_score"],
        bins=[-1, 33, 66, 100],
        labels=["Low", "Medium", "High"],
    )

    # --- Recommended action ---
    def recommend_action(row):
        if row["closing_stock"] == 0:
            return "Emergency reorder"
        if row["risk_tier"] == "High":
            return "Reorder now"
        if row["risk_tier"] == "Medium":
            return "Monitor closely"
        return "No action needed"

    df["recommended_action"] = df.apply(recommend_action, axis=1)

    cols = [
        "product_id", "store_id", "closing_stock", "avg_daily_demand",
        "days_of_inventory", "demand_volatility", "lead_time_days",
        "stockout_risk_score", "risk_tier", "recommended_action",
    ]
    return df[cols].sort_values("stockout_risk_score", ascending=False)


# ----------------------------------------------------------------------------
# STEP 5: Save to PostgreSQL for Power BI to consume
# ----------------------------------------------------------------------------
def save_to_postgres(engine, df: pd.DataFrame):
    df.to_sql("replenishment_priorities", engine, if_exists="replace", index=False)
    print("Saved replenishment_priorities:", len(df), "rows")


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    engine = get_engine()
    stock = load_latest_stock(engine)
    demand = load_latest_demand(engine)
    lead_times = load_supplier_lead_times(engine)

    replenishment_df = build_replenishment_table(stock, demand, lead_times)
    save_to_postgres(engine, replenishment_df)
