"""
broker.py
=========
Broker adapter layer.  Provides a unified interface over Zerodha Kite,
Upstox v2, and Angel SmartAPI so the strategy code stays broker-agnostic.

Install:
    pip install kiteconnect upstox-python-sdk smartapi-python
"""

import os
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------
class BrokerBase(ABC):
    """Minimal interface required by the strategy."""

    @abstractmethod
    def login(self) -> None: ...

    @abstractmethod
    def get_quote(self, instruments: List[str]) -> Dict[str, Any]: ...

    @abstractmethod
    def get_option_chain(self, underlying: str, expiry: str, exchange: str) -> List[Dict]: ...

    @abstractmethod
    def place_order(
        self,
        tradingsymbol: str,
        exchange: str,
        transaction_type: str,   # "BUY" | "SELL"
        quantity: int,
        order_type: str,          # "MARKET" | "LIMIT" | "SL"
        price: float = 0.0,
        trigger_price: float = 0.0,
        product: str = "NRML",
        tag: str = "",
    ) -> str: ...                 # returns order_id

    @abstractmethod
    def get_order_status(self, order_id: str) -> Dict[str, Any]: ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> None: ...

    @abstractmethod
    def get_positions(self) -> List[Dict[str, Any]]: ...


# ---------------------------------------------------------------------------
# Zerodha Kite Connect adapter
# ---------------------------------------------------------------------------
class KiteBroker(BrokerBase):
    def __init__(self):
        from kiteconnect import KiteConnect
        api_key   = os.environ.get("KITE_API_KEY", "")
        api_secret = os.environ.get("KITE_API_SECRET", "")
        access_token = os.environ.get("KITE_ACCESS_TOKEN", "")

        self.kite = KiteConnect(api_key=api_key)
        if access_token:
            self.kite.set_access_token(access_token)
        self._api_secret = api_secret

    def login(self) -> None:
        """Interactive login — generates and sets access token."""
        import webbrowser
        url = self.kite.login_url()
        print(f"Open this URL and complete login:\n{url}")
        webbrowser.open(url)
        request_token = input("Paste the request_token from the redirect URL: ").strip()
        data = self.kite.generate_session(request_token, api_secret=self._api_secret)
        self.kite.set_access_token(data["access_token"])
        os.environ["KITE_ACCESS_TOKEN"] = data["access_token"]
        log.info("Kite login successful")

    def get_quote(self, instruments: List[str]) -> Dict[str, Any]:
        return self.kite.quote(instruments)

    def get_option_chain(self, underlying: str, expiry: str, exchange: str) -> List[Dict]:
        """
        Fetch all option strikes for given underlying and expiry.
        Returns list of dicts with keys: strike, instrument_type, tradingsymbol,
        last_price, bid, ask, oi, volume, instrument_token.
        """
        instruments = self.kite.instruments(exchange)
        chain = [
            i for i in instruments
            if i["name"] == underlying
            and i["expiry"].strftime("%Y-%m-%d") == expiry
            and i["instrument_type"] in ("CE", "PE")
        ]
        if not chain:
            return []
        # Enrich with live quotes
        tokens = [f"{exchange}:{i['tradingsymbol']}" for i in chain]
        quotes = {}
        # Kite quote API accepts max 500 instruments
        for batch_start in range(0, len(tokens), 500):
            batch = tokens[batch_start: batch_start + 500]
            quotes.update(self.kite.quote(batch))
        result = []
        for inst in chain:
            sym = f"{exchange}:{inst['tradingsymbol']}"
            q = quotes.get(sym, {})
            depth = q.get("depth", {})
            bid = depth.get("buy", [{}])[0].get("price", 0.0)
            ask = depth.get("sell", [{}])[0].get("price", 0.0)
            result.append({
                "strike": inst["strike"],
                "instrument_type": inst["instrument_type"],
                "tradingsymbol": inst["tradingsymbol"],
                "last_price": q.get("last_price", 0.0),
                "bid": bid,
                "ask": ask,
                "oi": q.get("oi", 0),
                "volume": q.get("volume", 0),
                "instrument_token": inst["instrument_token"],
                "exchange": exchange,
            })
        return result

    def place_order(self, tradingsymbol, exchange, transaction_type, quantity,
                    order_type, price=0.0, trigger_price=0.0,
                    product="NRML", tag="") -> str:
        from kiteconnect import KiteConnect
        kwargs = dict(
            tradingsymbol=tradingsymbol,
            exchange=exchange,
            transaction_type=transaction_type,
            quantity=quantity,
            order_type=order_type,
            product=product,
            tag=tag,
        )
        if order_type in ("LIMIT", "SL"):
            kwargs["price"] = price
        if order_type == "SL":
            kwargs["trigger_price"] = trigger_price
        order_id = self.kite.place_order(variety=KiteConnect.VARIETY_REGULAR, **kwargs)
        log.info("Order placed: %s %s %s x%d -> %s", transaction_type, tradingsymbol, order_type, quantity, order_id)
        return str(order_id)

    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        orders = self.kite.orders()
        for o in orders:
            if str(o["order_id"]) == order_id:
                return o
        return {}

    def cancel_order(self, order_id: str) -> None:
        from kiteconnect import KiteConnect
        self.kite.cancel_order(variety=KiteConnect.VARIETY_REGULAR, order_id=order_id)

    def get_positions(self) -> List[Dict[str, Any]]:
        pos = self.kite.positions()
        return pos.get("net", [])


