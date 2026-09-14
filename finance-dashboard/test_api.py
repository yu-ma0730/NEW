#!/usr/bin/env python3
"""
金融ダッシュボード API テストスクリプト
"""

import requests
import json
from typing import Optional

BASE_URL = "http://localhost:8000"

class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_section(title: str):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}{Colors.ENDC}\n")

def print_success(message: str):
    print(f"{Colors.GREEN}✅ {message}{Colors.ENDC}")

def print_error(message: str):
    print(f"{Colors.RED}❌ {message}{Colors.ENDC}")

def print_info(message: str):
    print(f"{Colors.CYAN}ℹ️  {message}{Colors.ENDC}")

def test_api(endpoint: str, method: str = "GET") -> Optional[dict]:
    """API エンドポイントをテスト"""
    try:
        url = f"{BASE_URL}{endpoint}"
        response = requests.get(url, timeout=5)

        if response.status_code == 200:
            data = response.json()
            print_success(f"GET {endpoint}")
            print(json.dumps(data, indent=2, ensure_ascii=False))
            return data
        else:
            print_error(f"GET {endpoint} - Status: {response.status_code}")
            return None
    except requests.exceptions.ConnectionError:
        print_error(f"Connection failed. Is the server running at {BASE_URL}?")
        return None
    except Exception as e:
        print_error(f"Error: {str(e)}")
        return None

def main():
    print(f"\n{Colors.BOLD}{Colors.BLUE}")
    print("╔════════════════════════════════════════╗")
    print("║  金融データ可視化ダッシュボール テスト  ║")
    print("╚════════════════════════════════════════╝")
    print(f"{Colors.ENDC}")

    print_info(f"API ベース URL: {BASE_URL}")

    # 1. ルートエンドポイント
    print_section("1. ルートエンドポイント")
    test_api("/")

    # 2. 全銘柄の株価
    print_section("2. 全銘柄の株価情報")
    stocks_data = test_api("/api/stocks")

    # 3. 個別銘柄の詳細
    if stocks_data and stocks_data.get("success"):
        print_section("3. 個別銘柄の詳細情報")
        for stock in stocks_data["stocks"][:2]:
            print_info(f"テスト銘柄: {stock['symbol']}")
            test_api(f"/api/stock/{stock['symbol']}")
            print()

    # 4. ポートフォリオ
    print_section("4. ポートフォリオ情報")
    portfolio_data = test_api("/api/portfolio")

    # サマリー
    print_section("テスト結果サマリー")
    if stocks_data and portfolio_data:
        if stocks_data.get("success") and portfolio_data.get("success"):
            print_success("すべてのエンドポイントが正常に動作しています")
            print_info(f"取得した銘柄数: {len(stocks_data['stocks'])}")
            print_info(f"ポートフォリオ総資産: ${portfolio_data['totalValue']:.2f}")
            print_info(f"総利益: ${portfolio_data['totalGainLoss']:.2f} ({portfolio_data['totalGainLossPercent']:.2f}%)")
        else:
            print_error("API レスポンスにエラーがあります")
    else:
        print_error("API テストが失敗しました")

    print(f"\n{Colors.BOLD}{Colors.GREEN}テスト完了！{Colors.ENDC}\n")

if __name__ == "__main__":
    main()
