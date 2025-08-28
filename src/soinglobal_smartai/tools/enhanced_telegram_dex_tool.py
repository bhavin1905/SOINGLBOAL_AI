import os
import pymongo
from datetime import datetime, timedelta
import requests
import logging
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type, Dict, List, Optional
import time


class EnhancedTelegramDexInput(BaseModel):
    """Input schema for Enhanced Telegram DEX Tool."""
    query: str = Field(description="A description of what data to fetch")
    top_n: int = Field(default=5, description="Number of top results to return")
    hours_after_call: int = Field(default=24, description="Hours after call to measure impact")
    sort_by: str = Field(default="marketCapChangePercent", description="Field to sort by: marketCapChangePercent, groupsCount, latestMessageDate")
    sort_dir: str = Field(default="desc", description="Sort direction: asc or desc")
    chains: Optional[str] = Field(default=None, description="Comma-separated chain filters (e.g., 'ethereum,solana,bsc')")


# MongoDB configuration
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://bhavinparmar1953:123qwerty@cluster0.qndu4.mongodb.net/")
MONGO_DB = os.getenv("MONGO_DB", "telegram_tokens")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "group_user_counts_webhook_test")
DEXSCREENER_CACHE_COLLECTION = os.getenv("DEXSCREENER_CACHE_COLLECTION", "dexscreener_cache_new")

# Initialize MongoDB connection
client = pymongo.MongoClient(MONGO_URI)
db = client[MONGO_DB]
main_collection = db[MONGO_COLLECTION]
cache_collection = db[DEXSCREENER_CACHE_COLLECTION]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def fetch_dexscreener_data(contract_address: str) -> List[Dict]:
    """Fetch live DEX data from DexScreener API."""
    url = f"https://api.dexscreener.com/latest/dex/search/?q={contract_address}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json().get('pairs', [])
    except Exception as e:
        logger.error(f"Error fetching DEX data for {contract_address}: {e}")
    return []


def get_cached_price_data(contract_address: str) -> Optional[Dict]:
    """Get cached price data from MongoDB."""
    try:
        cached_data = cache_collection.find_one({"contract_address": contract_address})
        return cached_data
    except Exception as e:
        logger.error(f"Error getting cached data for {contract_address}: {e}")
        return None


