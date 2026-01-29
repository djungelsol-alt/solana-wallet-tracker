#!/usr/bin/env python3
"""
Solana Wallet Trade Tracker
===========================

This script demonstrates how to:
1. Track a Solana wallet's token trades
2. Get price data from DexScreener API
3. Get historical OHLCV data from GeckoTerminal API
4. Calculate min/max prices during holding periods
5. Monitor token performance after selling

APIs Used:
- DexScreener API (free, 300 req/min): Token data, pairs, search
- GeckoTerminal API (free, 30 req/min): OHLCV historical data
- Helius API (requires API key): Wallet transaction parsing

Usage:
    python solana_wallet_tracker.py

For full wallet tracking automation, you need:
- A Helius API key (free tier available at helius.dev)
- Or a Solana Tracker API key (solanatracker.io)
"""

import requests
import json
import time
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any
from enum import Enum


# ==============================================================================
# CONFIGURATION
# ==============================================================================

class Config:
    DEXSCREENER_BASE_URL = "https://api.dexscreener.com"
    GECKOTERMINAL_BASE_URL = "https://api.geckoterminal.com/api/v2"
    HELIUS_BASE_URL = "https://api-mainnet.helius-rpc.com/v0"
    
    # Rate limiting (requests per minute)
    DEXSCREENER_RATE_LIMIT = 300
    GECKOTERMINAL_RATE_LIMIT = 30
    
    # Default chain
    CHAIN_ID = "solana"
    NETWORK = "solana"


# ==============================================================================
# DATA MODELS
# ==============================================================================

class TradeStatus(Enum):
    OPEN = "open"
    CLOSED = "closed"


@dataclass
class Trade:
    """Represents a single trade"""
    id: str
    token_address: str
    token_symbol: str
    token_name: str
    pool_address: str
    dex_id: str
    buy_price: float
    buy_amount_usd: float
    buy_market_cap: Optional[float]
    buy_timestamp: str
    sell_price: Optional[float] = None
    sell_amount_usd: Optional[float] = None
    sell_timestamp: Optional[str] = None
    status: str = "open"
    notes: str = ""
    
    # Analysis results
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    min_timestamp: Optional[str] = None
    max_timestamp: Optional[str] = None
    pnl_percent: Optional[float] = None
    max_gain_percent: Optional[float] = None
    max_drawdown_percent: Optional[float] = None


@dataclass
class TokenData:
    """Token data from DexScreener"""
    address: str
    symbol: str
    name: str
    price_usd: float
    market_cap: Optional[float]
    volume_24h: Optional[float]
    liquidity_usd: Optional[float]
    price_change_24h: Optional[float]
    dex_id: str
    pair_address: str


# ==============================================================================
# API CLIENTS
# ==============================================================================

