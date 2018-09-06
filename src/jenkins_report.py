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

from typing import TYPE_CHECKING, Dict, List

from src.jenkins_job import JenkinsJob
from src.utils import (clear, get_build_options, jenkins_reports_dir,
                       save_argus_config)

if TYPE_CHECKING:
    from src.jenkins_manager import JenkinsManager


class JenkinsReport:

    def __init__(self, report_name):
        self.name = report_name
        self.connection_dict = {}  # dict of {connection_name: job_name_list}
        self._parser_path = jenkins_reports_dir + '/{}.cfg'.format(self.name)

    @property
    def connection_names(self) -> List[str]:
        return list(self.connection_dict.keys())

    @property
    def job_names(self) -> List[str]:
        return [job_name for job_list in list(self.connection_dict.values()) for job_name in job_list]

    @property
    def job_dict(self) -> Dict[JenkinsJob, str]:
        job_dict = {}
        for connection_name, job_name_list in self.connection_dict.items():
            for job_name in job_name_list:
                job_dict.update({job_name: connection_name})
        return job_dict

    def __str__(self) -> str:
        return '{}'.format(self.name)

    def __repr__(self) -> str:
        return 'JenkinsReport({})'.format(self.name)

    def save_report_config(self) -> None:
        config_parser = RawConfigParser()
        config_parser.add_section(SECTION_TITLE)

        if self.connection_names:
            config_parser.set(SECTION_TITLE, 'connection_names', ','.join(self.connection_names))
            for connection_name in self.connection_names:
                config_parser.add_section(connection_name)
                config_parser.set(connection_name, 'job_names', ','.join(self.connection_dict[connection_name]))

        save_argus_config(config_parser, self._parser_path)

    @staticmethod
    def load_report_config(jenkins_manager: 'JenkinsManager', report_name: str) -> None:
        jenkins_report = JenkinsReport(report_name)
        config_parser = RawConfigParser()
        if os.path.isfile(jenkins_report._parser_path):
            config_parser.read(jenkins_report._parser_path)

            if config_parser.has_option(SECTION_TITLE, 'connection_names'):
                connection_names = config_parser.get(SECTION_TITLE, 'connection_names').split(',')
                for connection_name in connection_names:
                    job_names = config_parser.get(connection_name, 'job_names').split(',')
                    jenkins_report.connection_dict[connection_name] = job_names

            jenkins_manager.jenkins_reports[jenkins_report.name] = jenkins_report
        else:
            print('No config file for {}.'.format(report_name))

    def add_job_to_report(self, job_name: str, connection_name: str) -> None:
        if connection_name in self.connection_names:
            self.connection_dict[connection_name].append(job_name)
        else:
            self.connection_dict[connection_name] = [job_name]

    def remove_job_from_report(self, job_name: str, connection_name: str) -> None:
        """
        Remove a job from a report.

        :param job_name: The name of the job to be removed
        :param connection_name: The name of the connection that the job belongs to
        :return: None
        """
        self.connection_dict[connection_name].remove(job_name)

    def get_job_list(self, jenkins_manager: 'JenkinsManager') -> List[JenkinsJob]:
        job_list = []
        for job, connection_name in self.job_dict.items():
            connection = jenkins_manager.get_connection(connection_name)
            job = connection.jenkins_jobs[job.name]
            job_list.append(job)
        return job_list

    def print_report(self, job_list: List[JenkinsJob]) -> None:
        clear()
        format_str = '{:<5}{:<60}{:<30}{:<25}{:<25}{:<15}{:<30}{:<25}'
        separator = ('-' * len(format_str.format('', '', '', '', '', '', '', '')))
        builds_to_check, recent_builds_to_check = get_build_options()

        print(separator)
        print(format_str.format('#', 'Job Name', 'Connection', 'Test Result', 'Last Build Date', 'Job Health',
                                'Failed Build History ({})'.format(builds_to_check),
                                'Recent Failed Builds ({})'.format(recent_builds_to_check)))
        print(separator)
        for i, job in enumerate(job_list, start=1):
            print(format_str.format(i, job.name, self.job_dict[job], job.last_build_tests,
                                    job.last_build_date, job.health, job.build_history,
                                    job.recent_history))
        print(separator)


SECTION_TITLE = JenkinsReport.__name__
