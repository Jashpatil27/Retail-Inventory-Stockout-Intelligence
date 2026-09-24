"""
FILE: 03_demand_analysis.py
PROJECT: Retail Inventory & Stockout Intelligence
PURPOSE: Build SKU-store demand profiles, a rolling-average demand baseline,
         and flag anomalies (sudden spikes or drops in sales).

INPUT: reads the cleaned `sales` table from PostgreSQL.
OUTPUT: writes `demand_profiles` and `demand_anomalies` tables back to
        PostgreSQL for use in Power BI / the replenishment script.
"""

import pandas as pd
from importlib import import_module

db_connection = import_module("01_db_connection")
get_engine = db_connection.get_engine


# ----------------------------------------------------------------------------
# STEP 1: Pull cleaned sales data and aggregate to product-store-day grain
# ----------------------------------------------------------------------------
def load_daily_sales(engine) -> pd.DataFrame:
    query = """
        SELECT product_id, store_id, sale_date, SUM(units) AS units_sold
        FROM sales
        GROUP BY product_id, store_id, sale_date
        ORDER BY product_id, store_id, sale_date
    """
    return pd.read_sql(query, engine)


# ----------------------------------------------------------------------------
# STEP 2: Build a rolling-average demand baseline per SKU-store
#   - 7-day and 30-day rolling mean
#   - rolling standard deviation (used for anomaly thresholds)
# ----------------------------------------------------------------------------
def build_demand_profile(daily: pd.DataFrame) -> pd.DataFrame:
    daily = daily.sort_values(["product_id", "store_id", "sale_date"])
    grouped = daily.groupby(["product_id", "store_id"])

    daily["rolling_avg_7d"] = grouped["units_sold"].transform(
        lambda x: x.rolling(window=7, min_periods=1).mean()
    )
    daily["rolling_avg_30d"] = grouped["units_sold"].transform(
        lambda x: x.rolling(window=30, min_periods=1).mean()
    )
    daily["rolling_std_30d"] = grouped["units_sold"].transform(
        lambda x: x.rolling(window=30, min_periods=3).std()
    )
    return daily


# ----------------------------------------------------------------------------
# STEP 3: Detect anomalies (sudden spikes or drops)
# A day is flagged if actual units sold is more than `z_threshold` standard
# deviations away from the 30-day rolling average.
# ----------------------------------------------------------------------------
def detect_anomalies(profile: pd.DataFrame, z_threshold: float = 2.5) -> pd.DataFrame:
    profile = profile.copy()
    profile["z_score"] = (
        (profile["units_sold"] - profile["rolling_avg_30d"])
        / profile["rolling_std_30d"].replace(0, pd.NA)
    )

    profile["anomaly_type"] = "Normal"
    profile.loc[profile["z_score"] > z_threshold, "anomaly_type"] = "Spike"
    profile.loc[profile["z_score"] < -z_threshold, "anomaly_type"] = "Drop"

    anomalies = profile[profile["anomaly_type"] != "Normal"].copy()
    return anomalies


# ----------------------------------------------------------------------------
# STEP 4: Write results back to PostgreSQL
# ----------------------------------------------------------------------------
def save_results(engine, profile: pd.DataFrame, anomalies: pd.DataFrame):
    profile.to_sql("demand_profiles", engine, if_exists="replace", index=False)
    anomalies.to_sql("demand_anomalies", engine, if_exists="replace", index=False)
    print("Saved:", len(profile), "demand profile rows |",
          len(anomalies), "flagged anomalies")


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    engine = get_engine()
    daily_sales = load_daily_sales(engine)
    demand_profile = build_demand_profile(daily_sales)
    anomalies = detect_anomalies(demand_profile)
    save_results(engine, demand_profile, anomalies)
