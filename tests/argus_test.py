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
from unittest import TestCase

import dill
from src import utils; utils.unit_test = True
from tests.utils import clean_test_files


class Tester(TestCase):
    DATA_DIR = os.path.join(os.path.dirname(__file__), 'test_data')
    JOB_INSTANCES_DIR = os.path.join(DATA_DIR, 'job_instances')
    JENKINS_JOBS_DIR = os.path.join(DATA_DIR, 'jenkins_jobs')

    def setUp(self):
        clean_test_files()
        utils.Config.init_argus()

    @staticmethod
    def build_data_file(file_str):
        return '{}.dat'.format(file_str)

    @staticmethod
    def get_builds_from_file(filename):
        path = os.path.join(Tester.DATA_DIR, filename)
        with open(path, 'rb') as file_handle:
            builds = dill.load(file_handle)
        return builds

    @staticmethod
    def create_builds_dict(builds):
        builds_dict = {}
        for build in builds:
            builds_dict.update({build.number: build})
        return builds_dict

    def tearDown(self):
        clean_test_files()
