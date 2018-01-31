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


class TestJenkinsServer(Tester):
    """
    Integration tests for interactions with Jenkins server.
    """

    def test_pickled_job_instance_equals_new_job_instance(self):
        """
        Tests that a dilled job_instance loaded from disk is identical to a new job_instance
        pulled directly from the jenkins server.
        """

        file_path = os.path.join(self.JOB_INSTANCES_DIR, self.build_data_file('job_with_no_builds'))
        with open(file_path, 'rb') as data_file:
            deserialized_server_job = dill.load(data_file)

        # todo: figure out how to do this without referencing jenkins-cassandra
        url = 'http://jenkins-cassandra.datastax.lan/'
        # todo: replace call to shuler's job with a job specifically for testing
        job_name = 'mshuler-9608-java9-trunk-cqlsh-tests'

        jenkins_server = Jenkins(url)
        server_job = jenkins_server.get_job(job_name)

        self.assertEqual(deserialized_server_job, server_job,
                         'The deserialized server job does not equal the new server job')

    def test_pickled_jenkins_job_equals_new_jenkins_job(self):
        """
        Tests that a pickled jenkins_job loaded from disk is identical to a new jenkins_job
        created from a job_instance pulled from the jenkins server.
        """

        file_path = os.path.join(self.JENKINS_JOBS_DIR, self.build_data_file('job_with_no_builds'))
        with open(file_path, 'rb') as data_file:
            pickled_jenkins_job = JenkinsJob.deserialize(data_file)

        url = 'http://jenkins-cassandra.datastax.lan/'
        job_name = 'mshuler-9608-java9-trunk-cqlsh-tests'

        jenkins_obj = Jenkins(url)
        jenkins_builds = download_builds(jenkins_obj, job_name)
        jenkins_job = JenkinsJob(job_name, jenkins_builds)

        self.assertEqual(pickled_jenkins_job, jenkins_job,
                         'The pickled jenkins job does not match the new jenkins job.')
