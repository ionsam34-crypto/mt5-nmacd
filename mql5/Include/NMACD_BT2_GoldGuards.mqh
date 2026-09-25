//+------------------------------------------------------------------+
//| NMACD_BT2_GoldGuards.mqh                                         |
//| Account-level risk guards for the NMACD BT2 gold EA.             |
//|                                                                  |
//| These guards sit OUTSIDE the tuned strategy logic. They never    |
//| open a trade and never change a signal. They only:               |
//|   - veto NEW legs (spread, rollover, news, lot cap, halts), and  |
//|   - close ALL owned legs when a loss limit is hit.               |
//|                                                                  |
//| Guard levels are chosen from how much you are willing to lose,   |
//| never optimized in the Strategy Tester. Optimizing them turns a  |
//| safety limit into another fitted parameter.                      |
//+------------------------------------------------------------------+
#ifndef NMACD_BT2_GOLD_GUARDS_MQH
#define NMACD_BT2_GOLD_GUARDS_MQH

input group "Gold Risk Guards (not for optimization)"
input bool   InpGG_Enable=true;
input double InpGG_BasketStopPctOfBalance=15.0;  // close all owned legs when floating net <= -X% of balance (0=off)
input double InpGG_DailyLossPct=20.0;            // realized+floating loss since server midnight; flatten and halt for the day (0=off)
input double InpGG_MaxEquityDrawdownPct=35.0;    // from equity high-water mark; flatten and halt until manual reset (0=off)
input bool   InpGG_ResetHardHalt=false;          // set true for ONE reattach to clear an equity-drawdown halt
input double InpGG_MaxTotalLots=0.0;             // cap on owned open volume across both sides (0=off)
input int    InpGG_CooldownMinutesAfterStop=240; // no new legs for this long after a basket stop
input double InpGG_SpreadMedianMultiple=3.0;     // block new legs when spread > X * rolling median spread (0=off)
input double InpGG_MaxSpreadPrice=0.80;          // absolute spread ceiling in PRICE units, e.g. 0.80 = $0.80 on gold (0=off)
input int    InpGG_RolloverBlockMinutes=10;      // block new legs +/- N minutes around server midnight (0=off)
input bool   InpGG_UseNewsFilter=true;
input int    InpGG_NewsBlockBeforeMinutes=15;
input int    InpGG_NewsBlockAfterMinutes=30;
input string InpGG_NewsCurrency="USD";
input string InpGG_NewsCsvFile="NMACD_news_high_impact.csv"; // Common\Files; used in the Strategy Tester (no live calendar there)

#define GG_SPREAD_RING 240
#define GG_SPREAD_MIN_SAMPLES 30
#define GG_MAX_NEWS 4096

string   g_gg_symbol="";
ulong    g_gg_magic=0;
ulong    g_gg_deviation=20;
bool     g_gg_ready=false;
bool     g_gg_is_tester=false;

double   g_gg_peak_equity=0.0;
bool     g_gg_hard_halt=false;
bool     g_gg_day_halt=false;
datetime g_gg_day_start=0;
double   g_gg_realized_today=0.0;
datetime g_gg_realized_refreshed_minute=0;
int      g_gg_last_leg_count=-1;
datetime g_gg_cooldown_until=0;
datetime g_gg_last_close_log_minute=0;
datetime g_gg_last_persist=0;

double   g_gg_spread_ring[GG_SPREAD_RING];
int      g_gg_spread_count=0;
int      g_gg_spread_head=0;
datetime g_gg_spread_last_minute=0;

datetime g_gg_news_times[];
string   g_gg_news_names[];
int      g_gg_news_count=0;
datetime g_gg_news_refreshed_at=0;
bool     g_gg_news_source_ok=false;

//--- time helpers (explicit long math; datetime modulo is not portable)
datetime GG_Floor(const datetime t,const int seconds)
  {
   return (datetime)((long)t-((long)t%seconds));
  }

long GG_SecondsOfDay(const datetime t)
  {
   return (long)t%86400;
  }

//--- persistence (live only; the tester always starts clean)
string GG_GlobalName(const string suffix)
  {
   return StringFormat("NMACD_GG_%I64u_%s",g_gg_magic,suffix);
  }

