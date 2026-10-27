//+------------------------------------------------------------------+
//|                                            MACD_MTF_Signal.mq5   |
//|  1時間足 MACD クロス + ローソク足 + 4H/日足 MACD 方向 のサインツール |
//|                                                                  |
//|  元ネタ: Maki@テクニカル先生 (@makitofx)                          |
//|  「月30万。忙しい社会人や主婦向けの手法」(X 記事, 2026-10-07)       |
//|  https://x.com/makitofx/status/2107750588322906446               |
//|                                                                  |
//|  ※ 本ツールは記事のルールを機械的に判定する補助ツールです。          |
//|    利益を保証するものではありません。                              |
//+------------------------------------------------------------------+
#property copyright "MACD MTF Signal"
#property version   "1.00"
#property description "H1 MACD(12,26,9) cross + candle + H4/D1 MACD direction signal"
#property indicator_chart_window
#property indicator_buffers 2
#property indicator_plots   2

#property indicator_label1  "Buy"
#property indicator_type1   DRAW_ARROW
#property indicator_color1  clrDodgerBlue
#property indicator_width1  3

#property indicator_label2  "Sell"
#property indicator_type2   DRAW_ARROW
#property indicator_color2  clrTomato
#property indicator_width2  3

//--- inputs
input group "MACD"
input int    InpFastEMA        = 12;    // MACD 短期EMA
input int    InpSlowEMA        = 26;    // MACD 長期EMA
input int    InpSignalSMA      = 9;     // MACD シグナル
input group "判定ルール"
input int    InpCrossLookback  = 3;     // クロス後、ローソク足条件を待つ最大本数(1=クロスと同じ足のみ)
input int    InpSlopeBars      = 1;     // 4H/日足 MACDライン上昇/下降の比較本数
input bool   InpUseH4          = true;  // 4時間足の方向を条件に含める
input bool   InpUseD1          = true;  // 日足の方向を条件に含める
input bool   InpBuyNeedBullish = true;  // ロング: 陽線を必須にする(記事の条件)
input bool   InpSellNeedBearish= false; // ショート: 陰線を必須にする(記事には明記なし)
input group "利確・損切(pips)"
input double InpTPPips         = 50;    // 利確 TP (記事: 40〜70、固定なら50)
input double InpSLPips         = 30;    // 損切 SL (記事: 30)
input double InpPipSize        = 0;     // 1pipの価格幅(0=自動: 3/5桁は10point)
input bool   InpDrawTPSL       = true;  // 最新サインのTP/SLラインを表示
input group "通知"
input bool   InpAlert          = true;  // アラート(ポップアップ)
input bool   InpPush           = false; // スマホへプッシュ通知
input bool   InpSound          = false; // サウンドのみ
input group "その他"
input int    InpMaxHistory     = 3000;  // 過去に遡って判定する最大本数
input bool   InpShowPanel      = true;  // 左上に判定状況を表示

//--- buffers / handles
double BuyBuf[];
double SellBuf[];
int    hH1 = INVALID_HANDLE, hH4 = INVALID_HANDLE, hD1 = INVALID_HANDLE;
double g_pip;
datetime g_lastAlertBar = 0;
const string OBJ_PREFIX = "MACDMTF_";

