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

import os
import shutil
from configparser import ConfigParser
from src.utils import TEST_DIR


def clean_test_files():
    """
    Deletes any files that could have been created by running tests
    """
    test_conf_path = os.path.join(TEST_DIR, 'conf')
    test_data_path = os.path.join(TEST_DIR, 'data')
    deleted_folders = False

    if os.path.exists(test_conf_path):
        print('Removing path {} from previous test'.format(test_conf_path))
        deleted_folders = True
        shutil.rmtree(test_conf_path)

    if os.path.exists(test_data_path):
        print('Removing path {} from previous test'.format(test_data_path))
        deleted_folders = True
        shutil.rmtree(test_data_path)

    if not deleted_folders:
        print('Test directory, "{}", is clean')
        print('No files removed')


def parser_to_dict(filename):
    if not os.path.exists(filename):
        raise Exception('{} does not exist'.format(filename))
    cp = ConfigParser()
    cp.read(filename)
    data = {}
    for section in cp.sections():
        data[section] = {}
        for option in cp.options(section):
            data[section].update({option: cp.get(section, option)})
    return data


def csv_to_list(row):
    return sorted(filter(None, [r for r in row.split(',')]))
