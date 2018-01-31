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

import dill
from jenkinsapi.jenkins import Jenkins

from src.jenkins_interface import download_builds
from src.jenkins_job import JenkinsJob
from tests.argus_test import Tester


FILENAME = '{}.dat'.format('job_with_no_builds')

url = 'http://jenkins-cassandra.datastax.lan/'
job_name = 'mshuler-9608-java9-trunk-cqlsh-tests'

jenkins_obj = Jenkins(url)
job_instance = jenkins_obj.get_job(job_name)
builds = download_builds(jenkins_obj, job_name)

# Use dill to create exact copy of job_instance from server
with open(os.path.join(Tester.JOB_INSTANCES_DIR, FILENAME), 'wb') as data_file:
    dill.dump(job_instance, data_file)

jenkins_job = JenkinsJob(job_name, builds)

# Use serialize() method to store jenkins_job as argus does
with open(os.path.join(Tester.JENKINS_JOBS_DIR, FILENAME), 'wb') as data_file:
    jenkins_job.serialize(data_file)
