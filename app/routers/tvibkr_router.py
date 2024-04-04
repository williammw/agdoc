from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Depends, Request
from databases import Database
from app.dependencies import get_database
# from app.redis_config import get_redis
from pydantic import BaseModel, Field
from datetime import datetime


router = APIRouter()


class TradeSignal(BaseModel):
    order_action: str = Field(...,
                              description="The action of the order, e.g., buy or sell.")
    order_contracts: int = Field(...,
                                 description="The number of contracts or shares to trade.")
    ticker: str = Field(..., description="The ticker symbol for the asset.")
    new_strategy_position: int = Field(...,
                                       description="The new position size after the trade.")
    time: datetime = Field(..., description="The timestamp of the trade signal.")
    exchange: str = Field(...,
                          description="The exchange on which the trade should be executed.")
    passphrase: str = Field(...,
                            description="A passphrase for authentication or verification.")



@router.get("/")
async def greeting():
    return {"message": "Hello from tradingView and IBKR API!"}


# @router.post("/notify")
# async def send_notification(message: str, redis=Depends(get_redis)):
#     # Example operation: Store message in Redis
#     await redis.set("latest_notification", message)
#     return {"message": "Notification sent", "data": message}


# @router.get("/notify")
# async def get_notification(redis=Depends(get_redis)):
#     # Example operation: Retrieve message from Redis
#     message = await redis.get("latest_notification")
#     return {"message": "Latest notification", "data": message}


# https://cd75-171-22-104-187.ngrok-free.app/api/v1/tvibkr/trade_signal
@router.post("/trade_signal")
async def receive_trade_signal(signal: TradeSignal, db: Database = Depends(get_database)):
    query = """
    INSERT INTO dev_trade_signals (order_action, order_contracts, ticker, new_strategy_position, time, exchange, passphrase)
    VALUES (:order_action, :order_contracts, :ticker, :new_strategy_position, :time, :exchange, :passphrase)
    """
    values = {
        "order_action": signal.order_action,
        "order_contracts": signal.order_contracts,
        "ticker": signal.ticker,
        "new_strategy_position": signal.new_strategy_position,
        "time": signal.time,
        "exchange": signal.exchange,
        "passphrase": signal.passphrase
    }
    try:
        await db.execute(query=query, values=values)
        return {"message": "Trade signal inserted successfully."}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to insert trade signal: {str(e)}")
