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
Contains all calls to the Jenkins server.
"""
from jenkinsapi.build import Build
from jenkinsapi.jenkins import Jenkins
from typing import List

from src.utils import get_build_options


def download_builds(jenkins_obj: Jenkins, job_name: str) -> List['JenkinsBuild']:
    """
    Download build data for a Jenkins job and convert to Argus JenkinsBuild object.

    :param jenkins_obj: Object representing a connection to a Jenkins server
    :param job_name: Name of job
    :return: Sorted list of JenkinsBuild objects
    """

    builds_to_check, _ = get_build_options()

    job_instance = jenkins_obj.get_job(job_name)
    build_ids = list(job_instance.get_build_ids())[:builds_to_check]

    jenkins_builds = []  # type: List[JenkinsBuild]
    for build_id in build_ids:
        build = job_instance.get_build(build_id)
        jenkins_build = JenkinsBuild(build)
        jenkins_builds.append(jenkins_build)

    return sorted(jenkins_builds, key=lambda j: j.number, reverse=True)


class JenkinsBuild:
    def __init__(self, build: Build) -> None:
        """
        Creates a container class for a Jenkins Build object.

        Attributes:
         - timestamp: Build timestamp in UTC
         - number: Build number
         - failed: False if build was successful, True if not
         - failed_tests: List of failed test names

        :param build: A Build object from the Jenkins server
        """

        self.timestamp = build.get_timestamp().strftime('%m-%d-%Y %I:%M %p')
        self.number = build.get_number()

        self.status = build.get_status()
        if self.status == 'SUCCESS':
            self.failed = False
        else:
            self.failed = True

        self.failed_tests = []  # type: List[str]
        self.test_count = 0
        self.fail_count = 0

        if self.status != 'ABORTED' and build.has_resultset():
            self.test_count = build.get_actions()['totalCount']
            self.fail_count = build.get_actions()['failCount']

            result_set = build.get_resultset()

            for _, result in result_set.iteritems():
                test_name = result.identifier()

                if result.status == 'FAILED' or result.status == 'REGRESSION':
                    self.failed_tests.append(test_name)
