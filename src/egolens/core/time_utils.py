"""Recording clock, not wall clock. Official HHMMSSFF names use 30 fps."""
import re

def recording_seconds(stamp, fps=30):
    value = str(stamp).zfill(8)
    if not re.fullmatch(r'\d{8}', value):
        raise ValueError('Expected HHMMSSFF')
    h, m, s, f = [int(value[i:i+2]) for i in range(0, 8, 2)]
    if h > 23 or m > 59 or s > 59 or f >= fps:
        raise ValueError('Invalid recording timestamp')
    return h*3600 + m*60 + s + f/fps

def explicit_constraints(question, query_day):
    days = {int(n) for n in re.findall(r'DAY\s*(\d+)', question, re.I)}
    days.update(int(n) for n in re.findall(r'第\s*(\d+)\s*天', question))
    match = re.search(r'(?<!\d)(\d{1,2}):(\d{2})(?::(\d{2}))?(?!\d)', question)
    interval = None
    if match:
        h, m = int(match[1]), int(match[2]); s = int(match[3] or 0)
        if h > 23 or m > 59 or s > 59:
            raise ValueError('Invalid explicit time')
        lo = h*3600+m*60+s
        interval = [lo, lo+(1 if match[3] else 60)]
        if not days: days = {int(str(query_day).replace('DAY',''))}
    return {'days':sorted(days), 'interval':interval}
