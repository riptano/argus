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

"""
This script is used to download a set of builds to be used for various unit tests.

The running of this script should not be automated, as the test that it depends on was not created
for the purpose of running unit tests. Rather, it should be run once and the resulting file should
be saved and added to version control.
"""
import os

import dill
from jenkinsapi.jenkins import Jenkins

from src.jenkins_interface import download_builds
from tests.argus_test import Tester

filename = 'build.dat'
url = 'http://jenkins-cassandra.datastax.lan/'
job_name = 'fallout-daily-regression-viewer'

jenkins_obj = Jenkins(url)
builds = download_builds(jenkins_obj, job_name)

# Use dill to create exact copy of job_instance from server
with open(os.path.join(Tester.DATA_DIR, filename), 'wb') as data_file:
    dill.dump(builds, data_file)