class DexScreenerAPI:
    """
    Client for DexScreener API
    
    Documentation: https://docs.dexscreener.com/api/reference
    
    Available endpoints:
    - GET /latest/dex/search?q={query} - Search tokens (300 req/min)
    - GET /token-pairs/v1/{chainId}/{tokenAddress} - Get token pools (300 req/min)
    - GET /latest/dex/pairs/{chainId}/{pairId} - Get pair data (300 req/min)
    - GET /tokens/v1/{chainId}/{tokenAddresses} - Get multiple tokens (300 req/min)
    - GET /token-boosts/latest/v1 - Get boosted tokens (60 req/min)
    - GET /token-boosts/top/v1 - Get top boosted (60 req/min)
    - GET /token-profiles/latest/v1 - Get token profiles (60 req/min)
    """
    
    def __init__(self):
        self.base_url = Config.DEXSCREENER_BASE_URL
        self.last_request_time = 0
        self.min_request_interval = 60 / Config.DEXSCREENER_RATE_LIMIT
    
    def _rate_limit(self):
        """Simple rate limiting"""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_request_interval:
            time.sleep(self.min_request_interval - elapsed)
        self.last_request_time = time.time()
    
    def search_token(self, query: str) -> List[Dict]:
        """
        Search for tokens by name or address
        
        Endpoint: GET /latest/dex/search?q={query}
        Rate limit: 300 req/min
        """
        self._rate_limit()
        url = f"{self.base_url}/latest/dex/search"
        params = {"q": query}
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            # Filter for Solana only
            pairs = data.get("pairs", [])
            solana_pairs = [p for p in pairs if p.get("chainId") == "solana"]
            return solana_pairs
            
        except requests.RequestException as e:
            print(f"DexScreener search error: {e}")
            return []
    
    def get_token_pairs(self, token_address: str) -> List[Dict]:
        """
        Get all pools for a token
        
        Endpoint: GET /token-pairs/v1/{chainId}/{tokenAddress}
        Rate limit: 300 req/min
        """
        self._rate_limit()
        url = f"{self.base_url}/token-pairs/v1/{Config.CHAIN_ID}/{token_address}"
        
        try:
            response = requests.get(url)
            response.raise_for_status()
            return response.json() or []
            
        except requests.RequestException as e:
            print(f"DexScreener token pairs error: {e}")
            return []
    
    def get_pair(self, pair_address: str) -> Optional[Dict]:
        """
        Get specific pair data
        
        Endpoint: GET /latest/dex/pairs/{chainId}/{pairId}
        Rate limit: 300 req/min
        """
        self._rate_limit()
        url = f"{self.base_url}/latest/dex/pairs/{Config.CHAIN_ID}/{pair_address}"
        
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            pairs = data.get("pairs", [])
            return pairs[0] if pairs else None
            
        except requests.RequestException as e:
            print(f"DexScreener pair error: {e}")
            return None
    
    def get_tokens(self, token_addresses: List[str]) -> List[Dict]:
        """
        Get multiple tokens data (up to 30 addresses)
        
        Endpoint: GET /tokens/v1/{chainId}/{tokenAddresses}
        Rate limit: 300 req/min
        """
        self._rate_limit()
        addresses = ",".join(token_addresses[:30])
        url = f"{self.base_url}/tokens/v1/{Config.CHAIN_ID}/{addresses}"
        
        try:
            response = requests.get(url)
            response.raise_for_status()
            return response.json() or []
            
        except requests.RequestException as e:
            print(f"DexScreener tokens error: {e}")
            return []
    
    def get_latest_boosted(self) -> List[Dict]:
        """
        Get latest boosted tokens
        
        Endpoint: GET /token-boosts/latest/v1
        Rate limit: 60 req/min
        """
        self._rate_limit()
        url = f"{self.base_url}/token-boosts/latest/v1"
        
        try:
            response = requests.get(url)
            response.raise_for_status()
            return response.json() or []
            
        except requests.RequestException as e:
            print(f"DexScreener boosted error: {e}")
            return []


