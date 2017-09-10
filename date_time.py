from datetime import datetime
import datetime as DT
import time
import calendar
class Clock(object):
    def __init__(self,offset=None):
        self.timezone=None
        if offset is not None:
            self.timezone=DT.timezone(DT.timedelta(hours=offset))
    def to_str(self,timestamp=None,with_orig=False):
        if not timestamp:
            timestamp=datetime.now(self.timezone)
        if with_orig:
            return timestamp,"{month_name} {day}, {year} {clock}".format(**self.as_dict(timestamp))
        return "{month_name} {day}, {year} {clock}".format(**self.as_dict(timestamp))
    def date(self,D=None):
        if D is None:
            D=datetime.now(self.timezone)
        months=[
            "Unesamber","Dutesamber","Trisesamber",
            "Tetresamber","Pentesamber","Hexesamber",
            "Sevesamber","Octesamber","Novesamber",
            "Desamber","Undesamber","Dodesamber",
            "Tridesamber","Year Day","Leap Day"
        ]
        D=D.timetuple()
        yd=D.tm_yday-1
        if calendar.isleap(D.tm_year):
            if yd==365:
                return "Leap Day"
            if yd==366:
                return "Year Day"
        elif yd==365:
            return "Year Day"
        P=yd/(365+int(calendar.isleap(D.tm_year)))
        month=int(P*(len(months)-2))
        month_name=months[month]
        day=((yd-1)%28)+1
        ret={"month_name":month_name,"month":month+1,"day":day,"year":D.tm_year}
        ret['date']="{month_name} {day}, {year}".format(**ret)
        return ret
    def time(self,D=None):
        if D is None:
            D=datetime.now(self.timezone)
        T=(D.time().microsecond/1000000+time.mktime(D.timetuple()))%(24*60*60)
        T="{:03.03f}".format((T/(24*60*60))*1000).zfill(7)
        T=T.replace(".",":")
        return {"clock":T,"above":T.split(":")[0],"below":T.split(":")[1]}
    def as_dict(self,D=None):
        if D is None:
            D=datetime.now(self.timezone)
        ret={'calendar':{
                "day":D.day,
                "month":D.month,
                "year":D.year,
                "time":D.time(),
                "date":D.date(),
                "hour":D.hour,
                "minute":D.minute,
                "second":D.second,
            }}
        ret.update(self.date(D))
        ret.update(self.time(D))
        ret['timestamp']="{month_name} {day}, {year} {clock}".format(**ret)
        return ret
Clock().time()