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
import sys
import time
from configparser import RawConfigParser
from typing import TYPE_CHECKING

from jenkinsapi.custom_exceptions import UnknownJob
from jenkinsapi.jenkins import Jenkins

from src.jenkins_interface import download_builds
from src.jenkins_job import JenkinsJob
from src.jenkins_view import JenkinsView
from src.utils import (ConfigError, MultiTasker, build_config_file,
                       build_jenkins_data_file, clear, decode, encode,
                       encode_password, get_build_options, jenkins_connections_dir,
                       pick_value, save_argus_config, pause)

if TYPE_CHECKING:
    from typing import Dict, List, Optional
    from src.jenkins_job import JenkinsTest


class JenkinsConnection:

    def __init__(self,
                 connection_name,   # type: str
                 url,               # type: str
                 auth=None          # type: Optional[Dict[str, str]]
                 ) -> None:
        """
        :param connection_name: Name of connection
        :param url: Url hosting Jenkins connection
        :param auth: dict containing keys, username and password
        :exception ConnectionError: on failure to connect to Jenkins instance
        """
        self.name = connection_name
        self.url = url

        # authentication
        if auth:
            self._auth = auth
            self._requires_auth = True
            username = self._auth['username']
            password = self._auth['password']
            self.jenkins_obj = self.create_jenkins_obj(self.url, username, password)
        else:
            self._auth = {}
            self._requires_auth = False
            self.jenkins_obj = self.create_jenkins_obj(self.url)

        # Map of cached job_names -> jenkins_jobs
        self.jenkins_jobs = {}  # type: Dict[str, JenkinsJob]

        # Map of cached view_names -> jenkins_views
        self.jenkins_views = {}  # type: Dict[str, JenkinsView]

    def __str__(self):
        return '{}'.format(self.name)

    def __repr__(self):
        return 'JenkinsConnection({}, {})'.format(self.name, self.url)

    def create_jenkins_obj(self, url, username=None, password=None):
        """
        Currently the sole purpose for this method is to have an easy method to
        mock when we don't want to request a real URL.
        :exception ConnectionError: on inability to reach input url
        """
        return Jenkins(url, username, password)

    @property
    def job_names(self):
        return list(self.jenkins_jobs.keys())

    @property
    def jobs(self):
        return list(self.jenkins_jobs.values())

    @property
    def view_names(self):
        return list(self.jenkins_views.keys())

    @property
    def views(self):
        return list(self.jenkins_views.values())

    def save_connection_config(self):
        if self.name and self.url:
            config_parser = RawConfigParser()
            config_parser.add_section(SECTION_TITLE)
            config_parser.set(SECTION_TITLE, 'url', self.url)

            if self._requires_auth:
                config_parser.set(SECTION_TITLE, 'username', self._auth['username'])
                password = encode(encode_password(), self._auth['password'])
                config_parser.set(SECTION_TITLE, 'password', password)

            if self.jenkins_views:
                config_parser.set(SECTION_TITLE, 'views', ','.join(self.view_names))

                for view in self.views:
                    view.save_view_config()

            save_argus_config(config_parser, build_config_file(jenkins_connections_dir, self.name))
        else:
            raise ConfigError('No data to save in JenkinsConnection config file.')

    @staticmethod
    def load_connection_config(jenkins_manager, connection_name):
        config_file = build_config_file(jenkins_connections_dir, connection_name)
        if os.path.isfile(config_file):
            config_parser = RawConfigParser()
            config_parser.read(config_file)
            url = config_parser.get(SECTION_TITLE, 'url')
            auth = {}

            if config_parser.has_option(SECTION_TITLE, 'password'):
                auth['username'] = config_parser.get(SECTION_TITLE, 'username')
                auth['password'] = decode(encode_password(), config_parser.get(SECTION_TITLE, 'password'))

            try:
                jenkins_connection = JenkinsConnection(connection_name, url, auth=auth)
                if config_parser.has_option(SECTION_TITLE, 'views'):
                    view_names = config_parser.get(SECTION_TITLE, 'views').split(',')
                    print('Loading Jenkins views for connection: {}'.format(connection_name))
                    for view_name in view_names:
                        JenkinsView.load_view_config(jenkins_connection, view_name)
                jenkins_manager.jenkins_connections[jenkins_connection.name] = jenkins_connection
            except Exception as e:
                print('WARNING! Error occurred during creation of Jenkins instance: {}.'.format(e))
                print('Skipping addition of this instance. Check routing to url: {}'.format(url))
                pause()
        else:
            'No config file for {}.'.format(connection_name)

    def download_jobs(self, view_name=None):
        print('Warning: Argus uses threading to download Jenkins data.')
        print('Please do not shutdown while jobs are downloading.')
        time.sleep(2)
        if view_name is None:
            jobs_to_download = []
            for view in self.views:
                for job_name in view.job_names:
                    jobs_to_download.append(job_name)
            print('Found {} Jenkins jobs in all views.'.format(len(jobs_to_download)))
        else:
            jobs_to_download = self.jenkins_views[view_name].job_names
            print('Found {} Jenkins jobs in {} view.'.format(len(jobs_to_download), view_name))

        updated_jobs = 0
        new_jobs = 0
        total_jobs = len(jobs_to_download)
        workers = MultiTasker()

        for job_num, job_name in enumerate(jobs_to_download, start=1):
            if job_name in self.job_names:
                if self.needs_update(job_name):
                    updated_jobs += 1
                    workers.add_job(self.download_job_worker, args=(job_name, job_num, total_jobs))
            else:
                new_jobs += 1
                workers.add_job(self.download_job_worker, args=(job_name, job_num, total_jobs))
        workers.run()
        print('Update complete. Found {} new jobs and updated {} jobs.'.format(new_jobs, updated_jobs))

    def download_job_worker(self, job_name, job_num, total_jobs):
        # type: (str, int, int) -> None
        """
        Download a single job. For use with threading.
        :param job_name: Name of the job to be downloaded
        :param job_num: The number of the current job being downloaded in the worker pool
        :param total_jobs: The total jobs being downloaded in the worker pool
        :return: None
        """
        try:
            sys.stdout.write('Downloading job {} of {}: {}\n'.format(job_num, total_jobs, job_name))
            builds = download_builds(self.jenkins_obj, job_name)
            jenkins_job = JenkinsJob(job_name, builds)
            jenkins_job_name = jenkins_job.name
            self.jenkins_jobs[jenkins_job_name] = jenkins_job
        except UnknownJob:
            sys.stdout.write('Job not found, please try again.\n')

    def needs_update(self, job_name):
        # type: (str) -> bool
        """
        :param job_name: Name of the job to be checked for updates
        :return: True if a job needs to be updated, else False
        """
        job_instance = self.jenkins_obj.get_job(job_name)
        last_build = job_instance.get_last_build_or_none()
        if last_build:
            last_build_number = last_build.get_number()
            if last_build_number != self.jenkins_jobs[job_name].last_build_number:
                return True
        return False

    def download_single_job(self, job_name):
        # type: (str) -> bool
        """
        Download a single job. Not to be used with threading.
        :param job_name: Name of the job to be downloaded
        :return: True if a job was successfully downloaded, else False
        """
        try:
            print('Downloading job: {}'.format(job_name))
            builds = download_builds(self.jenkins_obj, job_name)
            jenkins_job = JenkinsJob(job_name, builds)
            jenkins_job_name = jenkins_job.name
            self.jenkins_jobs[jenkins_job_name] = jenkins_job
            return True
        except UnknownJob:
            print('Job not found, please try again.')
            return False

    @staticmethod
    def print_job_report(job_list):
        # type: (List[JenkinsJob]) -> None
        clear()
        format_str = '{:<5}{:<60}{:<25}{:<25}{:<15}{:<30}{:<25}'
        separator = ('-' * len(format_str.format('', '', '', '', '', '', '')))
        builds_to_check, recent_builds_to_check = get_build_options()

        print(separator)
        print(format_str.format('#', 'Job Name', 'Test Result', 'Last Build Date', 'Job Health',
                                'Failed Build History ({})'.format(builds_to_check),
                                'Recent Failed Builds ({})'.format(recent_builds_to_check)))
        print(separator)
        for i, job in enumerate(job_list):
            print(format_str.format(i, job.name, job.last_build_tests, job.last_build_date,
                                    job.health, job.build_history, job.recent_history))
        print(separator)

    @staticmethod
    def sort_jobs(jobs):
        # type: (List[JenkinsJob]) -> List[JenkinsJob]
        sorted_by_name = sorted(jobs, key=lambda j: j.name.lower())
        sort_type = pick_value('Sort jobs by:', ['Name', 'Health'], allow_exit=False, sort=False)
        if sort_type == 'Health':
            # sort order: health, then recent history, then total failures, then name
            sorted_jobs = sorted(sorted(sorted_by_name,
                                        key=lambda j: (j.failed_builds, j.recent_failed_builds),
                                        reverse=True),
                                 key=lambda j: j.health)
        else:
            sorted_jobs = sorted_by_name

        return sorted_jobs

    @staticmethod
    def print_test_report(tests):
        # type: (List[JenkinsTest]) -> None
        clear()
        format_str = '{:<5}{:<130}{:<30}{:<25}'
        separator = ('-' * len(format_str.format('', '', '', '')))
        builds_to_check, recent_builds_to_check = get_build_options()

        print(separator)
        print(format_str.format(
            '#', 'Test Name',
            'Failed Test History ({})'.format(builds_to_check),
            'Recent Failed Tests ({})'.format(recent_builds_to_check)))
        print(separator)

        for i, jenkins_test in enumerate(tests):
            print(format_str.format(i, jenkins_test.name, jenkins_test.failure_history,
                                    jenkins_test.recent_history))
        print(separator)

    @staticmethod
    def sort_tests(tests):
        sorted_by_name = sorted(tests, key=lambda t: t.name.lower())
        sort_type = pick_value('Sort tests by:', ['Name', 'Health'], allow_exit=False, sort=False)
        if sort_type == 'Health':
            # sort order: recent history, then total failures, then name
            sorted_tests = sorted(sorted_by_name,
                                  key=lambda t: (t.failure_history, t.recent_history),
                                  reverse=True)
        else:
            sorted_tests = sorted_by_name

        return sorted_tests

    def save_job_data(self):
        with open(build_jenkins_data_file(self.name), 'wb') as data_file:
            for job in self.jobs:
                job.serialize(data_file)
        print('Saved local cache of {} jobs for [{}]'.format(len(self.jobs), self.name))

    def get_list_of_views(self, nested_view=None):
        if nested_view is None:
            return list(self.jenkins_obj.views.keys())
        else:
            return list(self.jenkins_obj.views[nested_view].views.keys())

    def get_view(self, view_name):
        split_view_name = view_name.split('-')
        if split_view_name[0] == 'Dev':
            view_obj = self.jenkins_obj.views['Dev'].views[split_view_name[1]]
        else:
            view_obj = self.jenkins_obj.views[view_name]
        job_names = list(view_obj.keys())
        return JenkinsView(view_name, job_names)


SECTION_TITLE = JenkinsConnection.__name__
