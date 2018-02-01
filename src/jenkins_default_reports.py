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

import json
import os
import tempfile
import traceback
from functools import reduce
from multiprocessing import Pool
from os.path import exists
from urllib.request import urlopen

from src.utils import clear, Config, load_file, open_url_in_browser, pause, pick_value

JENKINS_URL = Config.JENKINS_URL
JENKINS_BRANCHES = Config.JENKINS_BRANCHES
JENKINS_PROJECT = Config.JENKINS_PROJECT

BUILDS_TO_CHECK = 50
MAX_RESULTS = 20


def generate_branch_report(report_type):
    """
    Generate a report for a branch
    """
    branch = pick_value('Which branch would you want to get a test report for? ',
                        JENKINS_BRANCHES, True, 'Cancel')
    if not branch:
        print("Invalid selection, please try again.")
        pause()
        return

    print("Downloading a list of builds...")
    url = '{}/job/{}-{}-{}/api/json'.format(JENKINS_URL, JENKINS_PROJECT, branch, report_type)
    try:
        response = urlopen(url)
    except IOError as ie:
        print('IOError on attempt to get test failure report. Exception: {}'.format(ie))
        print('   Attempted url: {}'.format(url))
        traceback.print_stack()
        return

    builds = json.loads(response.read())
    orig_build_numbers = set(list(map(lambda build: build['number'], builds['builds']))[:BUILDS_TO_CHECK])

    pool = Pool(processes=8)
    print("Downloading builds...")

    if not exists(_get_argus_dir()):
        os.mkdir(_get_argus_dir())
    if not exists(_get_branch_dir(branch)):
        os.mkdir(_get_branch_dir(branch))
    if not exists(_get_json_dir(branch, report_type)):
        os.mkdir(_get_json_dir(branch, report_type))

    pool.map(load_file, map(lambda bn: [branch, report_type, bn], orig_build_numbers))

    print("Processing builds...")
    test_cases = {}

    json_dir = _get_json_dir(branch, report_type)
    build_numbers = set([])
    for build_number in orig_build_numbers:
        file_name = os.path.join(json_dir, '{}.json'.format(build_number))
        if exists(file_name):
            with open(file_name) as f:
                build_numbers.add(build_number)
                data = json.load(f)
                for suite in data["suites"]:
                    for case in suite["cases"]:
                        qualifier = (case["className"], case["name"])

                        if qualifier in test_cases:
                            test_cases[qualifier].append(case["status"])
                        else:
                            test_cases.update({qualifier: [case["status"]]})

    def to_tuple(entry):
        k, statuses = entry
        my_sum = reduce(lambda a, i: a + i, map(
            lambda status: 1 if status == "FAILED" or status == "REGRESSION" else 0, statuses))
        return k, my_sum

    test_cases = map(to_tuple, test_cases.items())
    test_cases = sorted(test_cases, key=lambda tup: tup[1], reverse=True)
    test_cases = test_cases[:MAX_RESULTS]

    max_length = max(map(lambda x: len(x[0][0]) + len(x[0][1]), test_cases))

    clear()

    def print_separator():
        print('-' * (max_length + 5 + 3 + 35))

    print_separator()
    fmt = '| {:3d} | {:' + str(max_length + 5) + 's} | Failed {:3d} out of {:3d} times |'

    jump_numbers = list(range(0, MAX_RESULTS))
    for i in jump_numbers:
        (name, failed_times) = test_cases[i]
        if failed_times > 0:
            (class_name, method_name) = name

            full_name = '{}.{}'.format(class_name, method_name)
            print(fmt.format(i + 1, full_name, failed_times, len(build_numbers)))
    print_separator()

    selection: int = pick_value('Jump to the build #', jump_numbers, True, 'Cancel', True, True)
    if selection:
        (name, failed_times) = test_cases[selection]
        (class_name, method_name) = name
        url = '{}job/{}-{}-{}/lastCompletedBuild/testReport/{}/{}/history/'.format(
            JENKINS_URL, JENKINS_PROJECT, branch, report_type,
            _format_build(report_type, class_name), method_name.replace('-', '_'))
        open_url_in_browser(url)


def _format_build(build_type, name):
    parts = name.split('.')
    if build_type == 'testall':
        path = '.'.join(parts[:(len(parts) - 1)])
        class_name = parts[len(parts) - 1]
        return '{}/{}'.format(path, class_name)
    else:
        # TODO: this won't work for upgrade tests
        path = parts[0]
        class_name = parts[1]
        return '{}/{}'.format(path, class_name)


def _get_temp_dir():
    return tempfile.gettempdir()


def _get_json_dir(branch, build_type):
    return os.path.join(_get_temp_dir(), 'argus', branch, build_type)


def _get_branch_dir(branch):
    return os.path.join(_get_temp_dir(), 'argus', branch)


def _get_argus_dir():
    return os.path.join(_get_temp_dir(), 'argus')
