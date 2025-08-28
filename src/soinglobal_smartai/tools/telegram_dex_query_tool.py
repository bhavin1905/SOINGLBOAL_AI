import os
import pymongo
from datetime import datetime
import requests
import logging
from langchain.tools import tool
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type


class TelegramDexQueryInput(BaseModel):
    """Input schema for TelegramDexQueryTool."""
    query: str = Field(description="A description of what data to fetch")
    top_n: int = Field(default=5, description="Number of top results to return")
    hours_after_call: int = Field(default=24, description="Hours after call to measure impact")


MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://bhavinparmar1953:123qwerty@cluster0.qndu4.mongodb.net/")
MONGO_DB = os.getenv("MONGO_DB", "telegram_tokens")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "group_user_counts_webhook_test")

# Use synchronous MongoDB client
client = pymongo.MongoClient(MONGO_URI)
db = client[MONGO_DB]
test_collection = db[MONGO_COLLECTION]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def fetch_dexscreener_data(contract_address: str):
    url = f"https://api.dexscreener.com/latest/dex/search/?q={contract_address}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json().get('pairs', [])
    except Exception as e:
        logger.error(f"Error fetching DEX data: {e}")
    return []


class TelegramDexQueryTool(BaseTool):
    name: str = "Telegram/DEX General Query Tool"
    description: str = "Fetches data from MongoDB based on the query about Telegram promoters and DEX data"
    args_schema: Type[BaseModel] = TelegramDexQueryInput

    def _run(self, query: str, top_n: int=5, hours_after_call: int=24) -> str:
        """
        Fetches data from MongoDB based on the query.
        Args:
            query: A description of what data to fetch (e.g., "all messages from user @username", "all contracts", "top users by calls", etc.)
            top_n: Number of top results to return
            hours_after_call: Hours after call to measure impact
        Returns:
            str: The requested data from MongoDB formatted as a string
        """
        result = self._fetch_mongodb_data(query, top_n, hours_after_call)
        
        # Convert dict result to string for better agent consumption
        if isinstance(result, dict):
            if 'error' in result:
                return f"Error: {result['error']}"
            
            data = result.get('data', [])
            
            if isinstance(data, dict):  # For user stats
                output = f"Query: {query}\n\nResults:\n"
                for user, stats in list(data.items())[:top_n]:
                    output += f"User: {user}\n"
                    output += f"  Total Market Cap Change: ${stats.get('total_mc_change', 0):,.2f}\n"
                    output += f"  Number of Calls: {stats.get('calls', 0)}\n"
                    output += f"  Success Rate: {stats.get('success_rate', 0):.1f}%\n"
                    output += f"  Unique Contracts: {stats.get('unique_contracts', 0)}\n\n"
                return output
            elif isinstance(data, list):
                output = f"Query: {query}\n\nFound {len(data)} results:\n\n"
                for i, item in enumerate(data[:top_n]):
                    output += f"{i+1}. "
                    if 'username' in item:
                        output += f"User: {item.get('username', 'Unknown')}\n"
                        output += f"   Message: {item.get('message', '')[:100]}...\n"
                        output += f"   DateTime: {item.get('datetime', '')}\n"
                        output += f"   Contract: {item.get('contract', '')}\n\n"
                    elif 'contract' in item:
                        output += f"Contract: {item.get('contract', '')}\n"
                        output += f"   Mentions: {item.get('mentions', 0)}\n"
                        output += f"   Unique Users: {item.get('unique_users', 0)}\n\n"
                    else:
                        output += f"{item}\n\n"
                return output
            else:
                return str(result)
        else:
            return str(result)

    def _fetch_mongodb_data(self, query: str, top_n: int=5, hours_after_call: int=24) -> dict:
        logger.info(f"Fetching MongoDB data for query: {query}")
        try:
            query_lower = query.lower()
            result = {"query": query, "data": [], "summary": {}, "total_count": 0}
            
            if "user" in query_lower and "message" in query_lower:
                username = None
                for word in query.split():
                    if word.startswith("@"):
                        username = word.lstrip("@")
                        break
                if username:
                    messages = []
                    for doc in test_collection.find({"Username": username}):
                        messages.append({
                            "username": doc.get("Username"),
                            "message": doc.get("Message Text"),
                            "datetime": doc.get("Message DateTime"),
                            "contract": doc.get("Contract Address"),
                            "group": doc.get("Group Name")
                        })
                    result["data"] = messages
                    result["total_count"] = len(messages)
                    result["summary"] = {"user": username, "message_count": len(messages)}
            
            elif "group" in query_lower and "message" in query_lower:
                group_name = None
                for word in query.split():
                    if word.startswith("#") or (word.isalnum() and len(word) > 2):
                        group_name = word
                        break
                if group_name:
                    messages = []
                    for doc in test_collection.find({"Group Name": {"$regex": group_name, "$options": "i"}}).limit(50):
                        messages.append({
                            "username": doc.get("Username"),
                            "message": doc.get("Message Text"),
                            "datetime": doc.get("Message DateTime"),
                            "contract": doc.get("Contract Address"),
                            "group": doc.get("Group Name")
                        })
                    result["data"] = messages
                    result["total_count"] = len(messages)
                    result["summary"] = {"group": group_name, "message_count": len(messages)}
            
            elif "contract" in query_lower and "call" in query_lower:
                contract_address = None
                for word in query.split():
                    if word.startswith("0x") and len(word) > 20:
                        contract_address = word.strip()
                        break
                if contract_address:
                    calls = []
                    unique_users = set()
                    for doc in test_collection.find({"Contract Address": contract_address}):
                        calls.append({
                            "username": doc.get("Username"),
                            "message": doc.get("Message Text"),
                            "datetime": doc.get("Message DateTime"),
                            "contract": doc.get("Contract Address"),
                            "dex_data": doc.get("Dexscreener Data", [])
                        })
                        if doc.get("Username"):
                            unique_users.add(doc.get("Username"))
                    result["data"] = calls
                    result["total_count"] = len(calls)
                    result["summary"] = {
                        "contract": contract_address,
                        "call_count": len(calls),
                        "unique_users": list(unique_users)
                    }
            
            elif "top" in query_lower and ("user" in query_lower or "caller" in query_lower or "promoter" in query_lower):
                user_stats = {}
                processed_count = 0
                
                for doc in test_collection.find({}):
                    processed_count += 1
                    if processed_count % 100 == 0:
                        logger.info(f"Processed {processed_count} documents...")
                    
                    contract = doc.get("Contract Address")
                    user = doc.get("Username")
                    call_time = doc.get("Message DateTime")
                    dex_data = doc.get("Dexscreener Data", [])
                    
                    if not (contract and user and call_time and dex_data):
                        continue
                    
                    # Parse call_time
                    if isinstance(call_time, str):
                        try:
                            call_time = datetime.fromisoformat(call_time)
                        except Exception:
                            continue
                    
                    # Get 'before' market cap from Dexscreener Data in the document
                    before_entry = dex_data[0] if dex_data else {}
                    before_mc = before_entry.get("marketCap") or before_entry.get("market_cap") or 0
                    before_price = before_entry.get("priceUsd") or 0
                    
                    # Get 'after' market cap from live DEX data
                    live_data = fetch_dexscreener_data(contract)
                    after_mc = live_data[0].get("marketCap") if live_data else 0
                    after_price = live_data[0].get("priceUsd") if live_data else 0
                    
                    try:
                        before_mc = float(before_mc) if before_mc else 0
                        after_mc = float(after_mc) if after_mc else 0
                        before_price = float(before_price) if before_price else 0
                        after_price = float(after_price) if after_price else 0
                        
                        mc_diff = after_mc - before_mc
                        price_diff = after_price - before_price
                        
                        if user not in user_stats:
                            user_stats[user] = {
                                "total_mc_change": 0,
                                "calls": 0,
                                "successful_calls": 0,
                                "contracts": set(),
                                "total_price_change": 0
                            }
                        
                        user_stats[user]["total_mc_change"] += mc_diff
                        user_stats[user]["total_price_change"] += price_diff
                        user_stats[user]["calls"] += 1
                        user_stats[user]["contracts"].add(contract)
                        
                        if mc_diff > 0:
                            user_stats[user]["successful_calls"] += 1
                    
                    except (ValueError, TypeError):
                        continue
                
                # Calculate additional stats
                for user in user_stats:
                    stats = user_stats[user]
                    stats["success_rate"] = (stats["successful_calls"] / stats["calls"]) * 100 if stats["calls"] > 0 else 0
                    stats["unique_contracts"] = len(stats["contracts"])
                    stats["avg_mc_change"] = stats["total_mc_change"] / stats["calls"] if stats["calls"] > 0 else 0
                    stats["contracts"] = list(stats["contracts"])
                
                # Sort by total market cap change
                sorted_users = dict(sorted(user_stats.items(), key=lambda x: x[1]["total_mc_change"], reverse=True))
                
                result["data"] = sorted_users
                result["total_count"] = len(user_stats)
                result["summary"] = {"total_users": len(user_stats), "processed_documents": processed_count}
            
            elif "contract" in query_lower and "discussed" in query_lower:
                contract_stats = {}
                for doc in test_collection.find({}):
                    contract = doc.get("Contract Address")
                    if contract:
                        if contract not in contract_stats:
                            contract_stats[contract] = {"mentions": 0, "users": set()}
                        contract_stats[contract]["mentions"] += 1
                        contract_stats[contract]["users"].add(doc.get("Username", "Unknown"))
                
                top_contracts = sorted(contract_stats.items(), key=lambda x: x[1]["mentions"], reverse=True)[:10]
                result["data"] = [
                    {
                        "contract": contract,
                        "mentions": stats["mentions"],
                        "unique_users": len(stats["users"])
                    }
                    for contract, stats in top_contracts
                ]
                result["total_count"] = len(result["data"])
                result["summary"] = {"top_contracts": [c for c, _ in top_contracts]}
            
            else:
                # Default: return recent messages
                messages = []
                for doc in test_collection.find({}).limit(100):
                    messages.append({
                        "username": doc.get("Username"),
                        "message": doc.get("Message Text"),
                        "datetime": doc.get("Message DateTime"),
                        "contract": doc.get("Contract Address"),
                        "group": doc.get("Group Name"),
                        "dex_data": doc.get("Dexscreener Data", [])
                    })
                result["data"] = messages
                result["total_count"] = len(messages)
                result["summary"] = {"recent_messages": len(messages)}
            
            return result
            
        except Exception as e:
            logger.error(f"Error fetching MongoDB data: {e}")
            return {"error": str(e), "query": query}