# ---------------------------------------------------------------------------
# Upstox v2 adapter
# ---------------------------------------------------------------------------
class UpstoxBroker(BrokerBase):
    def __init__(self):
        import upstox_client
        self._client = upstox_client
        cfg = upstox_client.Configuration()
        cfg.access_token = os.environ.get("UPSTOX_ACCESS_TOKEN", "")
        self._api_client = upstox_client.ApiClient(cfg)

    def login(self) -> None:
        raise NotImplementedError("Complete Upstox OAuth2 flow in a browser, then set UPSTOX_ACCESS_TOKEN env var.")

    def get_quote(self, instruments: List[str]) -> Dict[str, Any]:
        import upstox_client
        api = upstox_client.MarketQuoteApi(self._api_client)
        symbol_str = ",".join(instruments)
        resp = api.get_full_market_quote(symbol_str, "v2")
        return resp.data or {}

    def get_option_chain(self, underlying: str, expiry: str, exchange: str) -> List[Dict]:
        import upstox_client
        api = upstox_client.OptionsApi(self._api_client)
        resp = api.get_option_contracts(underlying, expiry, "v2")
        if not resp or not resp.data:
            return []
        result = []
        for item in resp.data:
            result.append({
                "strike": item.strike_price,
                "instrument_type": item.instrument_type,
                "tradingsymbol": item.tradingsymbol,
                "last_price": item.last_price or 0.0,
                "bid": 0.0,
                "ask": 0.0,
                "oi": item.oi or 0,
                "volume": item.volume or 0,
                "instrument_token": item.instrument_key,
                "exchange": exchange,
            })
        return result

    def place_order(self, tradingsymbol, exchange, transaction_type, quantity,
                    order_type, price=0.0, trigger_price=0.0,
                    product="NRML", tag="") -> str:
        import upstox_client
        api = upstox_client.OrderApi(self._api_client)
        body = upstox_client.PlaceOrderRequest(
            quantity=quantity,
            product=product,
            validity="DAY",
            price=price,
            tag=tag,
            instrument_token=tradingsymbol,
            order_type=order_type,
            transaction_type=transaction_type,
            disclosed_quantity=0,
            trigger_price=trigger_price,
            is_amo=False,
        )
        resp = api.place_order(body, "v2")
        return resp.data.order_id

    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        import upstox_client
        api = upstox_client.OrderApi(self._api_client)
        resp = api.get_order_details(order_id, "v2")
        return resp.data.__dict__ if resp.data else {}

    def cancel_order(self, order_id: str) -> None:
        import upstox_client
        upstox_client.OrderApi(self._api_client).cancel_order(order_id, "v2")

    def get_positions(self) -> List[Dict[str, Any]]:
        import upstox_client
        resp = upstox_client.PortfolioApi(self._api_client).get_positions("v2")
        return [p.__dict__ for p in (resp.data or [])]


