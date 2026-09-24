-- ============================================================================
-- FILE: 02_core_business_questions.sql
-- PROJECT: Retail Inventory & Stockout Intelligence
-- PURPOSE: One query per core business question from the project blueprint.
--          Run AFTER 01_schema.sql and 03_sql_build.sql (needs the derived
--          fields / snapshot table built there).
-- DB: PostgreSQL
-- ============================================================================


-- ----------------------------------------------------------------------------
-- Q1: Which products are most frequently out of stock?
-- Counts the number of days each product had zero closing stock.
-- ----------------------------------------------------------------------------
SELECT
    p.product_id,
    p.product_name,
    COUNT(*) FILTER (WHERE i.closing_stock = 0) AS stockout_days
FROM inventory i
JOIN products p ON p.product_id = i.product_id
GROUP BY p.product_id, p.product_name
ORDER BY stockout_days DESC
LIMIT 20;


-- ----------------------------------------------------------------------------
-- Q2: Which stores have the highest stockout rate?
-- Stockout rate = days with zero stock / total tracked days for that store.
-- ----------------------------------------------------------------------------
SELECT
    s.store_id,
    s.region,
    ROUND(
        COUNT(*) FILTER (WHERE i.closing_stock = 0)::NUMERIC
        / NULLIF(COUNT(*), 0), 4
    ) AS stockout_rate
FROM inventory i
JOIN stores s ON s.store_id = i.store_id
GROUP BY s.store_id, s.region
ORDER BY stockout_rate DESC
LIMIT 20;


-- ----------------------------------------------------------------------------
-- Q3: How much estimated revenue is lost during stockouts?
-- Uses avg_daily_demand (30-day) x avg_selling_price on each stockout day.
-- See 03_sql_build.sql for how avg_daily_demand is derived.
-- ----------------------------------------------------------------------------
WITH avg_price AS (
    SELECT product_id, AVG(unit_price) AS avg_selling_price
    FROM sales
    GROUP BY product_id
),
demand AS (
    SELECT
        s.product_id,
        s.store_id,
        s.sale_date,
        SUM(s.units) AS daily_units_sold
    FROM sales s
    GROUP BY s.product_id, s.store_id, s.sale_date
),
rolling_demand AS (
    SELECT
        product_id,
        store_id,
        sale_date,
        AVG(daily_units_sold) OVER (
            PARTITION BY product_id, store_id
            ORDER BY sale_date
            ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
        ) AS avg_daily_demand_30d
    FROM demand
)
SELECT
    i.product_id,
    i.store_id,
    COUNT(*) FILTER (WHERE i.closing_stock = 0) AS stockout_days,
    ROUND(
        COUNT(*) FILTER (WHERE i.closing_stock = 0)
        * AVG(r.avg_daily_demand_30d) * AVG(ap.avg_selling_price)
    , 2) AS estimated_lost_revenue
FROM inventory i
LEFT JOIN rolling_demand r
    ON r.product_id = i.product_id AND r.store_id = i.store_id AND r.sale_date = i.date
LEFT JOIN avg_price ap ON ap.product_id = i.product_id
GROUP BY i.product_id, i.store_id
ORDER BY estimated_lost_revenue DESC NULLS LAST
LIMIT 20;
-- NOTE: This is an ESTIMATE based on historical demand, not observed loss.
-- Document this assumption clearly in the project README / Power BI notes page.


-- ----------------------------------------------------------------------------
-- Q4: Which SKUs are overstocked but slow-moving?
-- High closing stock + low units sold in last 30 days.
-- ----------------------------------------------------------------------------
WITH recent_sales AS (
    SELECT product_id, store_id, SUM(units) AS units_last_30d
    FROM sales
    WHERE sale_date >= (SELECT MAX(sale_date) FROM sales) - INTERVAL '30 days'
    GROUP BY product_id, store_id
),
latest_stock AS (
    SELECT DISTINCT ON (product_id, store_id)
        product_id, store_id, closing_stock, date
    FROM inventory
    ORDER BY product_id, store_id, date DESC
)
SELECT
    ls.product_id,
    ls.store_id,
    ls.closing_stock,
    COALESCE(rs.units_last_30d, 0) AS units_last_30d
FROM latest_stock ls
LEFT JOIN recent_sales rs
    ON rs.product_id = ls.product_id AND rs.store_id = ls.store_id
WHERE ls.closing_stock > 100                 -- overstock threshold, tune as needed
  AND COALESCE(rs.units_last_30d, 0) < 10     -- slow-moving threshold
ORDER BY ls.closing_stock DESC
LIMIT 20;


-- ----------------------------------------------------------------------------
-- Q5: Which products are likely to stock out within 7 days?
-- days_of_inventory = current stock / avg daily demand.
-- ----------------------------------------------------------------------------
WITH latest_stock AS (
    SELECT DISTINCT ON (product_id, store_id)
        product_id, store_id, closing_stock, date
    FROM inventory
    ORDER BY product_id, store_id, date DESC
),
avg_demand AS (
    SELECT product_id, store_id, AVG(units) AS avg_daily_demand
    FROM sales
    WHERE sale_date >= (SELECT MAX(sale_date) FROM sales) - INTERVAL '30 days'
    GROUP BY product_id, store_id
)
SELECT
    ls.product_id,
    ls.store_id,
    ls.closing_stock,
    ad.avg_daily_demand,
    ROUND(ls.closing_stock / NULLIF(ad.avg_daily_demand, 0), 1) AS days_of_inventory
