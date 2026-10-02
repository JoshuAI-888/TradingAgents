"""Deterministic civil-time capture cadence. No exchange-calendar or data-time claims.

Nonexistent wall-clock times are skipped. Ambiguous times use the later UTC
occurrence once. Dispatch catches up only the most recent due slot; it never
backdates a new capture to a scheduled slot or invents missed observations.
"""
from dataclasses import dataclass
from datetime import date,datetime,timedelta,timezone
from uuid import UUID,uuid5
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
import re

NAMESPACE=UUID('2d78558c-a65a-4d87-b749-551ade928606')


def aware_utc(value):
    if not isinstance(value,datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Use a timezone-aware instant')
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class CaptureCadence:
    timezone: str
    hour: int
    minute: int
    weekdays: tuple[int,...]=(0,1,2,3,4)

    def __post_init__(self):
        if not isinstance(self.timezone,str) or len(self.timezone)>80 or not re.fullmatch(r'[A-Za-z0-9_+-]+(?:/[A-Za-z0-9_+-]+)*',self.timezone):
            raise ValueError('Use a valid IANA timezone')
        try:ZoneInfo(self.timezone)
        except (ValueError,ZoneInfoNotFoundError):raise ValueError('Timezone data is unavailable') from None
        if type(self.hour) is not int or not 0<=self.hour<=23 or type(self.minute) is not int or not 0<=self.minute<=59:
            raise ValueError('Use a valid hour and minute')
        if not isinstance(self.weekdays,tuple) or not 1<=len(self.weekdays)<=7 or any(type(day) is not int or not 0<=day<=6 for day in self.weekdays) or len(set(self.weekdays))!=len(self.weekdays):
            raise ValueError('Choose unique weekdays, Monday=0 through Sunday=6')

    def occurrence(self,day:date):
        if type(day) is not date:raise ValueError('Use a calendar date')
        if day.weekday() not in self.weekdays:return None
        zone=ZoneInfo(self.timezone);candidates=[]
        for fold in (0,1):
            local=datetime(day.year,day.month,day.day,self.hour,self.minute,tzinfo=zone,fold=fold)
            utc=local.astimezone(timezone.utc);back=utc.astimezone(zone)
            if back.date()==day and back.hour==self.hour and back.minute==self.minute:candidates.append(utc)
        return max(candidates) if candidates else None

    def next_after(self,after:datetime):
        instant=aware_utc(after);first=instant.astimezone(ZoneInfo(self.timezone)).date()
        # Three weeks cover a weekly cadence whose DST-gap slot is skipped.
        for delta in range(22):
            candidate=self.occurrence(first+timedelta(days=delta))
            if candidate is not None and candidate>instant:return candidate
        raise ValueError('No next occurrence in the bounded calendar window')

    def latest_due(self,now:datetime,not_before:datetime):
        instant=aware_utc(now);floor=aware_utc(not_before)
        if floor>instant:return None
        latest=instant.astimezone(ZoneInfo(self.timezone)).date()
        for delta in range(22):
            candidate=self.occurrence(latest-timedelta(days=delta))
            if candidate is not None and candidate<=instant:return candidate if candidate>=floor else None
        return None


def occurrence_id(schedule_id,revision,due):
    try:sid=str(UUID(str(schedule_id)))
    except (TypeError,ValueError,AttributeError):raise ValueError('Invalid schedule identity') from None
    if type(revision) is not int or revision<1:raise ValueError('Invalid schedule revision')
    slot=aware_utc(due).isoformat(timespec='microseconds')
    return str(uuid5(NAMESPACE,f'{sid}:{revision}:{slot}'))