void GG_Persist(void)
  {
   if(g_gg_is_tester)
      return;
   GlobalVariableSet(GG_GlobalName("HardHalt"),g_gg_hard_halt ? 1.0 : 0.0);
   GlobalVariableSet(GG_GlobalName("Peak"),g_gg_peak_equity);
  }

void GG_Restore(void)
  {
   if(g_gg_is_tester)
      return;
   if(InpGG_ResetHardHalt)
     {
      GlobalVariableDel(GG_GlobalName("HardHalt"));
      GlobalVariableDel(GG_GlobalName("Peak"));
      PrintFormat("[WARNING] component=GoldGuards event=hard_halt_reset_by_owner equity=%.2f",
                  AccountInfoDouble(ACCOUNT_EQUITY));
      return;
     }
   if(GlobalVariableCheck(GG_GlobalName("Peak")))
      g_gg_peak_equity=MathMax(g_gg_peak_equity,GlobalVariableGet(GG_GlobalName("Peak")));
   if(GlobalVariableCheck(GG_GlobalName("HardHalt")))
      g_gg_hard_halt=(GlobalVariableGet(GG_GlobalName("HardHalt"))>=0.5);
   if(g_gg_hard_halt)
      PrintFormat("[ERROR] component=GoldGuards event=hard_halt_restored peak=%.2f equity=%.2f action=no_new_legs_until_InpGG_ResetHardHalt",
                  g_gg_peak_equity,AccountInfoDouble(ACCOUNT_EQUITY));
  }

//--- owned-position helpers
int GG_CountOwned(double &lots,double &floating_net)
  {
   lots=0.0;
   floating_net=0.0;
   int count=0;
   for(int i=PositionsTotal()-1;i>=0;--i)
     {
      const ulong ticket=PositionGetTicket(i);
      if(ticket==0 || !PositionSelectByTicket(ticket)) continue;
      if(PositionGetString(POSITION_SYMBOL)!=g_gg_symbol) continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC)!=g_gg_magic) continue;
      lots+=PositionGetDouble(POSITION_VOLUME);
      floating_net+=PositionGetDouble(POSITION_PROFIT)+PositionGetDouble(POSITION_SWAP);
      count++;
     }
   return count;
  }

bool GG_ClosePosition(const ulong ticket,const string reason)
  {
   if(!PositionSelectByTicket(ticket))
      return false;
   const ENUM_POSITION_TYPE type=(ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
   MqlTick tick;
   if(!SymbolInfoTick(g_gg_symbol,tick))
      return false;

   const long mask=SymbolInfoInteger(g_gg_symbol,SYMBOL_FILLING_MODE);
   ENUM_ORDER_TYPE_FILLING fills[3];
   int n=0;
   if((mask & SYMBOL_FILLING_IOC)!=0) fills[n++]=ORDER_FILLING_IOC;
   if((mask & SYMBOL_FILLING_FOK)!=0) fills[n++]=ORDER_FILLING_FOK;
   if(n==0) fills[n++]=ORDER_FILLING_RETURN;

   for(int k=0;k<n;k++)
     {
      MqlTradeRequest request;
      MqlTradeResult  result;
      ZeroMemory(request);
      ZeroMemory(result);
      request.action=TRADE_ACTION_DEAL;
      request.symbol=g_gg_symbol;
      request.magic=g_gg_magic;
      request.position=ticket;
      request.volume=PositionGetDouble(POSITION_VOLUME);
      request.type=(type==POSITION_TYPE_BUY ? ORDER_TYPE_SELL : ORDER_TYPE_BUY);
      request.price=(type==POSITION_TYPE_BUY ? tick.bid : tick.ask);
      request.deviation=g_gg_deviation;
      request.type_filling=fills[k];
      request.type_time=ORDER_TIME_GTC;
      request.comment="EXIT|"+reason;
      if(OrderSend(request,result) &&
         (result.retcode==TRADE_RETCODE_DONE || result.retcode==TRADE_RETCODE_DONE_PARTIAL ||
          result.retcode==TRADE_RETCODE_PLACED))
         return true;
      if(result.retcode!=TRADE_RETCODE_INVALID_FILL)
        {
         // TIMEOUT/CONNECTION: outcome unknown, so do not try another fill mode.
         // The next tick re-counts real positions and retries only what is still open.
         return false;
        }
     }
   return false;
  }

// Returns the number of legs still open after the attempt. Failed closes
// (market closed, requote) are retried on the next tick by the caller.
int GG_CloseAllOwned(const string reason)
  {
   for(int i=PositionsTotal()-1;i>=0;--i)
     {
      const ulong ticket=PositionGetTicket(i);
      if(ticket==0 || !PositionSelectByTicket(ticket)) continue;
      if(PositionGetString(POSITION_SYMBOL)!=g_gg_symbol) continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC)!=g_gg_magic) continue;
      GG_ClosePosition(ticket,reason);
     }
   double lots=0.0,floating=0.0;
   const int remaining=GG_CountOwned(lots,floating);
   const datetime minute=GG_Floor(TimeCurrent(),60);
   if(minute!=g_gg_last_close_log_minute)
     {
      g_gg_last_close_log_minute=minute;
      PrintFormat("[%s] component=GoldGuards event=flatten reason=%s remaining=%d equity=%.2f balance=%.2f",
                  remaining==0 ? "WARNING" : "ERROR",reason,remaining,
                  AccountInfoDouble(ACCOUNT_EQUITY),AccountInfoDouble(ACCOUNT_BALANCE));
     }
   return remaining;
  }

