"""
FILE: 00_prepare_kaggle_data.py
PROJECT: Retail Inventory & Stockout Intelligence
PURPOSE: Convert the REAL Kaggle "Predict Future Sales" competition files
         into the sales_raw / products_raw / stores_raw / suppliers_raw
         format that 02_data_cleaning.py expects.

WHY THIS SCRIPT EXISTS:
The Kaggle dataset only ships sales_train.csv, items.csv,
item_categories.csv, and shops.csv. It has NO supplier data and NO true
cost/inventory data. So this script:
  1. Reshapes the real Kaggle columns into our sales/products/stores format.
  2. SYNTHESIZES supplier_id, cost, and lead_time_days, since the real
     dataset doesn't provide them. This is a clearly labeled assumption
     layer, exactly like the inventory simulation in 02_data_cleaning.py.

INPUT (place these 4 files, downloaded from Kaggle, into data/raw_kaggle/):
    sales_train.csv      -> date, date_block_num, shop_id, item_id, item_price, item_cnt_day
    items.csv             -> item_name, item_id, item_category_id
    item_categories.csv   -> item_category_name, item_category_id
    shops.csv              -> shop_name, shop_id

OUTPUT: writes sales_raw.csv, products_raw.csv, stores_raw.csv,
        suppliers_raw.csv into data/raw/ (ready for 02_data_cleaning.py).
"""

import json
from pathlib import Path

# Load Argos before NumPy/Pandas to avoid native-library conflicts on Windows.
print("Loading Argos Translate...", flush=True)
import argostranslate.translate
print("Argos Translate loaded. Loading NumPy and Pandas...", flush=True)

import numpy as np
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
RAW_KAGGLE_DIR = PROJECT_DIR / "data" / "raw_kaggle"
OUTPUT_DIR = PROJECT_DIR / "data" / "raw"
TRANSLATION_CACHE_FILE = OUTPUT_DIR / "translation_cache.json"


def translate_to_english(values: pd.Series) -> pd.Series:
    """Translate distinct non-empty Russian labels to English.

    Uses the installed Argos Translate Russian-to-English model locally, so
    translation does not send requests to an online translation service. The
    model must be installed once before running this script.
    """
    languages = argostranslate.translate.get_installed_languages()
    russian = next((language for language in languages if language.code == "ru"), None)
    english = next((language for language in languages if language.code == "en"), None)
    if russian is None or english is None:
        raise RuntimeError(
            "Argos Russian-to-English model is not installed. Install the "
            "translate-ru_en package, then run this script again."
        )
    translator = russian.get_translation(english)
    unique_values = values.dropna().astype(str).unique().tolist()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if TRANSLATION_CACHE_FILE.exists():
        with TRANSLATION_CACHE_FILE.open("r", encoding="utf-8") as cache_file:
            translations = json.load(cache_file)
    else:
        translations = {}

    pending = [value for value in unique_values if value not in translations]
    total_pending = len(pending)
    for index, value in enumerate(pending, start=1):
        translations[value] = translator.translate(value) or value

        if index % 100 == 0 or index == total_pending:
            with TRANSLATION_CACHE_FILE.open("w", encoding="utf-8") as cache_file:
                json.dump(translations, cache_file, ensure_ascii=False, indent=2)
            print(f"Translated {index:,} of {total_pending:,} new values...")

    return values.map(
        lambda value: translations.get(str(value), value) if pd.notna(value) else value
    )


# ----------------------------------------------------------------------------
# STEP 1: Load the real Kaggle files
# ----------------------------------------------------------------------------
def load_kaggle_files():
    sales_train = pd.read_csv(RAW_KAGGLE_DIR / "sales_train.csv")
    items = pd.read_csv(RAW_KAGGLE_DIR / "items.csv")
    item_categories = pd.read_csv(RAW_KAGGLE_DIR / "item_categories.csv")
    shops = pd.read_csv(RAW_KAGGLE_DIR / "shops.csv")
    return sales_train, items, item_categories, shops


# ----------------------------------------------------------------------------
# STEP 2: Build sales_raw.csv
# Kaggle's `date` column is formatted dd.mm.yyyy and units are item_cnt_day
# (can be negative for returns) — we parse the date properly and drop
# returns here since our schema assumes non-negative sale quantities.
# ----------------------------------------------------------------------------
def build_sales_raw(sales_train: pd.DataFrame) -> pd.DataFrame:
    df = sales_train.copy()
    df["date"] = pd.to_datetime(df["date"], format="%d.%m.%Y")
    df = df[df["item_cnt_day"] > 0]  # drop returns/refunds for this project

    df = df.rename(columns={
        "shop_id": "store_id",
        "item_id": "product_id",
        "item_cnt_day": "units",
        "item_price": "unit_price",
    })
    df["sale_id"] = range(1, len(df) + 1)

    return df[["sale_id", "date", "store_id", "product_id", "units", "unit_price"]]


