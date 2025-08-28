from crewai.tools import BaseTool
from typing import Type, List
from pydantic import BaseModel, Field
import os
import motor.motor_asyncio
from datetime import datetime, timedelta
import logging

# Direct MongoDB setup (replace backend_config usage)
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://bhavinparmar1953:123qwerty@cluster0.qndu4.mongodb.net/")
MONGO_DB = os.getenv("MONGO_DB", "telegram_tokens")
MONGO_MSG_COLLECTION = os.getenv("MONGO_MSG_COLLECTION", "messages")
MONGO_DEXSCREENER_COLLECTION = os.getenv("MONGO_DEXSCREENER_COLLECTION", "dexscreener_data")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "group_user_counts_webhook_test")

client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = client[MONGO_DB]
msg_collection = db[MONGO_MSG_COLLECTION]
dexscreener_data = db[MONGO_DEXSCREENER_COLLECTION]
test_collection = db[MONGO_COLLECTION]

import requests


def fetch_dexscreener_data(contract_address: str):
    url = f"https://api.dexscreener.com/latest/dex/search/?q={contract_address}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json().get('pairs', [])
    except Exception:
        pass
    return []


# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TopTelegramPromotersInput(BaseModel):
    """Input schema for TopTelegramPromotersTool."""
    hours_after_call: int = Field(24, description="How many hours after the call to measure volume/market cap change.")
    top_n: int = Field(5, description="How many top users to return.")


class TopTelegramPromotersTool(BaseTool):
    name: str = "Top Telegram Promoters Tool"
    description: str = (
        "Finds the top Telegram users who bring the most volume and market cap after their calls, based on DEX and message data."
    )
    args_schema: Type[BaseModel] = TopTelegramPromotersInput

    def _run(self, hours_after_call: int=24, top_n: int=5) -> str:
        logger.info(f"Running TopTelegramPromotersTool with hours_after_call={hours_after_call}, top_n={top_n}")
        import asyncio
        try:
            return asyncio.run(self._arun(hours_after_call, top_n))
        except Exception as e:
            logger.exception("Exception in _run of TopTelegramPromotersTool")
            return f"Error running TopTelegramPromotersTool: {e}"

    async def _arun(self, hours_after_call: int=24, top_n: int=5) -> str:
        logger.info(f"Starting async run with hours_after_call={hours_after_call}, top_n={top_n}")
        try:
            user_stats = {}
            async for doc in test_collection.find({}):
                print(doc)
                contract = doc.get("Contract Address")
                user = doc.get("Username")
                call_time = doc.get("Message DateTime")
                if not (contract and user and call_time):
                    logger.warning(f"Skipping doc due to missing contract/user/call_time: {doc}")
                    continue
                # Parse call_time
                if isinstance(call_time, str):
                    try:
                        call_time = datetime.fromisoformat(call_time)
                    except Exception as parse_exc:
                        logger.warning(f"Failed to parse call_time '{call_time}': {parse_exc}")
                        continue
                # Get 'before' market cap from Dexscreener Data in the document
                before_mc = 0
                dexscreener_data = doc.get("Dexscreener Data", [])
                if dexscreener_data and isinstance(dexscreener_data, list):
                    before_entry = dexscreener_data[0]
                    before_mc = before_entry.get("marketCap") or before_entry.get("market_cap") or 0
                # Get 'after' market cap from live DEX data
                live_pairs = fetch_dexscreener_data(contract)
                after_mc = 0
                if live_pairs:
                    after_entry = live_pairs[0]
                    after_mc = after_entry.get("marketCap") or 0
                mc_diff = after_mc - before_mc
                if user not in user_stats:
                    user_stats[user] = {"total_mc": 0, "calls": 0}
                user_stats[user]["total_mc"] += mc_diff
                user_stats[user]["calls"] += 1
            # Rank users by total market cap brought
            ranked = sorted(user_stats.items(), key=lambda x: x[1]["total_mc"], reverse=True)
            result = "Top Telegram Promoters (by market cap difference after call):\n"
            for i, (user, stats) in enumerate(ranked[:top_n]):
                result += f"{i+1}. {user} - Total Market Cap: {stats['total_mc']:.2f}, Calls: {stats['calls']}\n"
            if not ranked:
                logger.info("No data found for any users.")
                result += "No data found."
            logger.info("TopTelegramPromotersTool completed successfully.")
            return result 
        except Exception as e:
            logger.exception("Exception in _arun of TopTelegramPromotersTool")
            return f"Error in TopTelegramPromotersTool: {e}" 
