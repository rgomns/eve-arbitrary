import requests
import time
from pymongo import MongoClient, ASCENDING, UpdateOne
from datetime import datetime, timedelta
from tqdm import tqdm

# === CONFIG ===
CACHE_MINUTES = 30

# === MongoDB Setup ===
client = MongoClient("mongodb://localhost:27017/")
db = client["eve_market"]
orders_col = db["orders"]
stations_col = db["stations"]
items_col = db["items"]
regions_col = db["regions"]

orders_col.create_index([("order_id", ASCENDING)], unique=True)
orders_col.create_index([("region_id", ASCENDING), ("last_updated", ASCENDING)])
stations_col.create_index("station_id", unique=True)
items_col.create_index("type_id", unique=True)
regions_col.create_index("region_id", unique=True)

# === Helper functions ===
def get_station_info(station_id):
    cached = stations_col.find_one({"station_id": station_id})
    if cached:
        return cached["name"], cached.get("security", None)
    url = f"https://esi.evetech.net/latest/universe/stations/{station_id}/"
    r = requests.get(url)
    if r.status_code == 200:
        data = r.json()
        name = data.get("name", str(station_id))
        security_level = data.get("security", None)
        stations_col.update_one(
            {"station_id": station_id}, 
            {"$set": {"name": name, "security": security_level}}, 
            upsert=True
        )
        return name, security_level
    return str(station_id), None


def get_item_name(type_id):
    cached = items_col.find_one({"type_id": type_id})
    if cached:
        return cached["name"]
    url = f"https://esi.evetech.net/latest/universe/types/{type_id}/"
    r = requests.get(url)
    if r.status_code == 200:
        name = r.json().get("name", f"Type {type_id}")
        items_col.update_one(
            {"type_id": type_id}, {"$set": {"name": name}}, upsert=True
        )
        return name
    return f"Type {type_id}"

def get_all_region_ids():
    url = "https://esi.evetech.net/latest/universe/regions/"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()

def get_region_name(region_id):
    cached = regions_col.find_one({"region_id": region_id})
    if cached:
        return cached["name"]
    url = f"https://esi.evetech.net/latest/universe/regions/{region_id}/"
    r = requests.get(url)
    if r.status_code == 200:
        name = r.json().get("name", str(region_id))
        regions_col.update_one(
            {"region_id": region_id}, {"$set": {"name": name}}, upsert=True
        )
        return name
    return str(region_id)

# === Market order cache ===
def load_cached_orders(region_id):
    cutoff = datetime.utcnow() - timedelta(minutes=CACHE_MINUTES)
    cursor = orders_col.find({
        "region_id": region_id,
        "last_updated": {"$gte": cutoff}
    })
    orders = list(cursor)
    return orders if orders else None

def save_orders_to_cache(region_id, orders):
    now = datetime.utcnow()
    operations = []
    order_ids = [order["order_id"] for order in orders]

    # Remove outdated orders
    existing_orders = orders_col.find({"region_id": region_id})
    existing_order_ids = set(order["order_id"] for order in existing_orders)
    outdated_order_ids = existing_order_ids - set(order_ids)
    if outdated_order_ids:
        result = orders_col.delete_many({"order_id": {"$in": list(outdated_order_ids)}})
        print(f"❌ Removed {result.deleted_count} outdated orders from cache")

    for order in orders:
        order["region_id"] = region_id
        order["last_updated"] = now
        operations.append(
            UpdateOne({"order_id": order["order_id"]}, {"$set": order}, upsert=True)
        )

    if operations:
        result = orders_col.bulk_write(operations)
        print(f"✅ Saved {len(operations)} orders to cache (upserted: {result.upserted_count})")

# === Fetch all orders from ESI ===
def fetch_all_orders(region_id):
    print(f"Checking cache for region {region_id}...")
    cached = load_cached_orders(region_id)
    if cached:
        print(f"✅ Using cached orders for region {region_id}")
        return cached

    print(f"⏳ Fetching live orders for region {region_id} from ESI...")
    orders = []
    page = 1
    while True:
        url = f"https://esi.evetech.net/latest/markets/{region_id}/orders/"
        response = requests.get(url, params={"page": page})
        if response.status_code != 200:
            print(f"❌ Failed to fetch page {page} for region {region_id}")
            break
        batch = response.json()
        if not batch:
            break
        orders.extend(batch)
        if 'X-Pages' in response.headers:
            if page >= int(response.headers['X-Pages']):
                break
        else:
            break
        page += 1
        time.sleep(0.2)
    save_orders_to_cache(region_id, orders)
    return orders

# === Main execution ===
def fetch_data():
    print("🔍 Fetching all EVE region IDs from ESI...")
    try:
        region_ids = get_all_region_ids()
    except Exception as e:
        print(f"❌ Failed to fetch region list: {e}")
        exit(1)

    print(f"📦 Found {len(region_ids)} regions. Starting cache process...")

    for region_id in tqdm(region_ids, desc="Regions"):
        region_name = get_region_name(region_id)
        print(f"\n=== Region {region_id}: {region_name} ===")

        try:
            orders = fetch_all_orders(region_id)
        except Exception as e:
            print(f"⚠️ Error fetching orders for region {region_id}: {e}")
            continue

        unique_stations = set(o["location_id"] for o in orders)
        unique_types = set(o["type_id"] for o in orders)

        print(f"🗃️ Caching {len(unique_stations)} stations and {len(unique_types)} item names...")

        for station_id in tqdm(unique_stations, desc="Stations", leave=False):
            station_name, security_level = get_station_info(station_id)
        for type_id in tqdm(unique_types, desc="Items", leave=False):
            get_item_name(type_id)

    print("✅ All regions cached successfully.")