//+------------------------------------------------------------------+
int OnInit()
{
   SetIndexBuffer(0, BuyBuf, INDICATOR_DATA);
   SetIndexBuffer(1, SellBuf, INDICATOR_DATA);
   PlotIndexSetInteger(0, PLOT_ARROW, 233);
   PlotIndexSetInteger(1, PLOT_ARROW, 234);
   PlotIndexSetDouble(0, PLOT_EMPTY_VALUE, EMPTY_VALUE);
   PlotIndexSetDouble(1, PLOT_EMPTY_VALUE, EMPTY_VALUE);
   ArraySetAsSeries(BuyBuf, true);
   ArraySetAsSeries(SellBuf, true);

   if(InpCrossLookback < 1 || InpSlopeBars < 1)
   {
      Print("InpCrossLookback / InpSlopeBars は 1 以上にしてください");
      return INIT_PARAMETERS_INCORRECT;
   }

   hH1 = iMACD(_Symbol, PERIOD_H1, InpFastEMA, InpSlowEMA, InpSignalSMA, PRICE_CLOSE);
   hH4 = iMACD(_Symbol, PERIOD_H4, InpFastEMA, InpSlowEMA, InpSignalSMA, PRICE_CLOSE);
   hD1 = iMACD(_Symbol, PERIOD_D1, InpFastEMA, InpSlowEMA, InpSignalSMA, PRICE_CLOSE);
   if(hH1 == INVALID_HANDLE || hH4 == INVALID_HANDLE || hD1 == INVALID_HANDLE)
   {
      Print("iMACD ハンドルの作成に失敗しました: ", GetLastError());
      return INIT_FAILED;
   }

   if(InpPipSize > 0)
      g_pip = InpPipSize;
   else
      g_pip = (_Digits == 3 || _Digits == 5) ? _Point * 10 : _Point;

   IndicatorSetString(INDICATOR_SHORTNAME, "MACD MTF Signal");
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(hH1 != INVALID_HANDLE) IndicatorRelease(hH1);
   if(hH4 != INVALID_HANDLE) IndicatorRelease(hH4);
   if(hD1 != INVALID_HANDLE) IndicatorRelease(hD1);
   ObjectsDeleteAll(0, OBJ_PREFIX);
   Comment("");
}

//+------------------------------------------------------------------+
//| 上位足 MACDライン の方向                                          |
//| evalTime 時点で「確定済み」の上位足だけを使う (リペイント防止)        |
//| 戻り値: +1 上昇 / -1 下降 / 0 横ばい,  ok=false はデータ未準備      |
//+------------------------------------------------------------------+
int MtfSlope(int handle, ENUM_TIMEFRAMES tf, datetime evalTime, bool &ok)
{
   ok = false;
   int sh = iBarShift(_Symbol, tf, evalTime, false);
   if(sh < 0) return 0;
   datetime barOpen = iTime(_Symbol, tf, sh);
   if(barOpen == 0) return 0;
   if(barOpen + PeriodSeconds(tf) > evalTime) sh++;   // 未確定の足は1本ずらす

   double m[];
   ArraySetAsSeries(m, true);
   if(CopyBuffer(handle, MAIN_LINE, sh, InpSlopeBars + 1, m) != InpSlopeBars + 1) return 0;
   ok = true;
   double d = m[0] - m[InpSlopeBars];
   if(d > 0) return 1;
   if(d < 0) return -1;
   return 0;
}

//+------------------------------------------------------------------+
void DrawLevel(string name, datetime t1, datetime t2, double price, color clr, string text)
{
   string n = OBJ_PREFIX + name;
   if(ObjectFind(0, n) < 0)
      ObjectCreate(0, n, OBJ_TREND, 0, t1, price, t2, price);
   ObjectSetInteger(0, n, OBJPROP_TIME, 0, t1);
   ObjectSetDouble(0, n, OBJPROP_PRICE, 0, price);
   ObjectSetInteger(0, n, OBJPROP_TIME, 1, t2);
   ObjectSetDouble(0, n, OBJPROP_PRICE, 1, price);
   ObjectSetInteger(0, n, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, n, OBJPROP_STYLE, STYLE_DASH);
   ObjectSetInteger(0, n, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, n, OBJPROP_SELECTABLE, false);
   ObjectSetString(0, n, OBJPROP_TEXT, text);
   ObjectSetString(0, n, OBJPROP_TOOLTIP, text + " " + DoubleToString(price, _Digits));
}