//--- daily realized P&L (owned deals closed since server midnight)
void GG_RefreshRealizedToday(void)
  {
   g_gg_realized_today=0.0;
   if(!HistorySelect(g_gg_day_start,TimeCurrent()+60))
      return;
   const int total=HistoryDealsTotal();
   for(int i=0;i<total;i++)
     {
      const ulong deal=HistoryDealGetTicket(i);
      if(deal==0) continue;
      if(HistoryDealGetString(deal,DEAL_SYMBOL)!=g_gg_symbol) continue;
      if((ulong)HistoryDealGetInteger(deal,DEAL_MAGIC)!=g_gg_magic) continue;
      const long entry=HistoryDealGetInteger(deal,DEAL_ENTRY);
      if(entry!=DEAL_ENTRY_OUT && entry!=DEAL_ENTRY_OUT_BY && entry!=DEAL_ENTRY_INOUT) continue;
      g_gg_realized_today+=HistoryDealGetDouble(deal,DEAL_PROFIT)
                           +HistoryDealGetDouble(deal,DEAL_COMMISSION)
                           +HistoryDealGetDouble(deal,DEAL_SWAP);
     }
  }

//--- spread tracking
double GG_CurrentSpreadPoints(void)
  {
   MqlTick tick;
   const double point=SymbolInfoDouble(g_gg_symbol,SYMBOL_POINT);
   if(point<=0.0 || !SymbolInfoTick(g_gg_symbol,tick))
      return -1.0;
   return (tick.ask-tick.bid)/point;
  }

void GG_SampleSpread(void)
  {
   const datetime minute=GG_Floor(TimeCurrent(),60);
   if(minute==g_gg_spread_last_minute)
      return;
   g_gg_spread_last_minute=minute;
   const double spread=GG_CurrentSpreadPoints();
   if(spread<0.0)
      return;
   g_gg_spread_ring[g_gg_spread_head]=spread;
   g_gg_spread_head=(g_gg_spread_head+1)%GG_SPREAD_RING;
   if(g_gg_spread_count<GG_SPREAD_RING)
      g_gg_spread_count++;
  }

double GG_MedianSpreadPoints(void)
  {
   if(g_gg_spread_count<GG_SPREAD_MIN_SAMPLES)
      return -1.0;
   double copy[];
   ArrayResize(copy,g_gg_spread_count);
   for(int i=0;i<g_gg_spread_count;i++)
      copy[i]=g_gg_spread_ring[i];
   ArraySort(copy);
   const int mid=g_gg_spread_count/2;
   return (g_gg_spread_count%2==1) ? copy[mid] : 0.5*(copy[mid-1]+copy[mid]);
  }