def calculate_price_difference_with_groups(chain_filters: List[str]=None,
                                         sort_by: str="marketCapChangePercent",
                                         sort_dir: str="desc",
                                         limit: int=10,
                                         skip: int=0) -> List[Dict]:
    """
    Calculate price differences for coins with Telegram group mentions,
    similar to the Go API GetCoinsWithPriceDifference function.
    """
    try:
        # Build match stage
        match_stage = {
            "Dexscreener Data": {"$exists": True, "$ne": []}
        }
        
        if chain_filters:
            match_stage["Dexscreener Data.chainId"] = {"$in": chain_filters}
        
        # Aggregation pipeline similar to Go implementation
        pipeline = [
            {"$match": match_stage},
            {"$unwind": "$Dexscreener Data"},
            {
                "$match": {
                    "$expr": {
                        "$eq": ["$Contract Address", "$Dexscreener Data.baseToken.address"]
                    }
                }
            },
            {
                "$group": {
                    "_id": "$Contract Address",
                    "earliestMarketCap": {"$min": "$Dexscreener Data.marketCap"},
                    "firstDex": {"$first": "$Dexscreener Data"}
                }
            },
            {
                "$lookup": {
                    "from": DEXSCREENER_CACHE_COLLECTION,
                    "localField": "_id",
                    "foreignField": "contract_address",
                    "as": "cache"
                }
            },
            {
                "$unwind": {
                    "path": "$cache",
                    "preserveNullAndEmptyArrays": True
                }
            },
            {
                "$addFields": {
                    "cachedPriceUsd": "$cache.priceUsd",
                    "cachedMarketCap": "$cache.marketCap"
                }
            },
            {
                "$addFields": {
                    "marketCapChangePercent": {
                        "$cond": {
                            "if": {"$gt": ["$earliestMarketCap", 0]},
                            "then": {
                                "$multiply": [
                                    {
                                        "$divide": [
                                            {"$subtract": ["$cachedMarketCap", "$earliestMarketCap"]},
                                            "$earliestMarketCap"
                                        ]
                                    },
                                    100
                                ]
                            },
                            "else": None
                        }
                    }
                }
            },
            {
                "$lookup": {
                    "from": MONGO_COLLECTION,
                    "let": {"contractAddr": "$_id"},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {"$eq": ["$Contract Address", "$$contractAddr"]}
                            }
                        },
                        {
                            "$project": {
                                "Username": 1,
                                "Message DateTime": 1
                            }
                        }
                    ],
                    "as": "groupCalls"
                }
            },
            {
                "$addFields": {
                    "groups": {
                        "$setUnion": [
                            {
                                "$map": {
                                    "input": "$groupCalls",
                                    "as": "call",
                                    "in": "$$call.Username"
                                }
                            },
                            []
                        ]
                    },
                    "latestMessageDate": {
                        "$max": "$groupCalls.Message DateTime"
                    }
                }
            },
            {
                "$addFields": {
                    "groupsCount": {"$size": "$groups"}
                }
            },
            {
                "$project": {
                    "contract_address": "$_id",
                    "chainId": "$firstDex.chainId",
                    "dexURL": "$firstDex.url",
                    "info": "$firstDex.info",
                    "quoteToken": "$firstDex.quoteToken",
                    "baseToken": "$firstDex.baseToken",
                    "marketCapChangePercent": 1,
                    "cachedPriceUsd": 1,
                    "cachedMarketCap": 1,
                    "groups": 1,
                    "groupsCount": 1,
                    "latestMessageDate": 1,
                    "_id": 0
                }
            }
        ]
        
        # Add sorting
        sort_direction = -1 if sort_dir.lower() == "desc" else 1
        if sort_by in ["groupsCount", "latestMessageDate"]:
            pipeline.append({"$sort": {sort_by: sort_direction}})
        else:
            pipeline.append({"$sort": {sort_by: sort_direction}})
        
        # Add pagination
        pipeline.append({"$skip": skip})
        pipeline.append({"$limit": limit})
        
        # Execute aggregation
        results = list(main_collection.aggregate(pipeline))
        
        # Fetch live data for contracts missing cached data
        for result in results:
            contract_addr = result.get("contract_address")
            if not result.get("cachedPriceUsd") and contract_addr:
                live_data = fetch_dexscreener_data(contract_addr)
                if live_data:
                    pair = live_data[0]
                    result["cachedPriceUsd"] = pair.get("priceUsd")
                    result["cachedMarketCap"] = pair.get("marketCap")
                    result["dexURL"] = pair.get("url")
                    result["baseToken"] = pair.get("baseToken")
                    result["quoteToken"] = pair.get("quoteToken")
        
        return results
        
    except Exception as e:
        logger.error(f"Error in calculate_price_difference_with_groups: {e}")
        return []