# ----------------------------------------------------------------------------
# STEP 3: Build products_raw.csv
# Joins items -> item_categories for the category name. Cost and
# supplier_id do not exist in the real data, so they are SYNTHESIZED:
#   - cost = 60% of that product's average selling price (a common
#     retail rule-of-thumb margin assumption — document this in your writeup)
#   - supplier_id = products are round-robin assigned across 10 synthetic
#     suppliers, grouped by category so the same category tends to share suppliers
# ----------------------------------------------------------------------------
def build_products_raw(items: pd.DataFrame, item_categories: pd.DataFrame,
                        sales_train: pd.DataFrame) -> pd.DataFrame:
    df = items.merge(item_categories, on="item_category_id", how="left")
    df = df.rename(columns={
        "item_id": "product_id",
        "item_name": "product_name",
        "item_category_name": "category",
    })
    # Translate source text before it is saved and loaded into PostgreSQL.
    df["product_name"] = translate_to_english(df["product_name"])
    df["category"] = translate_to_english(df["category"])

    avg_price = (
        sales_train[sales_train["item_price"] > 0]
        .groupby("item_id")["item_price"].mean()
        .rename("avg_price")
    )
    df = df.merge(avg_price, left_on="product_id", right_index=True, how="left")
    overall_avg = df["avg_price"].mean()
    df["cost"] = round((df["avg_price"].fillna(overall_avg)) * 0.6, 2)

    df["brand"] = "Generic"  # not available in the Kaggle dataset

    n_suppliers = 10
    df["supplier_id"] = "SUP" + (
        (df["item_category_id"] % n_suppliers) + 1
    ).astype(str).str.zfill(2)

    return df[["product_id", "product_name", "category", "brand", "cost", "supplier_id"]]


# ----------------------------------------------------------------------------
# STEP 4: Build stores_raw.csv
# Kaggle shop_name is formatted like "Москва ТЦ Атриум" (city first) — we
# take the first word as a rough region proxy. store_type is synthesized.
# ----------------------------------------------------------------------------
def build_stores_raw(shops: pd.DataFrame) -> pd.DataFrame:
    df = shops.copy()
    df["region"] = df["shop_name"].str.split().str[0]
    df["region"] = translate_to_english(df["region"])
    df["store_type"] = np.random.choice(
        ["Mall", "Standalone", "Outlet", "Online"], size=len(df)
    )
    df = df.rename(columns={"shop_id": "store_id"})
    return df[["store_id", "region", "store_type"]]


# ----------------------------------------------------------------------------
# STEP 5: Build suppliers_raw.csv
# Fully synthesized — the real dataset has no supplier info at all.
# ----------------------------------------------------------------------------
def build_suppliers_raw(n_suppliers: int = 10) -> pd.DataFrame:
    np.random.seed(42)
    supplier_ids = ["SUP" + str(i).zfill(2) for i in range(1, n_suppliers + 1)]
    df = pd.DataFrame({
        "supplier_id": supplier_ids,
        "supplier_name": [f"Supplier {i}" for i in range(1, n_suppliers + 1)],
        "lead_time_days": np.random.randint(3, 30, size=n_suppliers),
        "minimum_order_qty": np.random.randint(50, 500, size=n_suppliers),
    })
    return df


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    print("Starting Kaggle data preparation from:", __file__, flush=True)
    sales_train, items, item_categories, shops = load_kaggle_files()
    print("Loaded Kaggle source files.", flush=True)

    sales_raw = build_sales_raw(sales_train)
    print("Prepared sales rows.", flush=True)
    products_raw = build_products_raw(items, item_categories, sales_train)
    print("Prepared and translated product names/categories.", flush=True)
    stores_raw = build_stores_raw(shops)
    print("Prepared and translated store regions.", flush=True)
    suppliers_raw = build_suppliers_raw()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sales_raw.to_csv(OUTPUT_DIR / "sales_raw.csv", index=False, encoding="utf-8-sig")
    products_raw.to_csv(OUTPUT_DIR / "products_raw.csv", index=False, encoding="utf-8-sig")
    stores_raw.to_csv(OUTPUT_DIR / "stores_raw.csv", index=False, encoding="utf-8-sig")
    suppliers_raw.to_csv(OUTPUT_DIR / "suppliers_raw.csv", index=False, encoding="utf-8-sig")

    print("Done. Wrote to", OUTPUT_DIR, flush=True)
    print("  sales_raw.csv:    ", len(sales_raw), "rows")
    print("  products_raw.csv: ", len(products_raw), "rows")
    print("  stores_raw.csv:   ", len(stores_raw), "rows")
    print("  suppliers_raw.csv:", len(suppliers_raw), "rows")
