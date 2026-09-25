//+------------------------------------------------------------------+
//| NMACD_ExportNewsCalendar.mq5                                     |
//| Exports high-impact economic calendar events to a CSV in         |
//| Terminal\Common\Files so the Strategy Tester (which has no live  |
//| calendar) can apply the same news blackout as the live EA.       |
//|                                                                  |
//| Run it once on a live/demo chart (any symbol) before testing.    |
//| Output: "YYYY.MM.DD HH:MM,CUR,Event name" in trade-server time,  |
//| the same clock the tester's history uses.                        |
//+------------------------------------------------------------------+
#property script_show_inputs
#property strict

input datetime InpFrom=D'2023.01.01 00:00';
input datetime InpTo=D'2026.12.31 23:59';
input string   InpCurrency="USD";
input ENUM_CALENDAR_EVENT_IMPORTANCE InpMinImportance=CALENDAR_IMPORTANCE_HIGH;
input string   InpFile="NMACD_news_high_impact.csv";

void OnStart()
  {
   MqlCalendarValue values[];
   ResetLastError();
   const int total=CalendarValueHistory(values,InpFrom,InpTo,NULL,InpCurrency);
   if(total<0)
     {
      PrintFormat("CalendarValueHistory failed error=%d (run this on a live/demo chart, not in the tester)",GetLastError());
      return;
     }

   const int handle=FileOpen(InpFile,FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(handle==INVALID_HANDLE)
     {
      PrintFormat("FileOpen failed file=%s error=%d",InpFile,GetLastError());
      return;
     }
   FileWriteString(handle,"server_time,currency,event\r\n");

   int written=0;
   for(int i=0;i<total;i++)
     {
      MqlCalendarEvent event;
      if(!CalendarEventById(values[i].event_id,event)) continue;
      if(event.importance<InpMinImportance) continue;
      string name=event.name;
      StringReplace(name,","," ");
      FileWriteString(handle,StringFormat("%s,%s,%s\r\n",
                                          TimeToString(values[i].time,TIME_DATE|TIME_MINUTES),
                                          InpCurrency,name));
      written++;
     }
   FileClose(handle);
   PrintFormat("Exported %d %s events (importance>=%s) from %s to %s into Common\\Files\\%s",
               written,InpCurrency,EnumToString(InpMinImportance),
               TimeToString(InpFrom),TimeToString(InpTo),InpFile);
  }
