from fastapi import FastAPI, Request, Query
from pymongo import MongoClient
from collections import defaultdict
from datetime import datetime, timedelta
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import pandas as pd
from typing import Optional 
# === CONFIG ===
BROKER_FEE = 0.03
SALES_TAX = 0.015
CACHE_MINUTES = 10000
HAULING_TIME_MINUTES = 15


# === FastAPI Setup ===
app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# === MongoDB Setup ===
client = MongoClient("mongodb://localhost:27017/")
db = client["eve_market"]
orders_col = db["orders"]
stations_col = db["stations"]
items_col = db["items"]
regions_col = db["regions"]

# === Helper Functions ===
def get_station_data(station_id):
    cached = stations_col.find_one({"station_id": station_id})
    return cached if cached else {"name": str(station_id), "security": "Unknown"}

def get_item_name(type_id):
    cached = items_col.find_one({"type_id": type_id})
    return cached["name"] if cached else f"Type {type_id}"

# === Unified Arbitrage Function === 
def find_arbitrage(source_station=None, dest_station=None):
    cutoff = datetime.utcnow() - timedelta(minutes=CACHE_MINUTES)

    query = {"last_updated": {"$gte": cutoff}}
    if source_station is not None and dest_station is not None:
        query["$or"] = [
            {"location_id": source_station},
            {"location_id": dest_station}
        ]
    elif source_station is not None:
        query["location_id"] = source_station
    elif dest_station is not None:
        query["location_id"] = dest_station

    orders = list(orders_col.find(query))
    if not orders:
        return []  # Return an empty list if no data is available

    sell_orders_query = {"is_buy_order": False, "last_updated": {"$gte": cutoff}}
    buy_orders_query = {"is_buy_order": True, "last_updated": {"$gte": cutoff}}

    if source_station:
        sell_orders_query["location_id"] = source_station
    if dest_station:
        buy_orders_query["location_id"] = dest_station

    sell_orders = list(orders_col.find(sell_orders_query))
    buy_orders = list(orders_col.find(buy_orders_query))

    sell_by_type = defaultdict(list)
    buy_by_type = defaultdict(list)

    for o in sell_orders:
        sell_by_type[o["type_id"]].append(o)
    for o in buy_orders:
        buy_by_type[o["type_id"]].append(o)

    results = []
    common_type_ids = set(sell_by_type.keys()) & set(buy_by_type.keys())

    for type_id in common_type_ids:
        try:
            best_sell = min(sell_by_type[type_id], key=lambda x: x["price"])
            best_buy = max(buy_by_type[type_id], key=lambda x: x["price"])

            sell_price = best_sell["price"]
            buy_price = best_buy["price"]
            volume = min(best_sell["volume_remain"], best_buy["volume_remain"])

            proceeds_per_unit = buy_price * (1 - BROKER_FEE - SALES_TAX)
            unit_profit = proceeds_per_unit - sell_price
            total_profit = unit_profit * volume
            margin = unit_profit / sell_price
            isk_per_minute = total_profit / HAULING_TIME_MINUTES

            
            results.append({
                "item": get_item_name(type_id),
                "source_station": get_station_data(best_sell["location_id"]),
                "dest_station": get_station_data(best_buy["location_id"]),
                "buy_price": round(sell_price, 2),
                "sell_price": round(buy_price, 2),
                "volume": volume,
                "unit_profit": round(unit_profit, 2),
                "total_profit": round(total_profit, 2),
                "margin": f"{margin:.1%}",
                "isk_per_minute": round(isk_per_minute, 2),
            })
        except Exception as e:
            print(f"Error processing item {type_id}: {e}")

    return results


def is_valid_security(security):
    try:
        return float(security)
    except (ValueError, TypeError):
        return None

# === API Endpoint: Render Trades ===
@app.get("/")
def render_results(request: Request,
                    source_station: Optional[int] = Query(None),
                    dest_station: Optional[str] = Query(None),
                    min_profit: int = Query(100000),
                    min_margin: float = Query(0.15),
                    sort_by: str = Query("total_profit"),
                    security_filter: float = Query(-1.0)):
    
    results = find_arbitrage(source_station, dest_station)

    print(dest_station)

    # Apply security level filter
    if security_filter != 0:
        filtered_results = []
        for r in results:
            sec = is_valid_security(r["source_station"].get("security"))
            if sec is not None and sec > security_filter:
                filtered_results.append(r)
        results = filtered_results


    # Apply profit and margin filters
    results = [r for r in results if r["total_profit"] >= min_profit and float(r["margin"].strip('%'))/100 >= min_margin]

    # Sort results
    results.sort(key=lambda x: x[sort_by], reverse=True)

    return templates.TemplateResponse("index.html", {"request": request, "trades": results[:100]})

@app.get("/search_station/")
def search_station(query: str):
    query = query.lower()
    stations = list(stations_col.find({"name": {"$regex": query, "$options": "i"}}, {"station_id": 1, "name": 1}))
    
    return [{"station_id": s["station_id"], "name": s["name"]} for s in stations]
