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
import traceback
from configparser import RawConfigParser
from getpass import getpass

from requests.exceptions import ConnectionError, HTTPError, MissingSchema
from typing import TYPE_CHECKING, Optional

from src.jenkins_connection import JenkinsConnection
from src.jenkins_job import JenkinsJob
from src.jenkins_report import JenkinsReport
from src.utils import (Config, ConfigError, display_results, get_connection_name, get_input, is_yes,
                       jenkins_conf_file, jenkins_data_dir, jenkins_views_dir,
                       pause, pick_value, save_argus_config)

if TYPE_CHECKING:
    from typing import Dict, List


class JenkinsManager:

    """
    Helper class to build Jenkins test reports
    """

    def __init__(self, main_menu):
        self._jenkins_branches = Config.JENKINS_BRANCHES
        self._builds_to_check = 50
        self._max_results = 20
        self._main_menu = main_menu

        # Map of connection_names -> jenkins_connections
        self.jenkins_connections = {}  # type: Dict[str, JenkinsConnection]

        # Map of report_names -> jenkins_reports
        self.jenkins_reports = {}  # type: Dict[str, JenkinsReport]

        # Currently active Jenkins connection
        self.active_connection = None  # type: JenkinsConnection

        # Currently active Jenkins report
        self.active_report = None  # type: JenkinsReport

        self.load_jenkins_config()

    @property
    def connection_names(self):
        return list(self.jenkins_connections.keys())

    @property
    def connections(self):
        return list(self.jenkins_connections.values())

    @property
    def report_names(self):
        return list(self.jenkins_reports.keys())

    @property
    def reports(self):
        return list(self.jenkins_reports.values())

    def load_jenkins_config(self):
        if os.path.exists(jenkins_conf_file):
            config_parser = RawConfigParser()
            config_parser.read(jenkins_conf_file)

            if config_parser.has_section(SECTION_TITLE):
                connection_names = config_parser.get(SECTION_TITLE, 'connections').split(',')

                # Load cached Jenkins connection configs from conf_dir & create empty Jenkins connections
                for connection_name in connection_names:
                    JenkinsConnection.load_connection_config(self, connection_name)

                # Load cached job data from jenkins_data_dir
                for file_name in os.listdir(jenkins_data_dir):
                    data_file = os.path.join(jenkins_data_dir, file_name)
                    print('Loading locally cached Jenkins job data from file: {}'.format(data_file))
                    jenkins_connection = self.load_job_data(data_file)
                    if jenkins_connection is not None:
                        self.jenkins_connections[jenkins_connection.name] = jenkins_connection

                if config_parser.has_option(SECTION_TITLE, 'reports'):
                    report_names = config_parser.get(SECTION_TITLE, 'reports').split(',')
                    for report_name in report_names:
                        JenkinsReport.load_report_config(self, report_name)

    def save_jenkins_config(self):
        config_parser = RawConfigParser()

        if os.path.exists(jenkins_conf_file):
            config_parser.read(jenkins_conf_file)

        if not config_parser.has_section(SECTION_TITLE):
            config_parser.add_section(SECTION_TITLE)

        config_parser.set(SECTION_TITLE, 'connections', ','.join(self.connection_names))

        if self.jenkins_reports:
            config_parser.set(SECTION_TITLE, 'reports', ','.join(self.report_names))

        for connection in self.connections:
            connection.save_connection_config()

        for report in self.reports:
            report.save_report_config()

        save_argus_config(config_parser, jenkins_conf_file)

    def load_job_data(self, file_name):
        try:
            with open(file_name, 'rb') as data_file:
                connection_name = get_connection_name(data_file.name)
                jenkins_connection = self.get_connection(connection_name)

                while True:
                    try:
                        jenkins_job = JenkinsJob.deserialize(data_file)
                        jenkins_connection.jenkins_jobs.update({jenkins_job.name: jenkins_job})
                    except EOFError:
                        break

        except ConfigError:
            print('Failed to load cached data for connection from config file: {}'.format(file_name))
            traceback.print_exc()
            return None

        print('Loaded connection [{}] with {} jobs cached.'.format(jenkins_connection.name, len(jenkins_connection.jenkins_jobs)))
        return jenkins_connection

    def select_active_connection(self):
        if self.jenkins_connections:
            connection_name = pick_value('Which Jenkins connection would you like to open?', self.connection_names)
            if connection_name:
                self.active_connection = self.get_connection(connection_name)
                self._main_menu.go_to_jenkins_connection_menu()
        else:
            if is_yes('No Jenkins connections. Would you like to add one now?'):
                self.add_connection()
                self.active_connection = self.get_connection(self.connection_names[0])
                self._main_menu.go_to_jenkins_connection_menu()

    def select_active_report(self):
        if self.jenkins_reports:
            report_name = pick_value('Which custom report would you like to open?', self.report_names)
            if report_name:
                self.active_report = self.get_custom_report(report_name)
                self._main_menu.go_to_jenkins_report_menu()
        else:
            if is_yes('No custom reports. Would you like to add one now?'):
                self.add_custom_report()
                self.active_report = self.get_custom_report(self.report_names[0])
                self._main_menu.go_to_jenkins_report_menu()

    def add_custom_report(self):
        report_name = get_input('Enter a name for this custom report, or enter nothing to exit.\n>', lowered=False)
        if report_name:
            report = JenkinsReport(report_name)
            report.save_report_config()
            self.jenkins_reports[report_name] = report
            self.save_jenkins_config()
            print('Successfully added custom report: {}'.format(report_name))
            pause()
            self.active_report = self.get_custom_report(report_name)
            self._main_menu.go_to_jenkins_report_menu()

    def remove_custom_report(self):
        report_name = pick_value('Which custom report would you like to remove?', list(self.jenkins_reports.keys()))
        if report_name:
            self.jenkins_reports.pop(report_name)
            self.save_jenkins_config()
            print('Successfully removed custom report: {}'.format(report_name))
            pause()

    def add_custom_report_job(self):
        if self.connection_names:
            connection_name = pick_value('Which Jenkins Connection would you like to add jobs from?', self.connection_names)
            if connection_name:
                connection = self.jenkins_connections[connection_name]
                if connection_name in self.active_report.connection_names:
                    job_options = [job_name for job_name in connection.job_names if job_name not in self.active_report.connection_dict[connection_name]]
                else:
                    job_options = connection.job_names

                while True:
                    job_name = pick_value('Which Jenkins job would you like to add?', job_options)
                    if job_name:
                        self.active_report.add_job_to_report(job_name, connection_name)
                        self.active_report.save_report_config()
                        print('Successfully added job: {}'.format(job_name))
                        job_options.remove(job_name)
                    else:
                        break
        else:
            if is_yes('No Jenkins connections to add jobs from. Would you like to add one now?'):
                self.active_connection = self.add_connection()
                self._main_menu.go_to_jenkins_connection_menu()

    def remove_custom_report_job(self):
        if self.active_report.job_names:
            job_options = self.active_report.job_names

            while True:
                job_name = pick_value('Which Jenkins job would you like to remove?', job_options)
                if job_name:
                    for connection_name, job_name_list in self.active_report.connection_dict.iteritems():
                        if job_name in job_name_list:
                            self.active_report.remove_job_from_report(job_name, connection_name)
                    for connection_name in self.active_report.connection_names:
                        if not self.active_report.connection_dict[connection_name]:
                            self.active_report.connection_dict.pop(connection_name)
                    self.active_report.save_report_config()
                    print('Successfully removed job: {}'.format(job_name))
                    job_options.remove(job_name)
                else:
                    break
        else:
            print('No Jenkins jobs to remove from report.')
            pause()

    def list_custom_reports(self):
        if self.jenkins_reports:
            display_results(self.report_names)
        else:
            print('No Jenkins reports to display.')

    def view_custom_report(self):
        if self.active_report.job_names:
            job_list = self.active_report.get_job_list(self)
            self.print_job_options(job_list)
        else:
            if is_yes('Attempted to run report with no jobs. Would you like to add jobs now?'):
                self.add_custom_report_job()

    def get_custom_report(self, report_name):
        if report_name not in list(self.jenkins_reports.keys()):
            raise ConfigError('Failed to get custom report: {}'.format(report_name))
        return self.jenkins_reports[report_name]

    def add_connection(self) -> Optional[JenkinsConnection]:
        print('Enter a name for this connection, or enter nothing to exit.')
        connection_name = get_input('>', lowered=False)
        if connection_name:
            print('Enter a Jenkins base url.')
            print('Example: http://cassci.datastax.com/')
            url = get_input('>')

            auth = {}
            is_auth = is_yes('Does this connection require authentication?')
            if is_auth:
                auth['username'] = get_input('Please enter connection username\n', lowered=False)
                print('Please enter connection password')
                auth['password'] = getpass()

            try:
                jenkins_connection = JenkinsConnection(connection_name, url, auth)
                self.jenkins_connections[jenkins_connection.name] = jenkins_connection
                self.save_jenkins_config()
                print('Successfully added connection: {}'.format(connection_name))
                pause()
                return jenkins_connection
            except (HTTPError, MissingSchema, ConnectionError) as e:
                print('Error occurred adding new connection: {}'.format(e))
                print('Invalid Jenkins URL. Please try again.')
                pause()
        return None

    def remove_connection(self):
        if self.jenkins_connections:
            connection_name = pick_value('Which Jenkins connection would you like to remove?', self.connection_names)
            if connection_name:
                print('About to remove: {}'.format(connection_name))
                if is_yes('Are you sure?'):
                    self.jenkins_connections.pop(connection_name)
                    self.save_jenkins_config()
                    print('Successfully removed connection: {}'.format(connection_name))
                    pause()
                else:
                    print('Remove aborted.')
                    pause()
        else:
            print('No Jenkins connections to remove.')
            pause()

    def get_connection(self, connection_name):
        if connection_name not in self.connection_names:
            raise ConfigError('Failed to get connection: {}'.format(connection_name))
        return self.jenkins_connections[connection_name]

    def load_connection_from_file(self, file_name):
        try:
            with open(file_name, 'r') as data_file:
                connection_name = data_file.readline().rstrip()
                jenkins_connection = self.get_connection(connection_name)

                while True:
                    try:
                        jenkins_job = JenkinsJob.deserialize(data_file)
                        jenkins_connection.jenkins_jobs.update({jenkins_job.name: jenkins_job})
                    except EOFError:
                        break

        except ConfigError as ce:
            print('Failed to load cached data for connection from config file: {}'.format(file_name))
            print('Error: {}'.format(ce))
            return None

        print('Loaded connection [{}] with {} jobs cached.'.format(jenkins_connection.name, len(jenkins_connection.jenkins_jobs)))
        return jenkins_connection

    def list_connections(self):
        if self.jenkins_connections:
            display_results(self.connection_names)
        else:
            print('No Jenkins connections to display.')

    def download_jobs(self):
        download_method = pick_value('Would you like to download jobs by view or individually?',
                                     ['By View', 'Individually'], sort=False)
        if download_method:
            if download_method == 'By View':
                if self.active_connection.jenkins_views:
                    view_options = self.active_connection.view_names
                    all_views = '* All Views'
                    view_options.append(all_views)
                    view_name = pick_value('Which saved view would you like to download jobs for?', view_options)
                    if view_name:
                        if view_name == all_views:
                            self.active_connection.download_jobs()
                            self.active_connection.save_job_data()
                            print('Successfully downloaded jobs for all views.')
                            pause()
                        else:
                            self.active_connection.download_jobs(view_name)
                            self.active_connection.save_job_data()
                            print('Successfully downloaded jobs for view: {}'.format(view_name))
                            pause()
                else:
                    if is_yes('No Jenkins views. Would you like to add one now?'):
                        self.add_view()
                        view_name = self.active_connection.view_names[0]
                        if is_yes('Download jobs for this view?'):
                            self.active_connection.download_jobs(view_name)
                            self.active_connection.save_job_data()
                            print('Successfully downloaded jobs for view: {}'.format(view_name))
                            pause()

            elif download_method == 'Individually':
                job_name = get_input('Enter the exact, case-sensitive name of the job, or enter nothing to exit.\n>', lowered=False)
                if job_name:
                    if self.active_connection.download_single_job(job_name):
                        self.active_connection.save_job_data()
                        print('Successfully downloaded Jenkins job: {}'.format(job_name))
                        pause()
                    else:
                        print('Failed to download Jenkins job: {}'.format(job_name))
                        pause()

    def view_cached_jobs(self):
        if self.active_connection.job_names:
            view_options = sorted(self.active_connection.view_names)
            all_jobs = '* All Jobs'
            view_options.append(all_jobs)
            view_name = pick_value('Which jobs would you like to view?', view_options)
            if view_name:
                if view_name == all_jobs:
                    self.print_job_options(self.active_connection.jobs, connection=True)
                else:
                    jobs_to_print = []
                    job_names = self.active_connection.jenkins_views[view_name].job_names
                    if job_names:
                        for job_name in job_names:
                            jobs_to_print.append(self.active_connection.jenkins_jobs[job_name])
                        self.print_job_options(jobs_to_print, connection=True)
                    else:
                        print('No jobs to print in this view.')
        else:
            if is_yes('There are no cached jobs for the current connection. Would you like to download jobs now?'):
                self.download_jobs()

    def view_num_jobs(self):
        """
        Displays the number of jobs cached locally and the total number of jobs on the server.
        """
        print('Jobs cached: {}'.format(len(self.active_connection.job_names)))
        print('Jobs on server: {}'.format(len(self.active_connection.jenkins_obj.get_jobs_list())))
        pause()

    def print_job_options(self, jobs, connection=False):
        # type: (List[JenkinsJob], bool) -> None
        # this is a terrible way of doing this
        # todo: get rid of connection bool and figure out a better way to do this
        sorted_jobs = JenkinsConnection.sort_jobs(jobs)
        if connection:
            self.active_connection.print_job_report(sorted_jobs)
        else:
            self.active_report.print_report(sorted_jobs)

        while True:
            print('Options:')
            print('Enter [#] to print test report for that job.')
            print('Enter [p] to re-print job report.')
            print('Enter [q] to exit.')
            selection = get_input('>')
            if selection.isdigit() and int(selection) in range(len(sorted_jobs)):
                jenkins_job = sorted_jobs[int(selection)]
                tests = jenkins_job.jenkins_tests
                self.print_test_options(tests)
                if connection:
                    self.active_connection.print_job_report(sorted_jobs)
                else:
                    self.active_report.print_report(sorted_jobs)
            elif selection == 'q':
                break
            elif selection == 'p':
                sorted_jobs = JenkinsConnection.sort_jobs(jobs)
                if connection:
                    JenkinsConnection.print_job_report(sorted_jobs)
                else:
                    self.active_report.print_report(sorted_jobs)
            else:
                print('Invalid selection, please try again.')

    @staticmethod
    def print_test_options(tests):
        sorted_tests = JenkinsConnection.sort_tests(tests)
        JenkinsConnection.print_test_report(sorted_tests)

        while True:
            print('Options:')
            print('Enter [p] to re-print test report.')
            print('Enter [q] to exit.')
            selection = get_input('>')
            if selection == 'q':
                break
            elif selection == 'p':
                sorted_tests = JenkinsConnection.sort_tests(tests)
                JenkinsConnection.print_test_report(sorted_tests)
            else:
                print('Invalid selection, please try again.')

    def add_view(self):
        view_name = pick_value('Which Jenkins view would you like to save?', self.active_connection.get_list_of_views())
        if view_name:
            if view_name == 'Dev':
                dev_view_name = pick_value('Which Jenkins dev view would you like to save?', self.active_connection.get_list_of_views(view_name))
                if dev_view_name:
                    dev_view_name = 'Dev-{}'.format(dev_view_name)
                    self.active_connection.jenkins_views[dev_view_name] = self.active_connection.get_view(dev_view_name)
                    self.active_connection.save_connection_config()
                    view_name = dev_view_name
            else:
                self.active_connection.jenkins_views[view_name] = self.active_connection.get_view(view_name)
                self.active_connection.save_connection_config()
            print('Successfully added view: {}'.format(view_name))
            pause()

            if is_yes('Would you like to download jobs for this view now?'):
                self.active_connection.download_jobs(view_name)
                self.active_connection.save_job_data()
                print('Successfully downloaded jobs for view: {}'.format(view_name))
                pause()

    def remove_view(self):
        if self.active_connection.jenkins_views:
            view_name = pick_value('Which Jenkins view would you like to remove?', self.active_connection.view_names)

            if view_name:
                print('About to delete: {}'.format(view_name))
                if is_yes('Are you sure?'):
                    del self.active_connection.jenkins_views[view_name]
                    self.active_connection.save_connection_config()
                    file_name = os.path.join(jenkins_views_dir, "{}.cfg".format(view_name))
                    if os.path.exists(file_name):
                        os.remove(file_name)
                        print('{} view deleted.'.format(view_name))
                    else:
                        print('Attempted to remove view {}'.format(view_name))
                        print('View path {} does not exist'.format(file_name))
                else:
                    print('Remove aborted.')
                pause()
        else:
            print('No Jenkins views to remove.')

    def list_views(self):
        if self.active_connection.jenkins_views:
            display_results(self.active_connection.view_names)
        else:
            print('No Jenkins views to display.')


SECTION_TITLE = JenkinsManager.__name__