//--- news calendar
void GG_AddNews(const datetime t,const string name)
  {
   if(g_gg_news_count>=GG_MAX_NEWS)
      return;
   ArrayResize(g_gg_news_times,g_gg_news_count+1);
   ArrayResize(g_gg_news_names,g_gg_news_count+1);
   g_gg_news_times[g_gg_news_count]=t;
   g_gg_news_names[g_gg_news_count]=name;
   g_gg_news_count++;
  }

// CSV lines: "YYYY.MM.DD HH:MM,CUR,Event name" in trade-server time.
// Produced by Scripts\NMACD_ExportNewsCalendar.mq5.
bool GG_LoadNewsCsv(void)
  {
   const int handle=FileOpen(InpGG_NewsCsvFile,FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON|FILE_SHARE_READ);
   if(handle==INVALID_HANDLE)
      return false;
   g_gg_news_count=0;
   while(!FileIsEnding(handle))
     {
      const string line=FileReadString(handle);
      string parts[];
      if(StringSplit(line,',',parts)<2) continue;
      if(parts[1]!=InpGG_NewsCurrency) continue;
      const datetime t=StringToTime(parts[0]);
      if(t<=0) continue;
      GG_AddNews(t,ArraySize(parts)>2 ? parts[2] : "");
     }
   FileClose(handle);
   return g_gg_news_count>0;
  }

bool GG_LoadNewsLive(void)
  {
   const datetime now=TimeCurrent();
   MqlCalendarValue values[];
   ResetLastError();
   const int total=CalendarValueHistory(values,now-86400,now+7*86400,NULL,InpGG_NewsCurrency);
   if(total<0)
      return false;
   g_gg_news_count=0;
   for(int i=0;i<total;i++)
     {
      MqlCalendarEvent event;
      if(!CalendarEventById(values[i].event_id,event)) continue;
      if(event.importance!=CALENDAR_IMPORTANCE_HIGH) continue;
      GG_AddNews(values[i].time,event.name);
     }
   return true;
  }

void GG_RefreshNews(const bool force)
  {
   if(!InpGG_UseNewsFilter)
      return;
   if(g_gg_is_tester)
     {
      if(!force)
         return; // CSV loaded once for the whole test
      g_gg_news_source_ok=GG_LoadNewsCsv();
      PrintFormat("[%s] component=GoldGuards event=news_source mode=tester_csv file=%s events=%d%s",
                  g_gg_news_source_ok ? "INFO" : "ERROR",InpGG_NewsCsvFile,g_gg_news_count,
                  g_gg_news_source_ok ? "" : " note=NEWS_FILTER_INACTIVE_IN_THIS_TEST_run_the_export_script_first");
      return;
     }
   if(!force && TimeCurrent()-g_gg_news_refreshed_at<3600)
      return;
   g_gg_news_refreshed_at=TimeCurrent();
   bool ok=GG_LoadNewsLive();
   string mode="live_calendar";
   if(!ok)
     {
      ok=GG_LoadNewsCsv();
      mode="csv_fallback";
     }
   if(ok!=g_gg_news_source_ok || force)
      PrintFormat("[%s] component=GoldGuards event=news_source mode=%s events=%d",
                  ok ? "INFO" : "ERROR",mode,g_gg_news_count);
   g_gg_news_source_ok=ok;
  }

bool GG_InNewsWindow(const datetime now,string &event_name)
  {
   event_name="";
   if(!InpGG_UseNewsFilter || g_gg_news_count==0)
      return false;
   const long before=(long)MathMax(0,InpGG_NewsBlockBeforeMinutes)*60;
   const long after=(long)MathMax(0,InpGG_NewsBlockAfterMinutes)*60;
   for(int i=0;i<g_gg_news_count;i++)
     {
      const long delta=(long)now-(long)g_gg_news_times[i];
      if(delta>=-before && delta<=after)
        {
         event_name=g_gg_news_names[i];
         return true;
        }
     }
   return false;
  }

//--- public API ----------------------------------------------------