# ---------------------------------------------------------------------------
# Angel SmartAPI adapter
# ---------------------------------------------------------------------------
class AngelBroker(BrokerBase):
    def __init__(self):
        import pyotp
        from SmartApi import SmartConnect
        api_key   = os.environ.get("ANGEL_API_KEY", "")
        client_id = os.environ.get("ANGEL_CLIENT_ID", "")
        password  = os.environ.get("ANGEL_PASSWORD", "")
        totp_secret = os.environ.get("ANGEL_TOTP_SECRET", "")

        self.obj = SmartConnect(api_key=api_key)
        totp = pyotp.TOTP(totp_secret).now()
        data = self.obj.generateSession(client_id, password, totp)
        self._token = data["data"]["jwtToken"]

    def login(self) -> None:
        log.info("Angel login handled in __init__ via TOTP.")

    def get_quote(self, instruments: List[str]) -> Dict[str, Any]:
        # instruments expected as list of "exchange:symbol"
        payload = [{"exchange": s.split(":")[0], "symboltoken": s.split(":")[1], "interval": "ONE_MINUTE"} for s in instruments]
        resp = self.obj.getMarketData("FULL", payload)
        return resp.get("data", {})

    def get_option_chain(self, underlying: str, expiry: str, exchange: str) -> List[Dict]:
        resp = self.obj.getOptionChainByExpiry(underlying, exchange, expiry)
        if not resp or not resp.get("data"):
            return []
        result = []
        for row in resp["data"]:
            for opt_type in ("CE", "PE"):
                d = row.get(opt_type, {})
                if not d:
                    continue
                result.append({
                    "strike": row["strikePrice"],
                    "instrument_type": opt_type,
                    "tradingsymbol": d.get("tradingsymbol", ""),
                    "last_price": d.get("ltp", 0.0),
                    "bid": d.get("bidprice", 0.0),
                    "ask": d.get("askprice", 0.0),
                    "oi": d.get("opnInterest", 0),
                    "volume": d.get("volume", 0),
                    "instrument_token": d.get("symboltoken", ""),
                    "exchange": exchange,
                })
        return result

    def place_order(self, tradingsymbol, exchange, transaction_type, quantity,
                    order_type, price=0.0, trigger_price=0.0,
                    product="NRML", tag="") -> str:
        params = {
            "variety": "NORMAL",
            "tradingsymbol": tradingsymbol,
            "symboltoken": tradingsymbol,
            "transactiontype": transaction_type,
            "exchange": exchange,
            "ordertype": order_type,
            "producttype": product,
            "duration": "DAY",
            "price": str(price),
            "squareoff": "0",
            "stoploss": "0",
            "quantity": str(quantity),
        }
        resp = self.obj.placeOrder(params)
        return resp.get("data", {}).get("orderid", "")

    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        orders = self.obj.orderBook()
        for o in (orders.get("data") or []):
            if str(o.get("orderid")) == order_id:
                return o
        return {}

    def cancel_order(self, order_id: str) -> None:
        self.obj.cancelOrder(order_id, "NORMAL")

    def get_positions(self) -> List[Dict[str, Any]]:
        resp = self.obj.position()
        return resp.get("data") or []


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def get_broker(broker: str = "kite") -> BrokerBase:
    mapping = {
        "kite":   KiteBroker,
        "upstox": UpstoxBroker,
        "angel":  AngelBroker,
    }
    cls = mapping.get(broker.lower())
    if cls is None:
        raise ValueError(f"Unknown broker '{broker}'. Choose from: {list(mapping)}")
    return cls()