class GeckoTerminalAPI:
    """
    Client for GeckoTerminal API
    
    Documentation: https://apiguide.geckoterminal.com/
    
    Key endpoints:
    - GET /networks/{network}/pools/{address}/ohlcv/{timeframe} - OHLCV data
    - GET /networks/{network}/pools/{address} - Pool info
    - GET /search/pools?query={query} - Search pools
    - GET /networks/{network}/tokens/{address}/pools - Token pools
    - GET /networks/{network}/pools/{address}/trades - Recent trades
    """
    
    def __init__(self):
        self.base_url = Config.GECKOTERMINAL_BASE_URL
        self.last_request_time = 0
        self.min_request_interval = 60 / Config.GECKOTERMINAL_RATE_LIMIT
    
    def _rate_limit(self):
        """Simple rate limiting"""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_request_interval:
            time.sleep(self.min_request_interval - elapsed)
        self.last_request_time = time.time()
    
    def get_ohlcv(
        self,
        pool_address: str,
        timeframe: str = "hour",
        aggregate: int = 1,
        limit: int = 100,
        currency: str = "usd"
    ) -> List[List]:
        """
        Get OHLCV candlestick data for a pool
        
        Endpoint: GET /networks/{network}/pools/{pool_address}/ohlcv/{timeframe}
        
        Args:
            pool_address: The pool/pair address
            timeframe: "day", "hour", or "minute"
            aggregate: Aggregation period (1, 4, 12 for hours; 1, 5, 15 for minutes)
            limit: Number of candles (max 1000)
            currency: "usd" or "token"
        
        Returns:
            List of [timestamp, open, high, low, close, volume]
        """
        self._rate_limit()
        url = f"{self.base_url}/networks/{Config.NETWORK}/pools/{pool_address}/ohlcv/{timeframe}"
        params = {
            "aggregate": aggregate,
            "limit": limit,
            "currency": currency
        }
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            return data.get("data", {}).get("attributes", {}).get("ohlcv_list", [])
            
        except requests.RequestException as e:
            print(f"GeckoTerminal OHLCV error: {e}")
            return []
    
    def get_pool(self, pool_address: str) -> Optional[Dict]:
        """
        Get pool information
        
        Endpoint: GET /networks/{network}/pools/{pool_address}
        """
        self._rate_limit()
        url = f"{self.base_url}/networks/{Config.NETWORK}/pools/{pool_address}"
        
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            return data.get("data", {}).get("attributes")
            
        except requests.RequestException as e:
            print(f"GeckoTerminal pool error: {e}")
            return None
    
    def search_pools(self, query: str) -> List[Dict]:
        """
        Search for pools
        
        Endpoint: GET /search/pools?query={query}
        """
        self._rate_limit()
        url = f"{self.base_url}/search/pools"
        params = {"query": query}
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])
            
        except requests.RequestException as e:
            print(f"GeckoTerminal search error: {e}")
            return []
    
    def get_token_pools(self, token_address: str) -> List[Dict]:
        """
        Get all pools for a token on Solana
        
        Endpoint: GET /networks/{network}/tokens/{token_address}/pools
        """
        self._rate_limit()
        url = f"{self.base_url}/networks/{Config.NETWORK}/tokens/{token_address}/pools"
        
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])
            
        except requests.RequestException as e:
            print(f"GeckoTerminal token pools error: {e}")
            return []
    
    def get_trades(self, pool_address: str, trade_volume_min: float = 0) -> List[Dict]:
        """
        Get recent trades for a pool
        
        Endpoint: GET /networks/{network}/pools/{pool_address}/trades
        """
        self._rate_limit()
        url = f"{self.base_url}/networks/{Config.NETWORK}/pools/{pool_address}/trades"
        params = {}
        if trade_volume_min > 0:
            params["trade_volume_in_usd_greater_than"] = trade_volume_min
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])
            
        except requests.RequestException as e:
            print(f"GeckoTerminal trades error: {e}")
            return []


