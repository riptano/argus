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
Contains all existing unit tests for the JenkinsJob class.

Since JenkinsJob does not contain any calls to the Jenkins server, it can be fully tested offline
without the need for integration tests.
"""

from src.jenkins_job import JenkinsJob
from tests.argus_test import Tester


class TestJenkinsJobMethods(Tester):
    """Unit tests for JenkinsJob methods."""

    def test_get_job_health(self):
        """Test all the different possible inputs to the get_job_health static method."""
        health = JenkinsJob._get_job_health(failed_builds=3, builds_checked=3)
        self.assertEqual(health, 'BAD')

        health = JenkinsJob._get_job_health(failed_builds=2, builds_checked=3)
        self.assertEqual(health, 'BAD')

        health = JenkinsJob._get_job_health(failed_builds=1, builds_checked=3)
        self.assertEqual(health, 'FAIR')

        health = JenkinsJob._get_job_health(failed_builds=0, builds_checked=3)
        self.assertEqual(health, 'GOOD')

        health = JenkinsJob._get_job_health(failed_builds=2, builds_checked=2)
        self.assertEqual(health, 'BAD')

        health = JenkinsJob._get_job_health(failed_builds=1, builds_checked=2)
        self.assertEqual(health, 'FAIR')

        health = JenkinsJob._get_job_health(failed_builds=0, builds_checked=2)
        self.assertEqual(health, 'GOOD')

        health = JenkinsJob._get_job_health(failed_builds=1, builds_checked=1)
        self.assertEqual(health, 'BAD')

        health = JenkinsJob._get_job_health(failed_builds=0, builds_checked=1)
        self.assertEqual(health, 'GOOD')

        health = JenkinsJob._get_job_health(failed_builds=0, builds_checked=0)
        self.assertEqual(health, 'N/A')

    def test_get_build_failures(self):
        """Tests that the correct number of build failures are counted by get_build_failures."""
        builds = self.get_builds_from_file('builds/builds_SUCCESS_and_FAILURE.dat')
        failed_builds, _ = JenkinsJob._get_build_failures(builds)
        self.assertEqual(failed_builds, 8,
                         'The number of failed builds was not counted correctly.')


class TestJenkinsJobConstructor(Tester):
    """Unit tests for all types of builds to test JenkinsJob __init__ method."""

    def setUp(self):
        super().setUp()
        self.job_name = 'test-job'

    def test_creation_of_jenkins_job_with_no_builds(self):
        """Test that a new Jenkins job can be created with no builds."""
        builds = []
        builds_dict = {}

        jenkins_job = JenkinsJob(self.job_name, builds)
        self.apply_assertions(jenkins_job, builds_dict)

    def test_creation_of_jenkins_job_with_builds(self):
        """Test that a new Jenkins job can be created with a list of builds."""
        builds = self.get_builds_from_file('builds/builds.dat')
        builds_dict = self.create_builds_dict(builds)

        jenkins_job = JenkinsJob(self.job_name, builds)
        self.apply_assertions(jenkins_job, builds_dict)

    def test_creation_of_jenkins_job_with_aborted_build(self):
        """Test that a new Jenkins job can be created with a build with ABORTED status."""
        builds = self.get_builds_from_file('builds/build_ABORTED.dat')
        builds_dict = self.create_builds_dict(builds)

        jenkins_job = JenkinsJob(self.job_name, builds)
        self.apply_assertions(jenkins_job, builds_dict)

    def test_creation_of_jenkins_job_with_failed_build(self):
        """Test that a new Jenkins job can be created with a build with FAILURE status."""
        builds = self.get_builds_from_file('builds/build_FAILURE.dat')
        builds_dict = self.create_builds_dict(builds)

        jenkins_job = JenkinsJob(self.job_name, builds)
        self.apply_assertions(jenkins_job, builds_dict)

    def test_creation_of_jenkins_job_with_in_progress_build(self):
        """Test that a new Jenkins job can be created with a build with IN_PROGRESS status."""
        builds = self.get_builds_from_file('builds/build_IN_PROGRESS.dat')
        builds_dict = self.create_builds_dict(builds)

        jenkins_job = JenkinsJob(self.job_name, builds)
        self.apply_assertions(jenkins_job, builds_dict)

    def test_creation_of_jenkins_job_with_successful_build(self):
        """Test that a new Jenkins job can be created with a build with SUCCESS status."""
        builds = self.get_builds_from_file('builds/build_SUCCESS.dat')
        builds_dict = self.create_builds_dict(builds)

        jenkins_job = JenkinsJob(self.job_name, builds)
        self.apply_assertions(jenkins_job, builds_dict)

    def test_creation_of_jenkins_job_with_unstable_build(self):
        """Test that a new Jenkins job can be created with a build with UNSTABLE status."""
        builds = self.get_builds_from_file('builds/build_UNSTABLE.dat')
        builds_dict = self.create_builds_dict(builds)

        jenkins_job = JenkinsJob(self.job_name, builds)
        self.apply_assertions(jenkins_job, builds_dict)

    def apply_assertions(self, jenkins_job, jenkins_builds):
        self.assertIsInstance(jenkins_job, JenkinsJob,
                              'JenkinsJob object was not successfully created.')
        self.assertEqual(jenkins_job.jenkins_builds, jenkins_builds,
                         'JenkinsJob builds dict was not properly initialized.')
