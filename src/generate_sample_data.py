"""Generate a synthetic dataset in the *exact* Instacart Kaggle CSV format.

Why this exists
---------------
The real "Instacart Market Basket Analysis" dataset is ~3 GB and gated behind
a Kaggle login, so it can't be committed to a repo or fetched in CI. This
module produces a small, internally-consistent stand-in with the identical
schema and -- importantly -- *learnable* reorder behaviour, so the entire
pipeline (load -> clean -> RFM -> model -> dashboard) runs end-to-end out of
the box. Drop the real CSVs into data/raw/ and every downstream step is
unchanged; this generator simply becomes unnecessary.

Output files (data/raw/):
    departments.csv, aisles.csv, products.csv, product_prices.csv,
    orders.csv, order_products__prior.csv, order_products__train.csv
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

import config

log = logging.getLogger(__name__)

# Real Instacart department names (21).
DEPARTMENTS = [
    "frozen", "other", "bakery", "produce", "alcohol", "international",
    "beverages", "pets", "dry goods pasta", "bulk", "personal care",
    "meat seafood", "pantry", "breakfast", "canned goods", "dairy eggs",
    "household", "babies", "snacks", "deli", "missing",
]

# A representative aisle set mapped to departments: (aisle_name, department).
AISLES = [
    ("fresh fruits", "produce"), ("fresh vegetables", "produce"),
    ("packaged vegetables fruits", "produce"), ("yogurt", "dairy eggs"),
    ("milk", "dairy eggs"), ("cheese", "dairy eggs"), ("eggs", "dairy eggs"),
    ("water seltzer sparkling water", "beverages"), ("soft drinks", "beverages"),
    ("juice nectars", "beverages"), ("coffee", "beverages"),
    ("chips pretzels", "snacks"), ("crackers", "snacks"),
    ("cookies cakes", "snacks"), ("ice cream ice", "frozen"),
    ("frozen meals", "frozen"), ("bread", "bakery"), ("breakfast bakery", "bakery"),
    ("poultry counter", "meat seafood"), ("packaged meat", "meat seafood"),
    ("seafood counter", "meat seafood"), ("canned meals beans", "canned goods"),
    ("soup broth bouillon", "canned goods"), ("cereal", "breakfast"),
    ("baking ingredients", "pantry"), ("oils vinegars", "pantry"),
    ("spices seasonings", "pantry"), ("paper goods", "household"),
    ("cleaning products", "household"), ("hair care", "personal care"),
    ("vitamins supplements", "personal care"), ("baby food formula", "babies"),
    ("beers coolers", "alcohol"), ("red wines", "alcohol"),
    ("lunch meat", "deli"), ("fresh dips tapenades", "deli"),
    ("dog food care", "pets"), ("tea", "beverages"),
    ("pasta sauce", "dry goods pasta"), ("dry pasta", "dry goods pasta"),
]

# Per-department price model: (low, high) in dollars. Used to enrich products.
DEPT_PRICE_RANGE = {
    "produce": (0.5, 6), "dairy eggs": (1.5, 9), "beverages": (1.0, 11),
    "snacks": (1.5, 8), "frozen": (2.0, 12), "bakery": (1.5, 9),
    "meat seafood": (4.0, 22), "canned goods": (1.0, 6), "breakfast": (2.0, 9),
    "pantry": (1.0, 12), "household": (3.0, 16), "personal care": (3.0, 22),
    "babies": (5.0, 26), "alcohol": (6.0, 40), "deli": (3.0, 13),
    "pets": (5.0, 30), "dry goods pasta": (1.0, 8), "international": (2.0, 14),
    "bulk": (3.0, 20), "other": (1.0, 10), "missing": (1.0, 10),
}

ADJECTIVES = ["Organic", "Original", "Classic", "Fresh", "Premium", "Natural",
              "Whole", "Low-Fat", "Family Size", "Gluten-Free", "Spicy", "Lite"]


def _build_catalog(rng: np.random.Generator):
    departments = pd.DataFrame(
        {"department_id": range(1, len(DEPARTMENTS) + 1), "department": DEPARTMENTS}
    )
    dept_id = dict(zip(departments.department, departments.department_id))

    aisles = pd.DataFrame(
        {
            "aisle_id": range(1, len(AISLES) + 1),
            "aisle": [a for a, _ in AISLES],
            "department_id": [dept_id[d] for _, d in AISLES],
        }
    )

    n = config.SAMPLE["n_products"]
    aisle_choice = rng.integers(0, len(aisles), size=n)
    nouns = ["Almond Milk", "Banana", "Sparkling Water", "Hummus", "Granola",
             "Tortilla Chips", "Greek Yogurt", "Sourdough", "Ground Coffee",
             "Pasta Sauce", "Chicken Breast", "Cheddar", "Avocado", "Salsa",
             "Olive Oil", "Cereal", "Ice Cream", "Sparkling Lemonade",
             "Baby Wipes", "Dish Soap", "Paper Towels", "Dog Treats", "IPA"]
    products = pd.DataFrame(
        {
            "product_id": range(1, n + 1),
            "product_name": [
                f"{rng.choice(ADJECTIVES)} {rng.choice(nouns)} #{i}"
                for i in range(1, n + 1)
            ],
            "aisle_id": aisles.aisle_id.to_numpy()[aisle_choice],
            "department_id": aisles.department_id.to_numpy()[aisle_choice],
        }
    )

    # Prices: sample within the product's department band, rounded to .x9.
    dept_by_pid = dict(zip(products.product_id,
                           [DEPARTMENTS[d - 1] for d in products.department_id]))
    prices = []
    for pid in products.product_id:
        lo, hi = DEPT_PRICE_RANGE[dept_by_pid[pid]]
        raw = rng.uniform(lo, hi)
        prices.append(round(np.floor(raw) + 0.99, 2))
    product_prices = pd.DataFrame({"product_id": products.product_id, "price": prices})

    return departments, aisles, products, product_prices


def _build_orders(rng: np.random.Generator, products: pd.DataFrame):
    n_users = config.SAMPLE["n_users"]
    n_products = len(products)

    # Global product popularity ~ Zipf-ish: a few hero SKUs, a long tail.
    pop = 1.0 / np.arange(1, n_products + 1)
    rng.shuffle(pop)
    pop = pop / pop.sum()
    product_ids = products.product_id.to_numpy()

    orders_rows = []
    prior_rows = []
    train_rows = []
    order_id = 0

    for user_id in range(1, n_users + 1):
        n_orders = max(
            config.SAMPLE["min_orders_per_user"],
            int(rng.poisson(config.SAMPLE["mean_orders_per_user"])),
        )
        # Personal favourites: 5-25 SKUs this user keeps rebuying.
        n_fav = rng.integers(5, 26)
        favourites = rng.choice(product_ids, size=n_fav, replace=False, p=pop)
        fav_set = set(favourites.tolist())
        ever_bought: set[int] = set()

        for o in range(1, n_orders + 1):
            order_id += 1
            is_last = o == n_orders
            eval_set = "train" if is_last else "prior"
            dow = int(rng.integers(0, 7))
            hour = int(np.clip(rng.normal(13, 4), 0, 23))
            dspo = "" if o == 1 else int(np.clip(rng.gamma(2.0, 5.0), 0, 30))
            orders_rows.append(
                (order_id, user_id, eval_set, o, dow, hour, dspo)
            )

            basket = max(1, int(rng.poisson(config.SAMPLE["mean_basket_size"])))
            # ~70% of a basket is drawn from favourites, the rest explores.
            n_from_fav = min(len(favourites), int(round(basket * 0.7)))
            n_explore = basket - n_from_fav

            picks: list[int] = []
            if n_from_fav:
                # Reorder favourites with higher probability the more orders in.
                fav_pick = rng.choice(favourites,
                                      size=min(n_from_fav, len(favourites)),
                                      replace=False)
                picks.extend(int(p) for p in fav_pick)
            if n_explore:
                explore = rng.choice(product_ids, size=n_explore, replace=False, p=pop)
                picks.extend(int(p) for p in explore)
            # Dedup while preserving order.
            seen: set[int] = set()
            picks = [p for p in picks if not (p in seen or seen.add(p))]

            rows = prior_rows if eval_set == "prior" else train_rows
            for cart_pos, pid in enumerate(picks, start=1):
                reordered = 1 if pid in ever_bought else 0
                rows.append((order_id, pid, cart_pos, reordered))
            ever_bought.update(picks)

    orders = pd.DataFrame(
        orders_rows,
        columns=["order_id", "user_id", "eval_set", "order_number",
                 "order_dow", "order_hour_of_day", "days_since_prior_order"],
    )
    op_prior = pd.DataFrame(
        prior_rows,
        columns=["order_id", "product_id", "add_to_cart_order", "reordered"],
    )
    op_train = pd.DataFrame(
        train_rows,
        columns=["order_id", "product_id", "add_to_cart_order", "reordered"],
    )
    return orders, op_prior, op_train


def generate() -> None:
    rng = np.random.default_rng(config.SAMPLE["seed"])
    log.info("Generating catalog (%s products)...", config.SAMPLE["n_products"])
    departments, aisles, products, product_prices = _build_catalog(rng)

    log.info("Generating orders for %s users...", config.SAMPLE["n_users"])
    orders, op_prior, op_train = _build_orders(rng, products)

    out = config.DATA_RAW
    departments.to_csv(out / "departments.csv", index=False)
    aisles.to_csv(out / "aisles.csv", index=False)
    products.to_csv(out / "products.csv", index=False)
    product_prices.to_csv(out / "product_prices.csv", index=False)
    orders.to_csv(out / "orders.csv", index=False)
    op_prior.to_csv(out / "order_products__prior.csv", index=False)
    op_train.to_csv(out / "order_products__train.csv", index=False)

    log.info(
        "Done. %s orders | %s prior line-items | %s train line-items",
        f"{len(orders):,}", f"{len(op_prior):,}", f"{len(op_train):,}",
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    generate()