bool GG_Init(const string symbol,const ulong magic,const int deviation_points)
  {
   g_gg_symbol=symbol;
   g_gg_magic=magic;
   g_gg_deviation=(ulong)MathMax(0,deviation_points);
   g_gg_is_tester=(bool)MQLInfoInteger(MQL_TESTER);
   g_gg_peak_equity=AccountInfoDouble(ACCOUNT_EQUITY);
   g_gg_hard_halt=false;
   g_gg_day_halt=false;
   g_gg_day_start=GG_Floor(TimeCurrent(),86400);
   g_gg_realized_refreshed_minute=0;
   g_gg_last_leg_count=-1;
   g_gg_cooldown_until=0;
   g_gg_spread_count=0;
   g_gg_spread_head=0;
   g_gg_spread_last_minute=0;
   g_gg_news_count=0;
   g_gg_news_refreshed_at=0;
   g_gg_news_source_ok=false;
   if(!InpGG_Enable)
     {
      Print("[WARNING] component=GoldGuards event=disabled note=no_account_level_protection");
      g_gg_ready=true;
      return true;
     }
   GG_Restore();
   GG_RefreshNews(true);
   PrintFormat("[INFO] component=GoldGuards event=initialized basket_stop_pct=%.2f daily_loss_pct=%.2f equity_dd_pct=%.2f max_lots=%.2f cooldown_min=%d spread_x_median=%.2f spread_ceiling=%.2f rollover_min=%d news=%d(%d/%d %s) tester=%d",
               InpGG_BasketStopPctOfBalance,InpGG_DailyLossPct,InpGG_MaxEquityDrawdownPct,
               InpGG_MaxTotalLots,InpGG_CooldownMinutesAfterStop,InpGG_SpreadMedianMultiple,
               InpGG_MaxSpreadPrice,InpGG_RolloverBlockMinutes,InpGG_UseNewsFilter ? 1 : 0,
               InpGG_NewsBlockBeforeMinutes,InpGG_NewsBlockAfterMinutes,InpGG_NewsCurrency,
               g_gg_is_tester ? 1 : 0);
   g_gg_ready=true;
   return true;
  }

void GG_Deinit(void)
  {
   if(InpGG_Enable && g_gg_ready)
      GG_Persist();
   g_gg_ready=false;
  }

// Call first thing in OnTick, every tick (not only on new bars): loss
// limits must act on the price that exists now, not on the last M3 close.
void GG_OnTick(void)
  {
   if(!InpGG_Enable || !g_gg_ready)
      return;

   GG_SampleSpread();
   GG_RefreshNews(false);

   const datetime now=TimeCurrent();
   const double equity=AccountInfoDouble(ACCOUNT_EQUITY);
   const double balance=AccountInfoDouble(ACCOUNT_BALANCE);
   double lots=0.0,floating=0.0;
   const int legs=GG_CountOwned(lots,floating);

   // New server day: clear the daily halt (never the hard halt).
   const datetime day_start=GG_Floor(now,86400);
   if(day_start!=g_gg_day_start)
     {
      g_gg_day_start=day_start;
      g_gg_day_halt=false;
      g_gg_realized_refreshed_minute=0;
     }

   // 1. Equity drawdown from the high-water mark -> hard halt.
   if(equity>g_gg_peak_equity)
     {
      g_gg_peak_equity=equity;
      if(!g_gg_is_tester && now-g_gg_last_persist>=300)
        {
         g_gg_last_persist=now;
         GG_Persist();
        }
     }
   if(InpGG_MaxEquityDrawdownPct>0.0 && g_gg_peak_equity>0.0 && !g_gg_hard_halt)
     {
      const double dd_pct=(g_gg_peak_equity-equity)/g_gg_peak_equity*100.0;
      if(dd_pct>=InpGG_MaxEquityDrawdownPct)
        {
         g_gg_hard_halt=true;
         GG_Persist();
         PrintFormat("[ERROR] component=GoldGuards event=equity_dd_hard_halt dd_pct=%.2f peak=%.2f equity=%.2f legs=%d",
                     dd_pct,g_gg_peak_equity,equity,legs);
        }
     }
   if(g_gg_hard_halt && legs>0)
     {
      GG_CloseAllOwned("GG_EQUITY_DD");
      return;
     }

   // 2. Daily loss (realized since server midnight + floating now).
   if(InpGG_DailyLossPct>0.0)
     {
      const datetime minute=GG_Floor(now,60);
      if(minute!=g_gg_realized_refreshed_minute || legs<g_gg_last_leg_count)
        {
         g_gg_realized_refreshed_minute=minute;
         GG_RefreshRealizedToday();
        }
      const double day_pnl=g_gg_realized_today+floating;
      const double start_balance=balance-g_gg_realized_today;
      if(!g_gg_day_halt && start_balance>0.0 && -day_pnl>=start_balance*InpGG_DailyLossPct/100.0)
        {
         g_gg_day_halt=true;
         PrintFormat("[ERROR] component=GoldGuards event=daily_loss_halt day_pnl=%.2f start_balance=%.2f limit_pct=%.2f legs=%d",
                     day_pnl,start_balance,InpGG_DailyLossPct,legs);
        }
     }
   g_gg_last_leg_count=legs;
   if(g_gg_day_halt && legs>0)
     {
      GG_CloseAllOwned("GG_DAILY_LOSS");
      return;
     }

   // 3. Basket stop on floating net loss.
   if(InpGG_BasketStopPctOfBalance>0.0 && legs>0 && balance>0.0 &&
      floating<=-balance*InpGG_BasketStopPctOfBalance/100.0)
     {
      if(g_gg_cooldown_until<now)
         PrintFormat("[ERROR] component=GoldGuards event=basket_stop floating=%.2f balance=%.2f limit_pct=%.2f legs=%d lots=%.2f",
                     floating,balance,InpGG_BasketStopPctOfBalance,legs,lots);
      g_gg_cooldown_until=now+(long)MathMax(0,InpGG_CooldownMinutesAfterStop)*60;
      GG_CloseAllOwned("GG_BASKET_STOP");
     }
  }

