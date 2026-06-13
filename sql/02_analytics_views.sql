-- ============================================================================
-- 02_analytics_views.sql  |  Reusable views for the analytics layer
-- ----------------------------------------------------------------------------
-- These push the heavy joins/aggregations into PostgreSQL so the Python layer
-- only pulls tidy, analysis-ready frames. Re-runnable (CREATE OR REPLACE).
-- ============================================================================

-- Per-order monetary value = sum of line-item prices in that order.
CREATE OR REPLACE VIEW v_order_value AS
SELECT
    o.order_id,
    o.user_id,
    o.eval_set,
    o.order_number,
    o.order_dow,
    o.order_hour_of_day,
    o.days_since_prior_order,
    COUNT(op.product_id)                       AS basket_size,
    SUM(pp.price)                              AS order_value
FROM orders o
JOIN order_products op ON op.order_id = o.order_id
JOIN product_prices  pp ON pp.product_id = op.product_id
GROUP BY o.order_id, o.user_id, o.eval_set, o.order_number,
         o.order_dow, o.order_hour_of_day, o.days_since_prior_order;

-- One row per customer: the raw ingredients for RFM. Recency is expressed as
-- the cumulative days between a customer's most recent order and "today"
-- (the max order date in the panel), reconstructed from days_since_prior_order.
CREATE OR REPLACE VIEW v_customer_orders AS
SELECT
    user_id,
    COUNT(*)                                   AS n_orders,
    SUM(order_value)                           AS total_spend,
    AVG(order_value)                           AS avg_order_value,
    SUM(basket_size)                           AS total_items,
    -- days_since_prior_order on the customer's LATEST order approximates
    -- how long they have been "quiet" since their previous purchase.
    MAX(order_number)                          AS last_order_number
FROM v_order_value
GROUP BY user_id;

-- Department-level loyalty signal: reorder rate per department.
CREATE OR REPLACE VIEW v_department_loyalty AS
SELECT
    d.department_id,
    d.department,
    COUNT(*)                                   AS line_items,
    SUM(op.reordered)                          AS reordered_items,
    ROUND(AVG(op.reordered)::numeric, 4)       AS reorder_rate,
    COUNT(DISTINCT o.user_id)                  AS unique_customers
FROM order_products op
JOIN orders   o ON o.order_id = op.order_id
JOIN products p ON p.product_id = op.product_id
JOIN departments d ON d.department_id = p.department_id
WHERE op.eval_set = 'prior'
GROUP BY d.department_id, d.department;
