import re
from datetime import datetime

import pytz
from dateutil.relativedelta import relativedelta

from src import utils


def current_time():
    # type: () -> datetime
    # Implementation lifted from: https://stackoverflow.com/questions/4530069/python-how-to-get-a-value-of-datetime-today-that-is-timezone-aware
    return datetime.utcnow().replace(tzinfo=pytz.utc)


def since_now(delta):
    # type: (str) -> datetime
    return since(current_time(), delta)


def since(source, delta):
    # type: (datetime, str) -> datetime
    """
    Accepts string in format '-123d 3w 5m', negative optional on each, can take multiple space delim options
    :return: datetime object representing deltasd interval from datetime.now()
    """
    day_delta = _extract_time('d', delta)
    week_delta = _extract_time('w', delta)
    month_delta = _extract_time('m', delta)
    year_delta = _extract_time('y', delta)
    utils.argus_debug('since input source: {}. delta: [{}]. days:{} weeks:{} months:{} years:{}'.format(
        source, delta, day_delta, week_delta, month_delta, year_delta
    ))

    return source + relativedelta(days=day_delta, weeks=week_delta, months=month_delta, years=year_delta)


def _extract_time(char, input):
    # type: (str, str) -> int
    result_match = re.search('([\-0-9]+){}'.format(char), input)
    if result_match:
        return int(result_match.group(1))
    return 0
