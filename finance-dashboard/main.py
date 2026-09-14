from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
from dotenv import load_dotenv
import requests
from datetime import datetime, timedelta

load_dotenv()

app = FastAPI()

# CORS 設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静的ファイルの配置
app.mount("/static", StaticFiles(directory="static"), name="static")

# デモ用データ（実際には API から取得）
DEMO_DATA = {
    "AAPL": {
        "name": "Apple Inc.",
        "price": 189.45,
        "change": 2.50,
        "changePercent": 1.34,
        "history": [
            {"date": "2024-09-14", "price": 189.45},
            {"date": "2024-09-13", "price": 186.95},
            {"date": "2024-09-12", "price": 185.20},
            {"date": "2024-09-11", "price": 187.80},
            {"date": "2024-09-10", "price": 186.50},
        ]
    },
    "GOOGL": {
        "name": "Alphabet Inc.",
        "price": 138.20,
        "change": 1.80,
        "changePercent": 1.32,
        "history": [
            {"date": "2024-09-14", "price": 138.20},
            {"date": "2024-09-13", "price": 136.40},
            {"date": "2024-09-12", "price": 135.60},
            {"date": "2024-09-11", "price": 137.10},
            {"date": "2024-09-10", "price": 135.80},
        ]
    },
    "MSFT": {
        "name": "Microsoft Corporation",
        "price": 416.85,
        "change": 3.45,
        "changePercent": 0.83,
        "history": [
            {"date": "2024-09-14", "price": 416.85},
            {"date": "2024-09-13", "price": 413.40},
            {"date": "2024-09-12", "price": 411.50},
            {"date": "2024-09-11", "price": 415.20},
            {"date": "2024-09-10", "price": 412.90},
        ]
    },
    "TSLA": {
        "name": "Tesla Inc.",
        "price": 242.50,
        "change": -5.30,
        "changePercent": -2.13,
        "history": [
            {"date": "2024-09-14", "price": 242.50},
            {"date": "2024-09-13", "price": 247.80},
            {"date": "2024-09-12", "price": 248.90},
            {"date": "2024-09-11", "price": 245.60},
            {"date": "2024-09-10", "price": 250.20},
        ]
    }
}

@app.get("/")
async def root():
    return {"message": "Finance Dashboard API"}

@app.get("/api/stocks")
async def get_stocks():
    """全ての株価情報を取得"""
    try:
        stocks = []
        for symbol, data in DEMO_DATA.items():
            stocks.append({
                "symbol": symbol,
                "name": data["name"],
                "price": data["price"],
                "change": data["change"],
                "changePercent": data["changePercent"]
            })
        return JSONResponse(content={"stocks": stocks, "success": True})
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "success": False}
        )

@app.get("/api/stock/{symbol}")
async def get_stock_detail(symbol: str):
    """特定の株の詳細情報を取得"""
    try:
        symbol = symbol.upper()
        if symbol not in DEMO_DATA:
            return JSONResponse(
                status_code=404,
                content={"error": f"Stock {symbol} not found", "success": False}
            )

        data = DEMO_DATA[symbol]
        return JSONResponse(content={
            "symbol": symbol,
            "name": data["name"],
            "price": data["price"],
            "change": data["change"],
            "changePercent": data["changePercent"],
            "history": data["history"],
            "success": True
        })
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "success": False}
        )

@app.get("/api/portfolio")
async def get_portfolio():
    """ポートフォリオ情報を取得"""
    try:
        total_value = 0
        total_change = 0
        holdings = [
            {"symbol": "AAPL", "shares": 10, "purchasePrice": 150.00},
            {"symbol": "GOOGL", "shares": 5, "purchasePrice": 100.00},
            {"symbol": "MSFT", "shares": 8, "purchasePrice": 300.00},
            {"symbol": "TSLA", "shares": 3, "purchasePrice": 200.00},
        ]

        portfolio = []
        for holding in holdings:
            symbol = holding["symbol"]
            if symbol in DEMO_DATA:
                stock = DEMO_DATA[symbol]
                current_value = stock["price"] * holding["shares"]
                purchase_value = holding["purchasePrice"] * holding["shares"]
                change = current_value - purchase_value
                change_percent = (change / purchase_value * 100) if purchase_value > 0 else 0

                total_value += current_value
                total_change += change

                portfolio.append({
                    "symbol": symbol,
                    "name": stock["name"],
                    "shares": holding["shares"],
                    "currentPrice": stock["price"],
                    "purchasePrice": holding["purchasePrice"],
                    "currentValue": round(current_value, 2),
                    "gainLoss": round(change, 2),
                    "gainLossPercent": round(change_percent, 2)
                })

        return JSONResponse(content={
            "portfolio": portfolio,
            "totalValue": round(total_value, 2),
            "totalGainLoss": round(total_change, 2),
            "totalGainLossPercent": round((total_change / (total_value - total_change) * 100) if (total_value - total_change) > 0 else 0, 2),
            "success": True
        })
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "success": False}
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