FROM latest_stock ls
JOIN avg_demand ad
    ON ad.product_id = ls.product_id AND ad.store_id = ls.store_id
WHERE ls.closing_stock / NULLIF(ad.avg_daily_demand, 0) <= 7
ORDER BY days_of_inventory ASC
LIMIT 30;


-- ----------------------------------------------------------------------------
-- Q6: Which suppliers have long lead times?
-- ----------------------------------------------------------------------------
SELECT
    supplier_id,
    supplier_name,
    lead_time_days,
    minimum_order_qty
FROM suppliers
ORDER BY lead_time_days DESC;


-- ----------------------------------------------------------------------------
-- Q7: Which categories have the best sell-through?
-- Sell-through = units sold / (units sold + closing stock).
-- ----------------------------------------------------------------------------
WITH category_sales AS (
    SELECT p.category, SUM(s.units) AS total_units_sold
    FROM sales s
    JOIN products p ON p.product_id = s.product_id
    GROUP BY p.category
),
category_stock AS (
    SELECT p.category, SUM(i.closing_stock) AS total_closing_stock
    FROM inventory i
    JOIN products p ON p.product_id = i.product_id
    WHERE i.date = (SELECT MAX(date) FROM inventory)
    GROUP BY p.category
)
SELECT
    cs.category,
    cs.total_units_sold,
    COALESCE(cst.total_closing_stock, 0) AS total_closing_stock,
    ROUND(
        cs.total_units_sold::NUMERIC
        / NULLIF(cs.total_units_sold + COALESCE(cst.total_closing_stock, 0), 0), 4
    ) AS sell_through_rate
FROM category_sales cs
LEFT JOIN category_stock cst ON cst.category = cs.category
ORDER BY sell_through_rate DESC;


-- ----------------------------------------------------------------------------
-- Q8: Which stores carry too much inventory relative to demand?
-- Inventory-to-sales ratio per store.
-- ----------------------------------------------------------------------------
WITH store_stock AS (
    SELECT store_id, SUM(closing_stock) AS total_stock
    FROM inventory
    WHERE date = (SELECT MAX(date) FROM inventory)
    GROUP BY store_id
),
store_sales AS (
    SELECT store_id, SUM(units) AS total_units_sold
    FROM sales
    WHERE sale_date >= (SELECT MAX(sale_date) FROM sales) - INTERVAL '30 days'
    GROUP BY store_id
)
SELECT
    ss.store_id,
    ss.total_stock,
    COALESCE(sl.total_units_sold, 0) AS units_sold_30d,
    ROUND(ss.total_stock::NUMERIC / NULLIF(sl.total_units_sold, 0), 2) AS inventory_to_sales_ratio
FROM store_stock ss
LEFT JOIN store_sales sl ON sl.store_id = ss.store_id
ORDER BY inventory_to_sales_ratio DESC NULLS LAST
LIMIT 20;


-- ----------------------------------------------------------------------------
-- Q9: Are promotions associated with stockout risk?
-- Requires a 'is_promo' flag on sales; included here as a template query
-- to add once/if a promotions field is available in the dataset.
-- ----------------------------------------------------------------------------
-- SELECT
--     s.is_promo,
--     COUNT(*) FILTER (WHERE i.closing_stock = 0) AS stockout_days,
--     COUNT(*) AS total_days
-- FROM sales s
-- JOIN inventory i
--     ON i.product_id = s.product_id AND i.store_id = s.store_id AND i.date = s.sale_date
-- GROUP BY s.is_promo;


-- ----------------------------------------------------------------------------
-- Q10: Which products should be prioritized for replenishment?
-- Combines low days-of-inventory with high recent demand -> priority score.
-- ----------------------------------------------------------------------------
WITH latest_stock AS (
    SELECT DISTINCT ON (product_id, store_id)
        product_id, store_id, closing_stock
    FROM inventory
    ORDER BY product_id, store_id, date DESC
),
avg_demand AS (
    SELECT product_id, store_id, AVG(units) AS avg_daily_demand
    FROM sales
    WHERE sale_date >= (SELECT MAX(sale_date) FROM sales) - INTERVAL '30 days'
    GROUP BY product_id, store_id
)
SELECT
    ls.product_id,
    ls.store_id,
    ls.closing_stock,
    ad.avg_daily_demand,
    ROUND(ls.closing_stock / NULLIF(ad.avg_daily_demand, 0), 1) AS days_of_inventory,
    -- simple priority score: higher demand + lower days of inventory = higher priority
    ROUND(ad.avg_daily_demand / NULLIF(ls.closing_stock / NULLIF(ad.avg_daily_demand, 0), 0), 2) AS priority_score
FROM latest_stock ls
JOIN avg_demand ad
    ON ad.product_id = ls.product_id AND ad.store_id = ls.store_id
ORDER BY priority_score DESC NULLS LAST
LIMIT 30;
