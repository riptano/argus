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
from configparser import RawConfigParser

CUSTOM_PARAMS_PATH = 'conf/custom_params.cfg'

JENKINS_URL = ''
JENKINS_BRANCHES = ''
JENKINS_PROJECT = ''

custom_params_path = CUSTOM_PARAMS_PATH
if not os.path.exists(custom_params_path):
    print('WARNING! Cannot find conf/custom_params.cfg. Will not have default project nor jenkins config data.')
    JENKINS_URL = 'https://test.jenkins.com'
    JENKINS_BRANCHES = ['branch_1.0', 'branch_2.0', 'branch_3.0']
    JENKINS_PROJECT = ['project_1', 'project_2', 'project_3']
else:
    config_parser = RawConfigParser()
    config_parser.read(custom_params_path)
    JENKINS_URL = config_parser.get('JENKINS', 'url').rstrip('/')
    JENKINS_BRANCHES = config_parser.get('JENKINS', 'branches').split(',')
    JENKINS_PROJECT = config_parser.get('JENKINS', 'project_name')
