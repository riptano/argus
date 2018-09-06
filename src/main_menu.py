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

import configparser
import os
import sys
from getpass import getpass
from typing import Dict, List

from src import __version__, utils
from src.jira_manager import JiraManager
from src.jenkins_manager import JenkinsManager
from src.menu_option import MenuOption
from src.team_manager import TeamManager
from src.triage_update import TriageUpdate
from src.utils import (Config, argus_conf_file,
                       argus_debug, change_browser, clear, conf_dir, get_input,
                       pause, save_argus_config, thick_separator,
                       thin_separator)


class MainMenu:
    def __init__(self, jira_manager: JiraManager, team_manager: TeamManager, options: Dict[str, str]) -> None:
        self.jira_manager = jira_manager
        self.team_manager = team_manager

        # TODO: Clean up the coupling with main_menu.
        self.jenkins_manager = JenkinsManager(self)

        if 'triage_csv' in options:
            jira_connections = {}
            for jira_connection in self.jira_manager.jira_connections():
                argus_debug('Init connection: {}'.format(jira_connection.connection_name))
                jira_connections[jira_connection.connection_name] = jira_connection
            triage_update = TriageUpdate(jira_connections, self.jira_manager.get_all_cached_jira_projects())
            triage_out = options['triage_out'] if 'triage_out' in options else None
            triage_update.process(options['triage_csv'], triage_out)

        if 'dashboard' in options:
            user_key = options['dashboard']
            dash_keys = list(self.jira_manager.jira_dashboards.keys())

            if user_key in dash_keys:
                self.jira_manager.jira_dashboards[user_key].display_dashboard(self.jira_manager, self.jira_manager.jira_views)
            else:
                print('Oops... Error with dashboard name {}'.format(user_key))
                print('Possible dashboard names : {}'.format(','.join(dash_keys)))
                print('Starting Argus normally...')

        if 'verbose' in options:
            utils.debug = True
            utils.argus_log = open('argus.log', 'w')

        self.main_menu = [
            MenuOption('d', 'Dashboards', self.go_to_dashboards_menu, pause=False),
            MenuOption('v', 'Jira Views', self.go_to_jira_views_menu, pause=False),
            MenuOption('p', 'JiraProject Queries', self.go_to_projects_menu, pause=False),
            MenuOption.print_blank_line(),
            MenuOption('t', 'Run a Team-Based Report', self._run_team_report, pause=False),
            MenuOption('u', 'Run an org-based Report', self._run_org_report, pause=False),
            MenuOption('e', 'View Escalations', self.jira_manager.display_escalations, pause=False),
            MenuOption.print_blank_line(),
            MenuOption('r', 'Generate a Pre-Determined Report', self.go_to_reports_menu, pause=False),
            MenuOption('m', 'Team Management', self.go_to_teams_menu, pause=False),
            MenuOption('c', 'Jira Connections', self.go_to_jira_connections_menu, pause=False),
            MenuOption.print_blank_line(),
            MenuOption('j', 'Jenkins Menu', self.go_to_jenkins_menu, pause=False),
            MenuOption.print_blank_line(),
            MenuOption('o', 'Change Options', self.go_to_options_menu, pause=False),
            MenuOption('x', 'Debug', self.jira_manager.run_debug, pause=False),
            MenuOption.print_blank_line(),
            MenuOption('h', 'Help', self._display_readme, pause=False),
            MenuOption.quit_program()
        ]

        self.dashboards_menu = [
            MenuOption('l', 'List all available dashboards', self.jira_manager.list_dashboards),
            MenuOption('d', 'Display a dashboard\'s results', self.jira_manager.display_dashboard),
            MenuOption('c', 'Create a dashboard', self.jira_manager.add_dashboard),
            MenuOption('e', 'Edit a dashboard', self.jira_manager.edit_dashboard),
            MenuOption('r', 'Remove a dashboard', self.jira_manager.remove_dashboard),
            MenuOption.print_blank_line(),
            MenuOption.return_to_previous_menu(self.go_to_main_menu)
        ]

        self.jira_views_menu = [
            MenuOption('l', 'List all defined JiraViews', self.jira_manager.list_all_jira_views),
            MenuOption('d', 'Display a JiraView\'s results', self.jira_manager.display_view),
            MenuOption('a', 'Add a JiraView', self._add_view),
            MenuOption('e', 'Edit a JiraView', self._edit_view),
            MenuOption('r', 'Remove a JiraView', self.jira_manager.remove_view),
            MenuOption.print_blank_line(),
            MenuOption.return_to_previous_menu(self.go_to_main_menu)
        ]

        self.reports_menu = [
            MenuOption('f', 'FixVersion report (release). Query all tickets with a specified FixVersion', self.jira_manager.report_fix_version),
            MenuOption('s', 'Add a single-user multi-JIRA open ticket dashboard', self._add_multi_jira_dashboard),
            MenuOption('l', 'Add a label-based cross-cutting view', self.jira_manager.add_label_view),
            MenuOption.print_blank_line(),
            MenuOption.return_to_previous_menu(self.go_to_main_menu)
        ]

        self.team_menu = [
            MenuOption('l', 'List all defined Teams', self.team_manager.list_teams),
            MenuOption('a', 'Add a new team', self._add_team),
            MenuOption('e', 'Edit an existing team', self._edit_team),
            MenuOption('r', 'Remove a team', self.team_manager.remove_team),
            MenuOption('x', 'Link a team member to two accounts across JiraConnections', self.add_linked_member),
            MenuOption('d', 'Delete a cross-Jira link', self.team_manager.remove_linked_member),
            MenuOption('o', 'Add an organization', self.team_manager.add_organization),
            MenuOption('p', 'Remove an organization', self.team_manager.remove_organization),
            MenuOption.print_blank_line(),
            MenuOption.return_to_previous_menu(self.go_to_main_menu)
        ]

        self.jira_connections_menu = [
            MenuOption('a', 'Add a JIRA connection', self.jira_manager.add_connection),
            MenuOption('r', 'Remove a JIRA connection and all related views', self.jira_manager.remove_connection),
            MenuOption('c', 'Cache offline ticket data for a JiraProject on a connection', self.jira_manager.cache_new_jira_project_data),
            MenuOption('d', 'Delete offline cached ticket data for a JiraProject on a connection', self.jira_manager.delete_cached_jira_project),
            MenuOption('l', 'List all configured Jiraconnections', self.jira_manager.list_jira_connections),
            MenuOption.print_blank_line(),
            MenuOption.return_to_previous_menu(self.go_to_main_menu)
        ]

        self.jenkins_menu = [
            MenuOption('r', 'Reports Manager', self.go_to_jenkins_reports_manager_menu, pause=False),
            MenuOption('c', 'Connections Manager', self.go_to_jenkins_connections_manager_menu, pause=False),
            MenuOption.print_blank_line(),
            MenuOption.return_to_previous_menu(self.go_to_main_menu)
        ]

        self.jenkins_reports_manager_menu = [
            MenuOption('o', 'Open custom report', self.jenkins_manager.select_active_report, pause=False),
            MenuOption('a', 'Add a custom report', self.jenkins_manager.add_custom_report, pause=False),
            MenuOption('r', 'Remove a custom report', self.jenkins_manager.remove_custom_report, pause=False),
            MenuOption('l', 'List custom reports', self.jenkins_manager.list_custom_reports),
            MenuOption.print_blank_line(),
            MenuOption.return_to_previous_menu(self.go_to_jenkins_menu)
        ]

        self.jenkins_report_menu = [
            MenuOption('v', 'View report', self.jenkins_manager.view_custom_report),
            MenuOption('a', 'Add a job', self.jenkins_manager.add_custom_report_job, pause=False),
            MenuOption('r', 'Remove a job', self.jenkins_manager.remove_custom_report_job, pause=False),
            MenuOption.print_blank_line(),
            MenuOption.return_to_previous_menu(self.go_to_jenkins_reports_manager_menu)
        ]

        self.jenkins_connections_manager_menu = [
            MenuOption('o', 'Open connection', self.jenkins_manager.select_active_connection, pause=False),
            MenuOption('a', 'Add a connection', self.jenkins_manager.add_connection, pause=False),
            MenuOption('r', 'Remove a connection', self.jenkins_manager.remove_connection, pause=False),
            MenuOption('l', 'List connections', self.jenkins_manager.list_connections),
            MenuOption.print_blank_line(),
            MenuOption.return_to_previous_menu(self.go_to_jenkins_menu)
        ]

        self.jenkins_connection_menu = [
            MenuOption('v', 'View cached jobs', self.jenkins_manager.view_cached_jobs, pause=False),
            MenuOption('d', 'Download jobs to cache', self.jenkins_manager.download_jobs, pause=False),
            MenuOption.print_blank_line(),
            MenuOption('l', 'List saved views', self.jenkins_manager.list_views),
            MenuOption('a', 'Add a view', self.jenkins_manager.add_view, pause=False),
            MenuOption('r', 'Remove a view', self.jenkins_manager.remove_view, pause=False),
            MenuOption.print_blank_line(),
            MenuOption.return_to_previous_menu(self.go_to_jenkins_connections_manager_menu)
        ]

        self.options_menu = [
            MenuOption('p', 'Change Argus password', self._change_password),
            MenuOption('b', 'Change browser', self._change_browser),
            MenuOption('v', 'Toggle Verbose/Debug', self._change_debug),
            MenuOption('d', 'Toggle Display dependencies', self._change_show_dependencies),
            MenuOption('o', 'Toggle show open dependencies only', self._change_dependency_type),
            MenuOption.print_blank_line(),
            MenuOption.return_to_previous_menu(self.go_to_main_menu)
        ]

        self.projects_menu = [
            MenuOption('l', 'List locally cached projects', self.jira_manager.list_projects, pause=True),
            MenuOption('s', 'Search locally cached JiraIssues for a string', self.jira_manager.search_projects, pause=False),
            MenuOption('a', 'Add new JiraProject offline cache', self.jira_manager.cache_new_jira_project_data, pause=True),
            MenuOption('d', 'Delete offline cached ticket data for a JiraProject on a connection', self.jira_manager.delete_cached_jira_project),
            MenuOption('u', 'Update all locally cached project JIRA data', self.jira_manager.update_cached_jira_project_data, pause=False),
            MenuOption.print_blank_line(),
            MenuOption.return_to_previous_menu(self.go_to_main_menu)
        ]

        self.active_menu = self.main_menu  # type: List[MenuOption]
        self.menu_header = 'uninit'  # type: str
        self.go_to_main_menu()

        self._load_config()

        # let user read startup info
        pause()

        if 'Debug' in options:
            print('Running Debug')
            self.jira_manager.run_debug()
            exit(0)

    def go_to_main_menu(self) -> None:
        self.active_menu = self.main_menu
        self.menu_header = 'Main Menu (Version {})'.format(__version__)

    def go_to_dashboards_menu(self) -> None:
        self.active_menu = self.dashboards_menu
        self.menu_header = 'Dashboards Menu'

    def go_to_jira_views_menu(self) -> None:
        self.active_menu = self.jira_views_menu
        self.menu_header = 'Jira Views Menu'

    def go_to_reports_menu(self) -> None:
        self.active_menu = self.reports_menu
        self.menu_header = 'Reports Menu'

    def go_to_projects_menu(self) -> None:
        self.active_menu = self.projects_menu
        self.menu_header = 'Jira Project Menu'

    def go_to_teams_menu(self) -> None:
        self.active_menu = self.team_menu
        self.menu_header = 'Teams Menu'

    def go_to_jira_connections_menu(self) -> None:
        self.active_menu = self.jira_connections_menu
        self.menu_header = 'Jira Connections Menu'

    def go_to_jenkins_menu(self) -> None:
        self.active_menu = self.jenkins_menu
        self.menu_header = 'Jenkins Menu'

    def go_to_jenkins_reports_manager_menu(self) -> None:
        self.active_menu = self.jenkins_reports_manager_menu
        self.menu_header = 'Jenkins Reports Manager'

    def go_to_jenkins_connections_manager_menu(self) -> None:
        self.active_menu = self.jenkins_connections_manager_menu
        self.menu_header = 'Jenkins Connections Manager'

    def go_to_jenkins_connection_menu(self) -> None:
        self.active_menu = self.jenkins_connection_menu
        self.menu_header = 'Jenkins Connection Menu [{}]'.format(self.jenkins_manager.active_connection)

    def go_to_jenkins_report_menu(self) -> None:
        MainMenu.active_menu = self.jenkins_report_menu
        self.menu_header = 'Jenkins Report Menu [{}]'.format(self.jenkins_manager.active_report)

    def go_to_options_menu(self) -> None:
        self.active_menu = self.options_menu
        self.menu_header = 'Options Menu'

    def display(self) -> None:
        while True:
            clear()
            print(thick_separator)
            print('Argus - {}'.format(self.menu_header))
            print(thick_separator)

            for menu_option in self.active_menu:
                # Menu header
                if menu_option.hotkey is None:
                    print('')
                else:
                    print('{:2}: {foo}'.format(menu_option.hotkey, foo=menu_option.entry_name))
            print(thin_separator)

            c_input = get_input('>')

            # brute force ftw.
            for menu_option in self.active_menu:
                if c_input == menu_option.hotkey:
                    if menu_option.entry_method is not None:
                        menu_option.entry_method()
                    if menu_option.needs_pause:
                        pause()

    def _add_view(self) -> None:
        self.jira_manager.add_view()

    def _edit_view(self) -> None:
        self.jira_manager.edit_view()

    def _add_team(self) -> None:
        self.team_manager.prompt_for_team_addition(self.jira_manager)

    def _edit_team(self) -> None:
        self.team_manager.edit_team(self.jira_manager)

    def _change_password(self) -> None:
        try_one = getpass('Enter new local Argus Password: ')
        try_two = getpass('Confirm password: ')
        if try_one != try_two:
            print('ERROR! Mismatched passwords. Not changing.')
            return
        Config.MenuPass = try_one
        self.jira_manager.change_password()

    def _change_browser(self) -> None:
        change_browser()
        self._save_config()

    def _change_debug(self) -> None:
        if utils.argus_log is None:
            utils.argus_log = open('argus.log', 'w')
        utils.debug = not utils.debug

    def _change_show_dependencies(self) -> None:
        utils.show_dependencies = not utils.show_dependencies
        self._print_dependency_show_state()
        self._save_config()

    def _change_dependency_type(self) -> None:
        utils.show_only_open_dependencies = not utils.show_only_open_dependencies
        self._print_dependency_show_state()
        self._save_config()

    def _print_dependency_show_state(self) -> None:
        print('Current dependency display state: {}. Open only: {}'.format(utils.show_dependencies, utils.show_only_open_dependencies))

    def _add_multi_jira_dashboard(self) -> None:
        self.jira_manager.add_multi_jira_dashboard()

    def _run_team_report(self) -> None:
        self.team_manager.run_team_reports(self.jira_manager)

    def _run_org_report(self) -> None:
        self.team_manager.run_org_report(self.jira_manager)

    def add_linked_member(self) -> None:
        if self.jira_manager.jira_connection_count() <= 1:
            print('>= 2 JIRA connections are required to link members. You cannot link an individual to another account on one JiraConnection')
            return
        self.team_manager.create_new_member_alias(self.jira_manager)

    @staticmethod
    def signal_handler(signal, frame) -> None:
        # prevent double-print on debug
        if not utils.debug:
            print('\nShutting down Argus on SigInt.')
        argus_debug('Shutting down Argus on SigInt.')
        if utils.argus_log is not None:
            utils.argus_log.close()
        sys.exit(0)

    @staticmethod
    def _save_config() -> None:
        config_parser = configparser.RawConfigParser()
        config_parser.add_section('Argus')
        config_parser.set('Argus', 'Browser', Config.Browser)
        config_parser.set('Argus', 'Show_Dependencies', str(utils.show_dependencies))
        config_parser.set('Argus', 'Show_Only_Open_Dependencies', str(utils.show_only_open_dependencies))
        conf = os.path.join(conf_dir, 'argus.cfg')
        save_argus_config(config_parser, conf)

    def _load_config(self) -> None:
        if os.path.exists(argus_conf_file):
            config_parser = configparser.RawConfigParser()
            config_parser.read(argus_conf_file)
            Config.Browser = config_parser.get('Argus', 'Browser')
            if config_parser.has_option('Argus', 'Show_Dependencies'):
                utils.show_dependencies = bool(config_parser.get('Argus', 'Show_Dependencies'))
            if config_parser.has_option('Argus', 'Show_Only_Open_Dependencies'):
                utils.show_only_open_dependencies = bool(config_parser.get('Argus', 'Show_Only_Open_Dependencies'))
        else:
            # if we don't yet have a config file, go ahead and create one on this first pass w/default values
            self._save_config()

    def _display_readme(self) -> None:
        while True:
            print('======================================')
            print(' How To Use Argus ')
            print('======================================')
            clear()
            fn = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'readme.md')
            in_user_guide = False
            with open(fn, "r") as myfile:
                for line in myfile:
                    if "<!-- start_user_guide -->" in line:
                        in_user_guide = True
                        line = line.replace('<!-- start_user_guide -->', '')
                        print(line)
                    elif in_user_guide:
                        if "<!-- end_user_guide -->" not in line:
                            print(line)
                        else:
                            in_user_guide = False
                            line = line.replace('<!-- end_user_guide -->', '')
                            print(line)
            i = get_input('[q] to quit.')
            if i == 'q':
                break
