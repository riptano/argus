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
Contains the JenkinsJob and JenkinsTest classes.

This module does not interact with the Jenkins server at all. All data needs to be collected
from the server prior to creating a new JenkinsJob object.
"""
import pickle
from typing import Dict, List, Tuple, TYPE_CHECKING

from src.jenkins_interface import JenkinsBuild
from src.utils import get_build_options


class JenkinsJob:
    """Represents a single Jenkins job with recent build and test failure data."""

    def __init__(self, name: str, jenkins_builds: List[JenkinsBuild]) -> None:
        """
        Create a Jenkins job object from data pulled from a Jenkins job_instance.

        :param name: The name of the job
        :param jenkins_builds: List of builds for the job
        """
        self.name = name

        # Build jenkins_builds dict
        self.jenkins_builds = {}  # type: Dict[int, JenkinsBuild]
        for jenkins_build in jenkins_builds:
            self.jenkins_builds.update({jenkins_build.number: jenkins_build})

        if jenkins_builds:
            # Get last build info
            last_build = jenkins_builds[0]
            self.last_build_date = last_build.timestamp
            self.last_build_number = last_build.number
            self.last_build_fail_count = last_build.fail_count
            self.last_build_test_count = last_build.test_count

            # Determine the number of builds checked
            self.builds_checked = len(jenkins_builds)

            # Determine the number of recent builds checked
            _, recent_builds_to_check = get_build_options()
            if recent_builds_to_check < self.builds_checked:
                self.recent_builds_checked = recent_builds_to_check
            else:
                self.recent_builds_checked = self.builds_checked

            recent_jenkins_builds = jenkins_builds[:recent_builds_to_check]

            # Get number of builds and tests that failed
            self.failed_builds, self.failed_tests = self._get_build_failures(jenkins_builds)
            self.recent_failed_builds, self.recent_failed_tests = self._get_build_failures(recent_jenkins_builds)

        else:
            self.last_build_date = 'N/A'
            self.last_build_number = None
            self.last_build_fail_count = 0
            self.last_build_test_count = 0

            self.builds_checked = 0
            self.failed_builds = 0

            self.recent_builds_checked = 0
            self.recent_failed_builds = 0

            self.failed_tests = {}
            self.recent_failed_tests = {}

        self.last_build_tests = '{} of {}'.format(self.last_build_fail_count, self.last_build_test_count)

        self.build_history = '{} of last {}'.format(self.failed_builds, self.builds_checked)
        self.recent_history = '{} of last {}'.format(self.recent_failed_builds,
                                                     self.recent_builds_checked)

        self.health = self._get_job_health(self.recent_failed_builds, self.recent_builds_checked)

        # set test history
        self.jenkins_tests = []  # type: List[JenkinsTest]
        for test_name in self.failed_tests.keys():
            num_failures = self.failed_tests[test_name]

            if test_name in self.recent_failed_tests.keys():
                num_recent_failures = self.recent_failed_tests[test_name]
            else:
                num_recent_failures = 0

            self.jenkins_tests.append(
                JenkinsTest(test_name, num_failures, self.builds_checked,
                            num_recent_failures, self.recent_builds_checked))

    @staticmethod
    def _get_build_failures(jenkins_builds: List[JenkinsBuild]) -> Tuple[int, Dict[str, int]]:
        """
        Loop through a list of Jenkins builds to determine the number of build and test failures.

        :param jenkins_builds: List of Jenkins builds
        :return: (Number of failed builds, Dict of failed tests and number of failures)
        """
        failed_builds = 0
        failed_tests = {}  # type: Dict[str, int]

        for jenkins_build in jenkins_builds:
            if jenkins_build.failed:
                failed_builds += 1

            for test_name in jenkins_build.failed_tests:
                if test_name not in failed_tests:
                    failed_tests.update({test_name: 0})
                failed_tests[test_name] += 1

        return failed_builds, failed_tests

    @staticmethod
    def _get_job_health(failed_builds: int, builds_checked: int) -> str:
        """
        Determine the health of a job based on the number of recently failed builds.

        :param failed_builds: Number of recently failed builds
        :param builds_checked: Number of recent builds checked.
        :return: The health of the job. Can be good, fair, or bad.
        """
        if builds_checked == 0:                         # No builds were checked    -> N/A
            health = 'N/A'
        elif failed_builds == 0:                        # All builds passed         -> GOOD
            health = 'GOOD'
        elif failed_builds / builds_checked <= 0.5:     # Half or fewer failed      -> FAIR
            health = 'FAIR'
        else:                                           # More than half failed     -> BAD
            health = 'BAD'

        return health

    def serialize(self, file_handle):
        """
        Save a serialized Jenkins job to a file.

        :param file_handle: The file to save the serialized Jenkins job
        :return: None
        """
        pickle.dump(self, file_handle, protocol=pickle.HIGHEST_PROTOCOL)

    @staticmethod
    def deserialize(file_handle):
        """
        Load a serialized Jenkins job from a file.

        :param file_handle: The file containing the serialized Jenkins job
        :return: The deserialized Jenkins job
        """
        return pickle.load(file_handle)

    def __eq__(self, other):
        """Used to compare two JenkinsJob objects."""
        return self.__dict__ == other.__dict__


class JenkinsTest:
    """Container class for a Jenkins test and its failure history."""

    def __init__(self, name: str, num_failures: int, builds_checked: int, num_recent_failures: int, recent_builds_checked: int) -> None:
        """
        Create a JenkinsTest instance.

        :param name: Name of the test
        :param num_failures: Number of times this test failed in all builds checked
        :param builds_checked: Total number of builds checked
        :param num_recent_failures: Number of times this test failed in recent builds
        :param recent_builds_checked: Number of recent builds checked
        """
        self.name = name
        self.failure_history = '{} of last {}'.format(num_failures, builds_checked)
        self.recent_history = '{} of last {}'.format(num_recent_failures, recent_builds_checked)
