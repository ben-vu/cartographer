-- ============================================================================
-- 01_schema.sql  |  Instacart Market Basket Analysis - relational schema
-- ----------------------------------------------------------------------------
-- The five core tables mirror the public Kaggle dataset 1:1 so you can drop in
-- the real CSVs unchanged. `product_prices` is an enrichment table we add
-- ourselves because the public dataset ships no prices, and RFM needs a
-- Monetary value. See README ("A note on Monetary") for the rationale.
-- ============================================================================

DROP TABLE IF EXISTS order_products CASCADE;
DROP TABLE IF EXISTS orders          CASCADE;
DROP TABLE IF EXISTS product_prices  CASCADE;
DROP TABLE IF EXISTS products        CASCADE;
DROP TABLE IF EXISTS aisles          CASCADE;
DROP TABLE IF EXISTS departments     CASCADE;

CREATE TABLE departments (
    department_id  INTEGER PRIMARY KEY,
    department     TEXT NOT NULL
);

CREATE TABLE aisles (
    aisle_id  INTEGER PRIMARY KEY,
    aisle     TEXT NOT NULL
);

CREATE TABLE products (
    product_id     INTEGER PRIMARY KEY,
    product_name   TEXT NOT NULL,
    aisle_id       INTEGER REFERENCES aisles(aisle_id),
    department_id  INTEGER REFERENCES departments(department_id)
);

-- Synthetic enrichment: one price per product (see README).
CREATE TABLE product_prices (
    product_id  INTEGER PRIMARY KEY REFERENCES products(product_id),
    price       NUMERIC(8, 2) NOT NULL
);

CREATE TABLE orders (
    order_id                INTEGER PRIMARY KEY,
    user_id                 INTEGER NOT NULL,
    eval_set                TEXT NOT NULL,           -- 'prior' | 'train'
    order_number            INTEGER NOT NULL,        -- 1 = first order for user
    order_dow               INTEGER NOT NULL,        -- 0=Sat ... 6=Fri (Kaggle coding)
    order_hour_of_day       INTEGER NOT NULL,
    days_since_prior_order  NUMERIC                  -- NULL on a user's first order
);

-- The two Kaggle files order_products__prior / __train are unioned into one
-- table with an `eval_set` discriminator, which is friendlier for SQL.
CREATE TABLE order_products (
    order_id          INTEGER NOT NULL REFERENCES orders(order_id),
    product_id        INTEGER NOT NULL REFERENCES products(product_id),
    add_to_cart_order INTEGER NOT NULL,
    reordered         SMALLINT NOT NULL,             -- 1 if user bought it before
    eval_set          TEXT NOT NULL,
    PRIMARY KEY (order_id, product_id)
);

-- ---------------------------------------------------------------------------
-- Indexes that the cleaning / feature-engineering queries lean on.
-- ---------------------------------------------------------------------------
CREATE INDEX idx_orders_user        ON orders(user_id);
CREATE INDEX idx_orders_evalset     ON orders(eval_set);
CREATE INDEX idx_op_order           ON order_products(order_id);
CREATE INDEX idx_op_product         ON order_products(product_id);
CREATE INDEX idx_products_dept      ON products(department_id);
CREATE INDEX idx_products_aisle     ON products(aisle_id);