// Entry veto. Call before any new leg is sent (and from the chart preview
// so the preview never shows a leg the guards would refuse).
bool GG_EntryAllowed(const double next_volume,string &reason)
  {
   reason="";
   if(!InpGG_Enable || !g_gg_ready)
      return true;
   const datetime now=TimeCurrent();

   if(g_gg_hard_halt)                { reason="gg_equity_dd_hard_halt"; return false; }
   if(g_gg_day_halt)                 { reason="gg_daily_loss_halt"; return false; }
   if(now<g_gg_cooldown_until)       { reason="gg_basket_stop_cooldown"; return false; }

   if(InpGG_MaxTotalLots>0.0)
     {
      double lots=0.0,floating=0.0;
      GG_CountOwned(lots,floating);
      if(lots+next_volume>InpGG_MaxTotalLots+1e-9)
        { reason=StringFormat("gg_total_lots_cap open=%.2f next=%.2f cap=%.2f",lots,next_volume,InpGG_MaxTotalLots); return false; }
     }

   const double spread=GG_CurrentSpreadPoints();
   const double point=SymbolInfoDouble(g_gg_symbol,SYMBOL_POINT);
   if(spread<0.0 || point<=0.0)      { reason="gg_spread_unavailable"; return false; }
   if(InpGG_MaxSpreadPrice>0.0 && spread*point>InpGG_MaxSpreadPrice)
     { reason=StringFormat("gg_spread_ceiling spread=%.2f ceiling=%.2f",spread*point,InpGG_MaxSpreadPrice); return false; }
   if(InpGG_SpreadMedianMultiple>0.0)
     {
      const double median=GG_MedianSpreadPoints();
      if(median>0.0 && spread>median*InpGG_SpreadMedianMultiple)
        { reason=StringFormat("gg_spread_vs_median spread_pts=%.1f median_pts=%.1f x=%.2f",spread,median,InpGG_SpreadMedianMultiple); return false; }
     }

   if(InpGG_RolloverBlockMinutes>0)
     {
      const long seconds_of_day=GG_SecondsOfDay(now);
      const long window=(long)InpGG_RolloverBlockMinutes*60;
      if(seconds_of_day<window || seconds_of_day>86400-window)
        { reason="gg_rollover_window"; return false; }
     }

   string event_name="";
   if(GG_InNewsWindow(now,event_name))
     { reason="gg_news_window "+event_name; return false; }

   return true;
  }

#endif // NMACD_BT2_GOLD_GUARDS_MQH
