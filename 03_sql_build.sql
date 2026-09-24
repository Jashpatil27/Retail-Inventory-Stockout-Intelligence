-- ============================================================================
-- FILE: 03_sql_build.sql
-- PROJECT: Retail Inventory & Stockout Intelligence
-- PURPOSE: The "SQL Build" pipeline from the blueprint — aggregates, rolling
--          averages, risk classification, and the final Power BI snapshot
--          table. Run AFTER 01_schema.sql and after loading cleaned data
--          (python/02_data_cleaning.py).
-- DB: PostgreSQL
-- ============================================================================


-- ----------------------------------------------------------------------------
-- STEP 1: Daily product-store sales aggregate.
-- Collapses transaction-level sales into one row per product-store-day.
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS daily_sales_agg;
CREATE TABLE daily_sales_agg AS
SELECT
    product_id,
    store_id,
    sale_date,
    SUM(units)                  AS daily_units_sold,
    SUM(units * unit_price)     AS daily_revenue,
    AVG(unit_price)             AS avg_unit_price
FROM sales
GROUP BY product_id, store_id, sale_date;

CREATE INDEX idx_daily_sales_agg ON daily_sales_agg(product_id, store_id, sale_date);


-- ----------------------------------------------------------------------------
-- STEP 2: 7-day and 30-day rolling average demand using window functions.
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS demand_rolling;
CREATE TABLE demand_rolling AS
SELECT
    product_id,
    store_id,
    sale_date,
    daily_units_sold,
    AVG(daily_units_sold) OVER (
        PARTITION BY product_id, store_id
        ORDER BY sale_date
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS avg_daily_demand_7d,
    AVG(daily_units_sold) OVER (
        PARTITION BY product_id, store_id
        ORDER BY sale_date
        ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
    ) AS avg_daily_demand_30d,
    -- demand volatility, used later in the stockout risk score
    STDDEV(daily_units_sold) OVER (
        PARTITION BY product_id, store_id
        ORDER BY sale_date
        ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
    ) AS demand_stddev_30d
FROM daily_sales_agg;


-- ----------------------------------------------------------------------------
-- STEP 3: Days of inventory = current stock / average daily demand.
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS inventory_with_demand;
CREATE TABLE inventory_with_demand AS
SELECT
    i.date,
    i.store_id,
    i.product_id,
    i.opening_stock,
    i.receipts,
    i.closing_stock,
    dr.avg_daily_demand_7d,
    dr.avg_daily_demand_30d,
    dr.demand_stddev_30d,
    ROUND(i.closing_stock / NULLIF(dr.avg_daily_demand_30d, 0), 1) AS days_of_inventory
FROM inventory i
LEFT JOIN demand_rolling dr
    ON dr.product_id = i.product_id
   AND dr.store_id   = i.store_id
   AND dr.sale_date  = i.date;


-- ----------------------------------------------------------------------------
-- STEP 4: Classify stockout risk with CASE WHEN.
-- Thresholds are illustrative — document these as assumptions.
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS inventory_risk;
CREATE TABLE inventory_risk AS
SELECT
    *,
    CASE
        WHEN closing_stock = 0                       THEN 'Stocked Out'
        WHEN days_of_inventory <= 3                  THEN 'High Risk'
        WHEN days_of_inventory <= 7                  THEN 'Medium Risk'
        WHEN days_of_inventory <= 30                 THEN 'Low Risk'
        WHEN days_of_inventory > 30                  THEN 'Overstock Risk'
        ELSE 'Unknown'
    END AS stockout_risk
FROM inventory_with_demand;


-- ----------------------------------------------------------------------------
-- STEP 5: Rank SKUs by estimated lost revenue (stockout days x demand x price).
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS lost_revenue_ranked;
CREATE TABLE lost_revenue_ranked AS
WITH lost AS (
    SELECT
        ir.product_id,
        ir.store_id,
        COUNT(*) FILTER (WHERE ir.closing_stock = 0) AS stockout_days,
        AVG(ir.avg_daily_demand_30d) AS avg_daily_demand,
        AVG(dsa.avg_unit_price) AS avg_unit_price
    FROM inventory_risk ir
    LEFT JOIN daily_sales_agg dsa
        ON dsa.product_id = ir.product_id AND dsa.store_id = ir.store_id
    GROUP BY ir.product_id, ir.store_id
)
SELECT
    *,
    ROUND(stockout_days * avg_daily_demand, 1) AS estimated_lost_units,
    ROUND(stockout_days * avg_daily_demand * avg_unit_price, 2) AS estimated_lost_revenue,
    RANK() OVER (ORDER BY stockout_days * avg_daily_demand * avg_unit_price DESC NULLS LAST) AS lost_revenue_rank
FROM lost;


-- ----------------------------------------------------------------------------
-- STEP 6: Compare store performance using CTEs.
-- ----------------------------------------------------------------------------
WITH store_revenue AS (
    SELECT store_id, SUM(daily_revenue) AS total_revenue
    FROM daily_sales_agg
    GROUP BY store_id
),
store_stockouts AS (
    SELECT store_id, COUNT(*) FILTER (WHERE closing_stock = 0) AS stockout_days
    FROM inventory_risk
    GROUP BY store_id
)
SELECT
    sr.store_id,
    sr.total_revenue,
    COALESCE(so.stockout_days, 0) AS stockout_days
FROM store_revenue sr
LEFT JOIN store_stockouts so ON so.store_id = sr.store_id
ORDER BY sr.total_revenue DESC;


-- ----------------------------------------------------------------------------
-- STEP 7: Daily inventory snapshot table for Power BI.
-- This is the single flattened table the Power BI report connects to.
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS powerbi_daily_snapshot;
CREATE TABLE powerbi_daily_snapshot AS
SELECT
    ir.date,
    ir.store_id,
    s.region,
    s.store_type,
    ir.product_id,
    p.product_name,
    p.category,
    p.brand,
    ir.opening_stock,
    ir.receipts,
    ir.closing_stock,
    ir.avg_daily_demand_7d,
    ir.avg_daily_demand_30d,
    ir.demand_stddev_30d,
    ir.days_of_inventory,
    ir.stockout_risk,
    CASE WHEN ir.closing_stock = 0 THEN 1 ELSE 0 END AS stockout_flag
FROM inventory_risk ir
JOIN stores s   ON s.store_id = ir.store_id
JOIN products p ON p.product_id = ir.product_id;

CREATE INDEX idx_snapshot_date ON powerbi_daily_snapshot(date);


-- ----------------------------------------------------------------------------
-- STEP 8: Current period vs prior period comparison (e.g. last 30 vs prior 30 days).
-- ----------------------------------------------------------------------------
WITH current_period AS (
    SELECT product_id, store_id, SUM(daily_units_sold) AS units_current
    FROM daily_sales_agg
    WHERE sale_date >= (SELECT MAX(sale_date) FROM daily_sales_agg) - INTERVAL '30 days'
    GROUP BY product_id, store_id
),
prior_period AS (
    SELECT product_id, store_id, SUM(daily_units_sold) AS units_prior
    FROM daily_sales_agg
    WHERE sale_date >= (SELECT MAX(sale_date) FROM daily_sales_agg) - INTERVAL '60 days'
      AND sale_date <  (SELECT MAX(sale_date) FROM daily_sales_agg) - INTERVAL '30 days'
    GROUP BY product_id, store_id
)
SELECT
    cp.product_id,
    cp.store_id,
    cp.units_current,
    COALESCE(pp.units_prior, 0) AS units_prior,
    ROUND(
        (cp.units_current - COALESCE(pp.units_prior, 0))::NUMERIC
        / NULLIF(pp.units_prior, 0) * 100, 1
    ) AS pct_change
FROM current_period cp
LEFT JOIN prior_period pp
    ON pp.product_id = cp.product_id AND pp.store_id = cp.store_id
ORDER BY pct_change DESC NULLS LAST
LIMIT 30;