//+------------------------------------------------------------------+
int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double &open[],
                const double &high[],
                const double &low[],
                const double &close[],
                const long &tick_volume[],
                const long &volume[],
                const int &spread[])
{
   if(_Period != PERIOD_H1)
   {
      Comment("MACD MTF Signal: 1時間足(H1)チャートに適用してください");
      return 0;
   }
   if(rates_total < InpSlowEMA + InpSignalSMA + InpCrossLookback + 5) return 0;
   if(BarsCalculated(hH1) < rates_total) return 0;

   ArraySetAsSeries(time, true);
   ArraySetAsSeries(open, true);
   ArraySetAsSeries(high, true);
   ArraySetAsSeries(low, true);
   ArraySetAsSeries(close, true);

   int limit;
   if(prev_calculated == 0)
   {
      ArrayInitialize(BuyBuf, EMPTY_VALUE);
      ArrayInitialize(SellBuf, EMPTY_VALUE);
      limit = MathMin(rates_total - (InpSlowEMA + InpSignalSMA + InpCrossLookback + 3), InpMaxHistory);
   }
   else
      limit = rates_total - prev_calculated + 1;   // 前回の形成中の足を確定足として再判定
   limit = MathMin(limit, rates_total - InpCrossLookback - 3);
   if(limit < 1) return 0;

   int need = limit + InpCrossLookback + 2;
   double mMain[], mSig[];
   ArraySetAsSeries(mMain, true);
   ArraySetAsSeries(mSig, true);
   if(CopyBuffer(hH1, MAIN_LINE, 0, need, mMain) != need) return 0;
   if(CopyBuffer(hH1, SIGNAL_LINE, 0, need, mSig) != need) return 0;

   BuyBuf[0]  = EMPTY_VALUE;   // 形成中の足ではサインを出さない
   SellBuf[0] = EMPTY_VALUE;

   int    lastSigBar = -1;
   int    lastSigDir = 0;
   string panel = "";

   for(int i = limit; i >= 1; i--)
   {
      BuyBuf[i]  = EMPTY_VALUE;
      SellBuf[i] = EMPTY_VALUE;

      // ① 1時間足 MACD クロス (直近 InpCrossLookback 本以内、かつ現在もクロス後の状態を維持)
      bool gc = false, dc = false;
      for(int k = i; k < i + InpCrossLookback; k++)
      {
         if(mMain[k] > mSig[k] && mMain[k + 1] <= mSig[k + 1]) gc = true;
         if(mMain[k] < mSig[k] && mMain[k + 1] >= mSig[k + 1]) dc = true;
      }
      gc = gc && mMain[i] > mSig[i];
      dc = dc && mMain[i] < mSig[i];

      // ② ローソク足 (確定足 i と その1本前 i+1 を比較)
      bool higherLow = low[i]  > low[i + 1];
      bool lowerHigh = high[i] < high[i + 1];
      bool bull = close[i] > open[i];
      bool bear = close[i] < open[i];
      bool candleBuy  = higherLow && (!InpBuyNeedBullish  || bull);
      bool candleSell = lowerHigh && (!InpSellNeedBearish || bear);

      // ③ 4時間足・日足 MACDライン の方向 (足 i が確定した時刻で判定)
      datetime evalTime = time[i] + PeriodSeconds(PERIOD_H1);
      bool ok4 = true, okD = true;
      int s4 = InpUseH4 ? MtfSlope(hH4, PERIOD_H4, evalTime, ok4) : 0;
      int sD = InpUseD1 ? MtfSlope(hD1, PERIOD_D1, evalTime, okD) : 0;
      if(!ok4 || !okD) return 0;   // 上位足データ未準備 → 次のティックで再計算
      bool mtfUp   = (!InpUseH4 || s4 > 0) && (!InpUseD1 || sD > 0);
      bool mtfDown = (!InpUseH4 || s4 < 0) && (!InpUseD1 || sD < 0);

      bool buy  = gc && candleBuy  && mtfUp;
      bool sell = dc && candleSell && mtfDown;

      // 同じクロスで2回以上サインを出さない
      for(int j = i + 1; j < i + InpCrossLookback && j < rates_total; j++)
      {
         if(BuyBuf[j]  != EMPTY_VALUE) buy  = false;
         if(SellBuf[j] != EMPTY_VALUE) sell = false;
      }

      if(buy)  BuyBuf[i]  = low[i]  - 3 * g_pip;
      if(sell) SellBuf[i] = high[i] + 3 * g_pip;

      if(i == 1)
      {
         panel = StringFormat(
            "MACD MTF Signal  [%s]\n"
            "直近確定足 %s の判定\n"
            "① 1H MACD : %s\n"
            "② ローソク足 : 安値切上げ=%s / 高値切下げ=%s / %s\n"
            "③ 4H MACD : %s   日足 MACD : %s\n"
            "TP %.0f pips / SL %.0f pips  (1pip=%s)",
            _Symbol, TimeToString(time[1], TIME_DATE | TIME_MINUTES),
            gc ? "ゴールデンクロス" : dc ? "デッドクロス" : (mMain[1] > mSig[1] ? "MACD > シグナル (クロスなし)" : "MACD < シグナル (クロスなし)"),
            higherLow ? "○" : "×", lowerHigh ? "○" : "×", bull ? "陽線" : bear ? "陰線" : "同値",
            !InpUseH4 ? "未使用" : s4 > 0 ? "上向き↑" : s4 < 0 ? "下向き↓" : "横ばい",
            !InpUseD1 ? "未使用" : sD > 0 ? "上向き↑" : sD < 0 ? "下向き↓" : "横ばい",
            InpTPPips, InpSLPips, DoubleToString(g_pip, _Digits));
      }
   }

   // 最新サインを探す (TP/SLライン・パネル用)
   for(int i = 1; i < MathMin(rates_total, InpMaxHistory); i++)
   {
      if(BuyBuf[i]  != EMPTY_VALUE) { lastSigBar = i; lastSigDir =  1; break; }
      if(SellBuf[i] != EMPTY_VALUE) { lastSigBar = i; lastSigDir = -1; break; }
   }

   if(InpDrawTPSL && lastSigBar > 0)
   {
      double entry = close[lastSigBar];   // 目安: サイン足の終値 (実際は次の足の始値で約定)
      double tp = entry + lastSigDir * InpTPPips * g_pip;
      double sl = entry - lastSigDir * InpSLPips * g_pip;
      datetime t1 = time[lastSigBar];
      datetime t2 = t1 + PeriodSeconds(PERIOD_H1) * 24;
      DrawLevel("Entry", t1, t2, entry, clrSilver, "Entry(目安)");
      DrawLevel("TP", t1, t2, tp, clrLimeGreen, StringFormat("TP +%.0fpips", InpTPPips));
      DrawLevel("SL", t1, t2, sl, clrRed, StringFormat("SL -%.0fpips", InpSLPips));
   }

   if(InpShowPanel)
   {
      if(lastSigBar > 0)
         panel += StringFormat("\n最新サイン: %s  %s", lastSigDir > 0 ? "BUY ▲" : "SELL ▼",
                               TimeToString(time[lastSigBar], TIME_DATE | TIME_MINUTES));
      Comment(panel);
   }

   // 通知: 新しく確定した足 (i=1) でサインが出たときだけ。初回ロード時は鳴らさない
   if(prev_calculated > 0 && time[1] != g_lastAlertBar)
   {
      g_lastAlertBar = time[1];
      int dir = BuyBuf[1] != EMPTY_VALUE ? 1 : SellBuf[1] != EMPTY_VALUE ? -1 : 0;
      if(dir != 0)
      {
         double entry = close[1];
         string msg = StringFormat("%s H1 %s サイン  目安Entry %s  TP %s  SL %s",
                                   _Symbol, dir > 0 ? "BUY" : "SELL",
                                   DoubleToString(entry, _Digits),
                                   DoubleToString(entry + dir * InpTPPips * g_pip, _Digits),
                                   DoubleToString(entry - dir * InpSLPips * g_pip, _Digits));
         if(InpAlert) Alert(msg);
         if(InpPush)  SendNotification(msg);
         if(InpSound) PlaySound("alert.wav");
      }
   }
   else if(prev_calculated == 0)
      g_lastAlertBar = time[1];

   return rates_total;
}
//+------------------------------------------------------------------+
