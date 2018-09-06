# Copyright 2018 DataStax, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import re
from datetime import datetime

import pytz
from dateutil.relativedelta import relativedelta

from src import utils


def current_time() -> datetime:
    # Implementation lifted from: https://stackoverflow.com/questions/4530069/python-how-to-get-a-value-of-datetime-today-that-is-timezone-aware
    return datetime.utcnow().replace(tzinfo=pytz.utc)


def since_now(delta: str) -> datetime:
    return since(current_time(), delta)


def since(source: datetime, delta: str) -> datetime:
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


def _extract_time(char: str, input: str) -> int:
    result_match = re.search('([\-0-9]+){}'.format(char), input)
    if result_match:
        return int(result_match.group(1))
    return 0