class EnhancedTelegramDexTool(BaseTool):
    name: str = "Enhanced Telegram/DEX Analysis Tool"
    description: str = "Advanced tool for analyzing Telegram promoters, DEX data, and market cap changes with sophisticated filtering and ranking capabilities"
    args_schema: Type[BaseModel] = EnhancedTelegramDexInput

    def _run(self, query: str, top_n: int=5, hours_after_call: int=24,
             sort_by: str="marketCapChangePercent", sort_dir: str="desc",
             chains: Optional[str]=None) -> str:
        """
        Enhanced analysis of Telegram promoters and DEX data.
        """
        try:
            query_lower = query.lower()
            chain_filters = []
            
            if chains:
                chain_filters = [chain.strip().lower() for chain in chains.split(",")]
            
            # Determine query type and execute appropriate analysis
            if "top" in query_lower and ("user" in query_lower or "promoter" in query_lower):
                return self._analyze_top_promoters(top_n, hours_after_call, sort_by, sort_dir)
            
            elif "coin" in query_lower or "contract" in query_lower or "token" in query_lower:
                return self._analyze_coins_with_price_difference(
                    chain_filters, sort_by, sort_dir, top_n
                )
            
            elif "group" in query_lower and "performance" in query_lower:
                return self._analyze_group_performance(top_n, hours_after_call)
            
            elif "market cap" in query_lower or "price change" in query_lower:
                return self._analyze_market_cap_changes(
                    chain_filters, sort_by, sort_dir, top_n
                )
            
            else:
                # Default comprehensive analysis
                return self._comprehensive_analysis(top_n, chain_filters)
                
        except Exception as e:
            logger.error(f"Error in Enhanced Telegram DEX Tool: {e}")
            return f"Error: {str(e)}"

    def _analyze_top_promoters(self, top_n: int, hours_after_call: int,
                             sort_by: str, sort_dir: str) -> str:
        """Analyze top Telegram promoters by various metrics."""
        try:
            user_stats = {}
            processed_count = 0
            
            for doc in main_collection.find({}):
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
                        call_time = datetime.fromisoformat(call_time.replace('Z', '+00:00'))
                    except Exception:
                        continue
                
                # Get before and after market data
                before_entry = dex_data[0] if dex_data else {}
                before_mc = float(before_entry.get("marketCap", 0) or 0)
                before_price = float(before_entry.get("priceUsd", 0) or 0)
                
                # Get current data
                cached_data = get_cached_price_data(contract)
                if cached_data:
                    after_mc = float(cached_data.get("marketCap", 0) or 0)
                    after_price = float(cached_data.get("priceUsd", 0) or 0)
                else:
                    live_data = fetch_dexscreener_data(contract)
                    if live_data:
                        after_mc = float(live_data[0].get("marketCap", 0) or 0)
                        after_price = float(live_data[0].get("priceUsd", 0) or 0)
                    else:
                        after_mc = after_price = 0
                
                # Calculate metrics
                mc_diff = after_mc - before_mc
                price_diff = after_price - before_price
                mc_change_pct = (mc_diff / before_mc * 100) if before_mc > 0 else 0
                price_change_pct = (price_diff / before_price * 100) if before_price > 0 else 0
                
                if user not in user_stats:
                    user_stats[user] = {
                        "total_mc_change": 0,
                        "total_price_change": 0,
                        "calls": 0,
                        "successful_calls": 0,
                        "contracts": set(),
                        "avg_mc_change_pct": 0,
                        "avg_price_change_pct": 0,
                        "best_call_mc_change": 0,
                        "worst_call_mc_change": 0
                    }
                
                stats = user_stats[user]
                stats["total_mc_change"] += mc_diff
                stats["total_price_change"] += price_diff
                stats["calls"] += 1
                stats["contracts"].add(contract)
                
                if mc_diff > 0:
                    stats["successful_calls"] += 1
                
                # Track best and worst calls
                if mc_diff > stats["best_call_mc_change"]:
                    stats["best_call_mc_change"] = mc_diff
                if mc_diff < stats["worst_call_mc_change"]:
                    stats["worst_call_mc_change"] = mc_diff
            
            # Calculate final metrics
            for user in user_stats:
                stats = user_stats[user]
                stats["success_rate"] = (stats["successful_calls"] / stats["calls"]) * 100 if stats["calls"] > 0 else 0
                stats["unique_contracts"] = len(stats["contracts"])
                stats["avg_mc_change"] = stats["total_mc_change"] / stats["calls"] if stats["calls"] > 0 else 0
                stats["avg_price_change"] = stats["total_price_change"] / stats["calls"] if stats["calls"] > 0 else 0
                stats["contracts"] = list(stats["contracts"])
            
            # Sort users by specified metric
            if sort_by == "total_mc_change":
                sorted_users = sorted(user_stats.items(), key=lambda x: x[1]["total_mc_change"], reverse=(sort_dir.lower() == "desc"))
            elif sort_by == "success_rate":
                sorted_users = sorted(user_stats.items(), key=lambda x: x[1]["success_rate"], reverse=(sort_dir.lower() == "desc"))
            elif sort_by == "calls":
                sorted_users = sorted(user_stats.items(), key=lambda x: x[1]["calls"], reverse=(sort_dir.lower() == "desc"))
            else:
                sorted_users = sorted(user_stats.items(), key=lambda x: x[1]["total_mc_change"], reverse=True)
            
            # Format output
            output = f"🚀 TOP {top_n} TELEGRAM PROMOTERS ANALYSIS\n"
            output += "=" * 50 + "\n\n"
            
            for i, (user, stats) in enumerate(sorted_users[:top_n]):
                output += f"{i+1}. 👤 {user}\n"
                output += f"   💰 Total Market Cap Impact: ${stats['total_mc_change']:,.2f}\n"
                output += f"   📞 Total Calls: {stats['calls']}\n"
                output += f"   ✅ Success Rate: {stats['success_rate']:.1f}%\n"
                output += f"   📈 Avg MC Change: ${stats['avg_mc_change']:,.2f}\n"
                output += f"   🎯 Best Call: ${stats['best_call_mc_change']:,.2f}\n"
                output += f"   📉 Worst Call: ${stats['worst_call_mc_change']:,.2f}\n"
                output += f"   🏷️  Unique Contracts: {stats['unique_contracts']}\n\n"
            
            output += f"📊 Total Analyzed: {len(user_stats)} users, {processed_count} documents\n"
            return output
            
        except Exception as e:
            logger.error(f"Error in _analyze_top_promoters: {e}")
            return f"Error analyzing top promoters: {str(e)}"

    def _analyze_coins_with_price_difference(self, chain_filters: List[str],
                                           sort_by: str, sort_dir: str,
                                           limit: int) -> str:
        """Analyze coins with price differences, similar to Go API."""
        try:
            results = calculate_price_difference_with_groups(
                chain_filters=chain_filters,
                sort_by=sort_by,
                sort_dir=sort_dir,
                limit=limit
            )
            
            if not results:
                return "No coins found with the specified criteria."
            
            output = f"🪙 TOP {limit} COINS WITH PRICE CHANGES\n"
            output += "=" * 50 + "\n\n"
            
            for i, coin in enumerate(results):
                contract = coin.get("contract_address", "N/A")
                base_token = coin.get("baseToken", {})
                token_name = base_token.get("name", "Unknown") if base_token else "Unknown"
                token_symbol = base_token.get("symbol", "N/A") if base_token else "N/A"
                
                mc_change_pct = coin.get("marketCapChangePercent", 0) or 0
                cached_mc = coin.get("cachedMarketCap", 0) or 0
                cached_price = coin.get("cachedPriceUsd", 0) or 0
                groups_count = coin.get("groupsCount", 0)
                chain_id = coin.get("chainId", "unknown")
                
                output += f"{i+1}. 🏷️  {token_name} ({token_symbol})\n"
                output += f"   📄 Contract: {contract[:10]}...{contract[-6:] if len(contract) > 16 else contract}\n"
                output += f"   ⛓️  Chain: {chain_id.upper()}\n"
                output += f"   📈 Market Cap Change: {mc_change_pct:.2f}%\n"
                output += f"   💰 Current Market Cap: ${cached_mc:,.2f}\n"
                output += f"   💵 Current Price: ${cached_price:.8f}\n"
                output += f"   👥 Telegram Groups: {groups_count}\n"
                
                if coin.get("latestMessageDate"):
                    output += f"   📅 Latest Mention: {coin['latestMessageDate']}\n"
                
                output += "\n"
            
            return output
            
        except Exception as e:
            logger.error(f"Error in _analyze_coins_with_price_difference: {e}")
            return f"Error analyzing coins: {str(e)}"

    def _analyze_group_performance(self, top_n: int, hours_after_call: int) -> str:
        """Analyze performance of different Telegram groups."""
        try:
            group_stats = {}
            
            for doc in main_collection.find({}):
                group_name = doc.get("Group Name")
                contract = doc.get("Contract Address")
                call_time = doc.get("Message DateTime")
                dex_data = doc.get("Dexscreener Data", [])
                
                if not (group_name and contract and call_time and dex_data):
                    continue
                
                if group_name not in group_stats:
                    group_stats[group_name] = {
                        "total_calls": 0,
                        "total_mc_change": 0,
                        "successful_calls": 0,
                        "unique_contracts": set(),
                        "avg_mc_change": 0
                    }
                
                # Calculate market cap change for this call
                before_entry = dex_data[0] if dex_data else {}
                before_mc = float(before_entry.get("marketCap", 0) or 0)
                
                cached_data = get_cached_price_data(contract)
                if cached_data:
                    after_mc = float(cached_data.get("marketCap", 0) or 0)
                else:
                    live_data = fetch_dexscreener_data(contract)
                    after_mc = float(live_data[0].get("marketCap", 0)) if live_data else 0
                
                mc_diff = after_mc - before_mc
                
                stats = group_stats[group_name]
                stats["total_calls"] += 1
                stats["total_mc_change"] += mc_diff
                stats["unique_contracts"].add(contract)
                
                if mc_diff > 0:
                    stats["successful_calls"] += 1
            
            # Calculate final metrics and sort
            for group in group_stats:
                stats = group_stats[group]
                stats["success_rate"] = (stats["successful_calls"] / stats["total_calls"]) * 100 if stats["total_calls"] > 0 else 0
                stats["avg_mc_change"] = stats["total_mc_change"] / stats["total_calls"] if stats["total_calls"] > 0 else 0
                stats["unique_contracts_count"] = len(stats["unique_contracts"])
                stats["unique_contracts"] = list(stats["unique_contracts"])
            
            sorted_groups = sorted(group_stats.items(), key=lambda x: x[1]["total_mc_change"], reverse=True)
            
            output = f"📱 TOP {top_n} TELEGRAM GROUPS PERFORMANCE\n"
            output += "=" * 50 + "\n\n"
            
            for i, (group, stats) in enumerate(sorted_groups[:top_n]):
                output += f"{i+1}. 🏷️  {group}\n"
                output += f"   💰 Total Market Cap Impact: ${stats['total_mc_change']:,.2f}\n"
                output += f"   📞 Total Calls: {stats['total_calls']}\n"
                output += f"   ✅ Success Rate: {stats['success_rate']:.1f}%\n"
                output += f"   📈 Avg MC Change: ${stats['avg_mc_change']:,.2f}\n"
                output += f"   🏷️  Unique Contracts: {stats['unique_contracts_count']}\n\n"
            
            return output
            
        except Exception as e:
            logger.error(f"Error in _analyze_group_performance: {e}")
            return f"Error analyzing group performance: {str(e)}"

    def _analyze_market_cap_changes(self, chain_filters: List[str],
                                  sort_by: str, sort_dir: str, limit: int) -> str:
        """Analyze market cap changes across different metrics."""
        return self._analyze_coins_with_price_difference(chain_filters, sort_by, sort_dir, limit)

    def _comprehensive_analysis(self, top_n: int, chain_filters: List[str]) -> str:
        """Provide a comprehensive analysis combining multiple metrics."""
        try:
            output = "🔍 COMPREHENSIVE TELEGRAM/DEX ANALYSIS\n"
            output += "=" * 50 + "\n\n"
            
            # Get top promoters
            promoters_result = self._analyze_top_promoters(top_n, 24, "total_mc_change", "desc")
            output += promoters_result + "\n\n"
            
            # Get top coins
            coins_result = self._analyze_coins_with_price_difference(
                chain_filters, "marketCapChangePercent", "desc", top_n
            )
            output += coins_result + "\n\n"
            
            # Get top groups
            groups_result = self._analyze_group_performance(top_n, 24)
            output += groups_result
            
            return output
            
        except Exception as e:
            logger.error(f"Error in _comprehensive_analysis: {e}")
            return f"Error in comprehensive analysis: {str(e)}"