@tool
def fetch_dex_data(contract_address: str) -> dict:
    """
    Fetches live DEX data for a given contract address.
    Args:
        contract_address: The contract address to fetch data for (should start with 0x)
    Returns:
        dict: Live DEX data including price, market cap, volume, etc.
    """
    logger.info(f"Fetching DEX data for contract: {contract_address}")
    try:
        if not contract_address.startswith("0x") or len(contract_address) < 20:
            return {"error": "Invalid contract address format"}
        
        live_data = fetch_dexscreener_data(contract_address)
        if not live_data:
            return {"error": "No DEX data found for this contract"}
        
        pair = live_data[0]
        result = {
            "contract_address": contract_address,
            "dex_data": {
                "market_cap": pair.get('marketCap'),
                "price_usd": pair.get('priceUsd'),
                "volume_24h": pair.get('volume', {}).get('h24'),
                "liquidity_usd": pair.get('liquidity', {}).get('usd'),
                "price_change_24h": pair.get('priceChange', {}).get('h24'),
                "dex_id": pair.get('dexId'),
                "pair_address": pair.get('pairAddress'),
                "token_name": pair.get('baseToken', {}).get('name'),
                "token_symbol": pair.get('baseToken', {}).get('symbol')
            },
            "raw_data": pair
        }
        return result
    except Exception as e:
        logger.error(f"Error fetching DEX data: {e}")
        return {"error": str(e), "contract_address": contract_address}