class HeliusAPI:
    """
    Client for Helius API (requires API key)
    
    Sign up at https://helius.dev to get a free API key
    
    Key features:
    - Enhanced transaction parsing
    - Wallet transaction history
    - Real-time webhooks for trade detection
    """
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = Config.HELIUS_BASE_URL
    
    def get_wallet_transactions(
        self,
        wallet_address: str,
        tx_type: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        Get parsed transactions for a wallet
        
        Args:
            wallet_address: Solana wallet address
            tx_type: Filter by type (e.g., "SWAP", "TRANSFER")
            limit: Number of transactions
        
        Example types: SWAP, NFT_SALE, NFT_LISTING, TRANSFER, etc.
        """
        url = f"{self.base_url}/addresses/{wallet_address}/transactions"
        params = {"api-key": self.api_key}
        if tx_type:
            params["type"] = tx_type
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            return response.json()
            
        except requests.RequestException as e:
            print(f"Helius transactions error: {e}")
            return []
    
    def parse_transactions(self, signatures: List[str]) -> List[Dict]:
        """
        Parse raw transaction signatures into human-readable format
        """
        url = f"{self.base_url}/transactions/"
        params = {"api-key": self.api_key}
        payload = {"transactions": signatures}
        
        try:
            response = requests.post(url, json=payload, params=params)
            response.raise_for_status()
            return response.json()
            
        except requests.RequestException as e:
            print(f"Helius parse error: {e}")
            return []


# ==============================================================================
# TRADE ANALYZER
# ==============================================================================

class TradeAnalyzer:
    """Analyzes trade performance using historical data"""
    
    def __init__(self):
        self.dexscreener = DexScreenerAPI()
        self.geckoterminal = GeckoTerminalAPI()
    
    def analyze_trade(self, trade: Trade) -> Trade:
        """
        Analyze a trade to find min/max prices during holding period
        
        Args:
            trade: Trade object with buy details
        
        Returns:
            Trade object with analysis results filled in
        """
        if not trade.pool_address:
            print(f"No pool address for {trade.token_symbol}")
            return trade
        
        # Get OHLCV data
        ohlcv = self.geckoterminal.get_ohlcv(
            trade.pool_address,
            timeframe="hour",
            aggregate=1,
            limit=1000
        )
        
        if not ohlcv:
            print(f"No OHLCV data for {trade.token_symbol}")
            return trade
        
        # Parse timestamps
        try:
            buy_time = datetime.fromisoformat(trade.buy_timestamp.replace("Z", "+00:00"))
        except:
            buy_time = datetime.fromisoformat(trade.buy_timestamp)
        buy_timestamp = buy_time.timestamp()
        
        if trade.sell_timestamp:
            try:
                sell_time = datetime.fromisoformat(trade.sell_timestamp.replace("Z", "+00:00"))
            except:
                sell_time = datetime.fromisoformat(trade.sell_timestamp)
            sell_timestamp = sell_time.timestamp()
        else:
            sell_timestamp = time.time()
        
        # Filter candles within holding period
        # OHLCV format: [timestamp, open, high, low, close, volume]
        relevant_candles = []
        for candle in ohlcv:
            candle_time = candle[0]  # Unix timestamp in seconds
            if buy_timestamp <= candle_time <= sell_timestamp:
                relevant_candles.append(candle)
        
        if not relevant_candles:
            print(f"No candles in holding period for {trade.token_symbol}")
            return trade
        
        # Calculate min/max
        min_price = float('inf')
        max_price = float('-inf')
        min_ts = None
        max_ts = None
        
        for candle in relevant_candles:
            ts, open_p, high, low, close, vol = candle
            
            if low < min_price:
                min_price = low
                min_ts = ts
            
            if high > max_price:
                max_price = high
                max_ts = ts
        
        # Update trade with analysis
        trade.min_price = min_price
        trade.max_price = max_price
        trade.min_timestamp = datetime.fromtimestamp(min_ts).isoformat() if min_ts else None
        trade.max_timestamp = datetime.fromtimestamp(max_ts).isoformat() if max_ts else None
        
        # Calculate percentages
        if trade.buy_price > 0:
            trade.max_gain_percent = ((max_price - trade.buy_price) / trade.buy_price) * 100
            trade.max_drawdown_percent = ((min_price - trade.buy_price) / trade.buy_price) * 100
            
            if trade.sell_price:
                trade.pnl_percent = ((trade.sell_price - trade.buy_price) / trade.buy_price) * 100
        
        return trade
    
    def get_current_price(self, token_address: str) -> Optional[float]:
        """Get current price for a token"""
        pairs = self.dexscreener.get_token_pairs(token_address)
        if pairs:
            return float(pairs[0].get("priceUsd", 0))
        return None
    
    def get_post_sell_performance(self, trade: Trade) -> Dict:
        """
        Track token performance after selling
        
        Returns dict with:
        - current_price
        - price_change_since_sell
        - missed_gains or avoided_loss
        """
        if not trade.sell_price or not trade.token_address:
            return {}
        
        current_price = self.get_current_price(trade.token_address)
        if not current_price:
            return {}
        
        change_since_sell = ((current_price - trade.sell_price) / trade.sell_price) * 100
        
        return {
            "current_price": current_price,
            "price_change_since_sell": change_since_sell,
            "missed_gains": change_since_sell if change_since_sell > 0 else 0,
            "avoided_loss": abs(change_since_sell) if change_since_sell < 0 else 0
        }


# ==============================================================================
# WALLET TRACKER
# ==============================================================================

class WalletTracker:
    """
    Tracks wallet trades on Solana
    
    Note: For automatic trade detection, you need a Helius API key
    """
    
    def __init__(self, helius_api_key: Optional[str] = None):
        self.dexscreener = DexScreenerAPI()
        self.geckoterminal = GeckoTerminalAPI()
        self.helius = HeliusAPI(helius_api_key) if helius_api_key else None
        self.analyzer = TradeAnalyzer()
        self.trades: List[Trade] = []
    
    def add_manual_trade(
        self,
        token_address: str,
        buy_price: float,
        buy_amount_usd: float,
        buy_timestamp: str,
        sell_price: Optional[float] = None,
        sell_amount_usd: Optional[float] = None,
        sell_timestamp: Optional[str] = None,
        notes: str = ""
    ) -> Trade:
        """
        Manually add a trade
        
        Args:
            token_address: Solana token mint address
            buy_price: Price in USD when bought
            buy_amount_usd: Amount invested in USD
            buy_timestamp: ISO format timestamp
            sell_price: Price in USD when sold (optional)
            sell_amount_usd: Amount received in USD (optional)
            sell_timestamp: ISO format timestamp (optional)
            notes: Trade notes
        
        Returns:
            Trade object
        """
        # Get token info from DexScreener
        pairs = self.dexscreener.get_token_pairs(token_address)
        
        if not pairs:
            raise ValueError(f"Token not found: {token_address}")
        
        pair = pairs[0]  # Use the most liquid pair
        
        trade = Trade(
            id=f"trade_{int(time.time())}_{token_address[:8]}",
            token_address=token_address,
            token_symbol=pair.get("baseToken", {}).get("symbol", "UNKNOWN"),
            token_name=pair.get("baseToken", {}).get("name", "Unknown"),
            pool_address=pair.get("pairAddress", ""),
            dex_id=pair.get("dexId", ""),
            buy_price=buy_price,
            buy_amount_usd=buy_amount_usd,
            buy_market_cap=pair.get("marketCap"),
            buy_timestamp=buy_timestamp,
            sell_price=sell_price,
            sell_amount_usd=sell_amount_usd,
            sell_timestamp=sell_timestamp,
            status="closed" if sell_price else "open",
            notes=notes
        )
        
        self.trades.append(trade)
        return trade
    
    def detect_wallet_trades(self, wallet_address: str) -> List[Trade]:
        """
        Automatically detect trades from a wallet using Helius API
        
        Requires Helius API key
        """
        if not self.helius:
            raise ValueError("Helius API key required for automatic trade detection")
        
        # Get swap transactions
        swaps = self.helius.get_wallet_transactions(
            wallet_address,
            tx_type="SWAP",
            limit=100
        )
        
        detected_trades = []
        
        for swap in swaps:
            # Parse the swap transaction
            description = swap.get("description", "")
            timestamp = swap.get("timestamp")
            
            print(f"Detected swap: {description}")
        
        return detected_trades
    
    def analyze_all_trades(self):
        """Analyze all trades to find min/max prices"""
        for i, trade in enumerate(self.trades):
            print(f"Analyzing trade {i+1}/{len(self.trades)}: {trade.token_symbol}")
            self.trades[i] = self.analyzer.analyze_trade(trade)
    
    def get_portfolio_summary(self) -> Dict:
        """Get summary statistics for all trades"""
        if not self.trades:
            return {}
        
        closed_trades = [t for t in self.trades if t.status == "closed"]
        open_trades = [t for t in self.trades if t.status == "open"]
        
        winners = [t for t in closed_trades if t.sell_price and t.sell_price > t.buy_price]
        win_rate = len(winners) / len(closed_trades) * 100 if closed_trades else 0
        
        total_invested = sum(t.buy_amount_usd for t in self.trades if t.buy_amount_usd)
        
        total_pnl = 0
        for t in closed_trades:
            if t.pnl_percent:
                total_pnl += (t.buy_amount_usd or 0) * (t.pnl_percent / 100)
        
        avg_pnl = sum(t.pnl_percent or 0 for t in closed_trades) / len(closed_trades) if closed_trades else 0
        
        return {
            "total_trades": len(self.trades),
            "open_trades": len(open_trades),
            "closed_trades": len(closed_trades),
            "win_rate": win_rate,
            "total_invested": total_invested,
            "total_pnl": total_pnl,
            "avg_pnl_percent": avg_pnl
        }
    
    def print_trade_report(self, trade: Trade):
        """Print detailed trade report"""
        print("\n" + "="*60)
        print(f"TRADE REPORT: {trade.token_symbol} ({trade.token_name})")
        print("="*60)
        print(f"Status: {trade.status.upper()}")
        print(f"DEX: {trade.dex_id}")
        print(f"Token: {trade.token_address}")
        print(f"Pool: {trade.pool_address}")
        print("-"*60)
        print("BUY DETAILS:")
        print(f"  Price: ${trade.buy_price:.10f}")
        print(f"  Amount: ${trade.buy_amount_usd:.2f}")
        print(f"  Market Cap: ${trade.buy_market_cap:,.0f}" if trade.buy_market_cap else "  Market Cap: N/A")
        print(f"  Time: {trade.buy_timestamp}")
        
        if trade.sell_price:
            print("-"*60)
            print("SELL DETAILS:")
            print(f"  Price: ${trade.sell_price:.10f}")
            print(f"  Amount: ${trade.sell_amount_usd:.2f}" if trade.sell_amount_usd else "  Amount: N/A")
            print(f"  Time: {trade.sell_timestamp}")
        
        if trade.min_price is not None:
            print("-"*60)
            print("PERFORMANCE ANALYSIS:")
            print(f"  Max Price: ${trade.max_price:.10f} ({trade.max_gain_percent:+.2f}%)")
            print(f"  Min Price: ${trade.min_price:.10f} ({trade.max_drawdown_percent:+.2f}%)")
            if trade.pnl_percent is not None:
                pnl_emoji = "✅" if trade.pnl_percent > 0 else "❌"
                print(f"  Realized P&L: {trade.pnl_percent:+.2f}% {pnl_emoji}")
                
                # Calculate how much of max gain was captured
                if trade.max_gain_percent and trade.max_gain_percent > 0:
                    captured = (trade.pnl_percent / trade.max_gain_percent) * 100
                    print(f"  % of Max Captured: {captured:.1f}%")
        
        if trade.notes:
            print("-"*60)
            print(f"Notes: {trade.notes}")
        
        print("="*60 + "\n")
    
    def export_trades(self, filename: str = "trades.json"):
        """Export trades to JSON file"""
        data = [asdict(t) for t in self.trades]
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"Exported {len(self.trades)} trades to {filename}")
    
    def import_trades(self, filename: str = "trades.json"):
        """Import trades from JSON file"""
        with open(filename, 'r') as f:
            data = json.load(f)
        
        self.trades = [Trade(**t) for t in data]
        print(f"Imported {len(self.trades)} trades from {filename}")


# ==============================================================================
# EXAMPLE USAGE
# ==============================================================================

def demo_dexscreener():
    """Demonstrate DexScreener API usage"""
    print("\n" + "="*60)
    print("DEXSCREENER API DEMO")
    print("="*60)
    
    api = DexScreenerAPI()
    
    # Search for a token
    print("\n1. Searching for 'BONK'...")
    results = api.search_token("BONK")
    if results:
        print(f"   Found {len(results)} pairs")
        pair = results[0]
        print(f"   Top result: {pair['baseToken']['symbol']} - ${pair.get('priceUsd', 'N/A')}")
        print(f"   Market Cap: ${pair.get('marketCap', 0):,.0f}")
        print(f"   DEX: {pair.get('dexId')}")
    
    # Get token pairs by address (BONK token)
    bonk_address = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
    print(f"\n2. Getting pairs for BONK ({bonk_address[:20]}...)...")
    pairs = api.get_token_pairs(bonk_address)
    if pairs:
        print(f"   Found {len(pairs)} pools")
        for i, p in enumerate(pairs[:3]):
            print(f"   Pool {i+1}: {p.get('dexId')} - ${float(p.get('priceUsd', 0)):.10f}")


def demo_geckoterminal():
    """Demonstrate GeckoTerminal API usage"""
    print("\n" + "="*60)
    print("GECKOTERMINAL API DEMO")
    print("="*60)
    
    api = GeckoTerminalAPI()
    
    # Search for pools
    print("\n1. Searching for 'BONK' pools...")
    pools = api.search_pools("BONK")
    if pools:
        print(f"   Found {len(pools)} pools")
        pool = pools[0]
        attrs = pool.get("attributes", {})
        print(f"   Top pool: {attrs.get('name')}")
        print(f"   Address: {attrs.get('address')}")
    
    # Get OHLCV data
    # Using a known BONK/SOL pool address
    pool_address = "Gk9CfaWVY9y6wbfHqnDtMnLG5QJNquUxY7hcLc6NPv9P"
    print(f"\n2. Getting OHLCV data for pool {pool_address[:20]}...")
    ohlcv = api.get_ohlcv(pool_address, timeframe="hour", limit=24)
    if ohlcv:
        print(f"   Got {len(ohlcv)} candles")
        latest = ohlcv[0]  # Most recent
        print(f"   Latest candle:")
        print(f"   - Time: {datetime.fromtimestamp(latest[0]).isoformat()}")
        print(f"   - Open: ${latest[1]:.10f}")
        print(f"   - High: ${latest[2]:.10f}")
        print(f"   - Low: ${latest[3]:.10f}")
        print(f"   - Close: ${latest[4]:.10f}")
        print(f"   - Volume: ${latest[5]:,.2f}")


def demo_trade_tracking():
    """Demonstrate trade tracking workflow"""
    print("\n" + "="*60)
    print("TRADE TRACKING DEMO")
    print("="*60)
    
    tracker = WalletTracker()
    
    # Example: Add a manual trade
    print("\n1. Adding a sample trade...")
    
    try:
        trade = tracker.add_manual_trade(
            token_address="DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",  # BONK
            buy_price=0.00003,
            buy_amount_usd=100,
            buy_timestamp="2024-01-15T10:00:00Z",
            sell_price=0.00004,
            sell_amount_usd=133,
            sell_timestamp="2024-01-20T15:00:00Z",
            notes="BONK memecoin trade"
        )
        
        print(f"   Added trade: {trade.token_symbol}")
        
        # Analyze the trade
        print("\n2. Analyzing trade performance...")
        tracker.analyze_all_trades()
        
        # Print report
        tracker.print_trade_report(tracker.trades[0])
        
        # Get portfolio summary
        summary = tracker.get_portfolio_summary()
        print("\n3. Portfolio Summary:")
        for key, value in summary.items():
            if isinstance(value, float):
                print(f"   {key}: {value:.2f}")
            else:
                print(f"   {key}: {value}")
        
        # Check post-sell performance
        print("\n4. Checking post-sell performance...")
        post_sell = tracker.analyzer.get_post_sell_performance(trade)
        if post_sell:
            print(f"   Current price: ${post_sell['current_price']:.10f}")
            print(f"   Change since sell: {post_sell['price_change_since_sell']:+.2f}%")
            if post_sell['missed_gains'] > 0:
                print(f"   😢 Missed gains: {post_sell['missed_gains']:.2f}%")
            else:
                print(f"   🎯 Avoided loss: {post_sell['avoided_loss']:.2f}%")
    
    except Exception as e:
        print(f"   Error: {e}")


def main():
    """Main function"""
    print("\n" + "="*60)
    print("SOLANA WALLET TRACKER")
    print("="*60)
    print("""
This script demonstrates how to:
1. Use DexScreener API for token data
2. Use GeckoTerminal API for historical prices
3. Track trades and analyze performance

APIs Used:
- DexScreener: Token search, pairs, prices (300 req/min)
- GeckoTerminal: OHLCV data, pools (30 req/min)

For automatic wallet tracking, you need:
- Helius API key (helius.dev)
- Or Solana Tracker API (solanatracker.io)
""")
    
    # Run demos
    demo_dexscreener()
    time.sleep(2)  # Rate limit buffer
    
    demo_geckoterminal()
    time.sleep(2)
    
    demo_trade_tracking()


if __name__ == "__main__":
    main()
