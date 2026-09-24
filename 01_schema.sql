-- ============================================================================
-- FILE: 01_schema.sql
-- PROJECT: Retail Inventory & Stockout Intelligence
-- PURPOSE: Create the core relational tables used by the whole project.
--          Run this FIRST, before loading any data.
-- DB: PostgreSQL
-- ============================================================================

-- Drop tables if re-running this script during development
DROP TABLE IF EXISTS inventory CASCADE;
DROP TABLE IF EXISTS sales CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS stores CASCADE;
DROP TABLE IF EXISTS suppliers CASCADE;

-- ----------------------------------------------------------------------------
-- TABLE: suppliers
-- Holds supplier-level info used for reorder / lead-time analysis.
-- ----------------------------------------------------------------------------
CREATE TABLE suppliers (
    supplier_id         VARCHAR(20) PRIMARY KEY,
    supplier_name       VARCHAR(100),
    lead_time_days      INT NOT NULL,
    minimum_order_qty   INT NOT NULL
);

-- ----------------------------------------------------------------------------
-- TABLE: stores
-- One row per physical / online store location.
-- ----------------------------------------------------------------------------
CREATE TABLE stores (
    store_id     VARCHAR(20) PRIMARY KEY,
    region       VARCHAR(50),
    store_type   VARCHAR(50)   -- e.g. 'Flagship', 'Mall', 'Outlet', 'Online'
);

-- ----------------------------------------------------------------------------
-- TABLE: products
-- One row per SKU. Linked to a supplier.
-- ----------------------------------------------------------------------------
CREATE TABLE products (
    product_id    VARCHAR(20) PRIMARY KEY,
    product_name  TEXT,
    category      VARCHAR(50),
    brand         VARCHAR(50),
    cost          NUMERIC(10,2) NOT NULL,
    supplier_id   VARCHAR(20) REFERENCES suppliers(supplier_id)
);

-- ----------------------------------------------------------------------------
-- TABLE: sales
-- Transaction-level sales. Grain = one row per sale line item.
-- ----------------------------------------------------------------------------
CREATE TABLE sales (
    sale_id      BIGINT PRIMARY KEY,
    sale_date    DATE NOT NULL,
    store_id     VARCHAR(20) REFERENCES stores(store_id),
    product_id   VARCHAR(20) REFERENCES products(product_id),
    units        INT NOT NULL CHECK (units >= 0),
    unit_price   NUMERIC(10,2) NOT NULL CHECK (unit_price >= 0)
);

-- ----------------------------------------------------------------------------
-- TABLE: inventory
-- Daily stock position per store-product. This is the SIMULATED layer
-- (see python/02_data_cleaning.py) since raw Kaggle sales data does not
-- include true stock-on-hand.
-- ----------------------------------------------------------------------------
CREATE TABLE inventory (
    date            DATE NOT NULL,
    store_id        VARCHAR(20) REFERENCES stores(store_id),
    product_id      VARCHAR(20) REFERENCES products(product_id),
    opening_stock   INT NOT NULL,
    receipts        INT NOT NULL DEFAULT 0,
    closing_stock   INT NOT NULL,
    PRIMARY KEY (date, store_id, product_id)
);

-- ----------------------------------------------------------------------------
-- Helpful indexes for the rolling-average / date-range queries used later.
-- ----------------------------------------------------------------------------
CREATE INDEX idx_sales_date            ON sales(sale_date);
CREATE INDEX idx_sales_product_store   ON sales(product_id, store_id);
CREATE INDEX idx_inventory_date        ON inventory(date);
CREATE INDEX idx_inventory_prod_store  ON inventory(product_id, store_id);
