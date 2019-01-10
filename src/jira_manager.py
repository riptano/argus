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
import getpass
import os
import traceback

from jira import JIRAError
from typing import TYPE_CHECKING, Dict, Optional, List, Tuple

from src.display_filter import DisplayFilter
from src.jira_connection import JiraConnection
from src.jira_dashboard import JiraDashboard
from src.jira_filter import JiraFilter
from src.jira_project import JiraProject
from src.jira_utils import JiraUtils
from src.jira_issue import JiraIssue
from src.jira_view import JiraView
from src.utils import (ConfigError, argus_debug, clear, get_input, is_empty,
                       is_yes, jira_conf_file, pause, pick_value, print_separator,
                       save_argus_config, jira_project_dir, Config)

if TYPE_CHECKING:
    from src.team_manager import TeamManager


class JiraManager:

    """
    Contains multiple JiraConnection objects and re-initializes them on program startup
    The JiraManager houses most of the logic surrounding manipulating JiraConnection and JiraView objects, creating
    dashboards, editing, removing, etc.
    """

    def __init__(self, team_manager: 'TeamManager') -> None:
        """
        Recreates any JiraConnections and JiraViews based on saved data in conf/jira.cfg
        """

        self.team_manager = team_manager

        # Holds connected Jira objects to be queried by JiraViews
        self._jira_connections = {}  # type: Dict[str, JiraConnection]

        # JiraViews, caching filters for different ways to view Jira Data. Implicit 1:1 JiraConnection to JiraView
        self.jira_views = {}  # type: Dict[str, JiraView]

        self.jira_dashboards = {}  # type: Dict[str, JiraDashboard]

        # Used during JiraDependency resolution to notify user of missing JiraProjects
        self.missing_project_counts = {}  # type: Dict[str, int]

        self._display_filter = DisplayFilter.default()

        if os.path.exists(jira_conf_file):
            config_parser = configparser.RawConfigParser()
            config_parser.read(jira_conf_file)

            connection_names = []  # type: List[str]
            if config_parser.has_section('JiraManager') and config_parser.has_option('JiraManager', 'Connections'):
                connection_names = config_parser.get('JiraManager', 'Connections').split(',')

            # JiraConnections are the root of our container hierarchy
            for connection_name in connection_names:
                if connection_name == '':
                    pass
                try:
                    jira_connection = JiraConnection.from_file(connection_name)
                    # If we had an error on init we obviously cannot add this
                    if jira_connection is None:
                        continue
                    self._jira_connections[jira_connection.connection_name] = jira_connection
                except ConfigError as ce:
                    print('ConfigError with project {}: {}'.format(connection_name, ce))

            # Construct JiraViews so they can be used during JiraDashboard creation.
            view_names = []  # type: List[str]
            if config_parser.has_option('JiraManager', 'Views'):
                view_names = config_parser.get('JiraManager', 'Views').split(',')

            for name in view_names:
                try:
                    jv = JiraView.from_file(self, name, self.team_manager)
                    self.jira_views[jv.name] = jv
                except ConfigError as ce:
                    print('ConfigError with jira view {}: {}'.format(name, ce))

            if config_parser.has_section('Dashboards'):
                for dash in config_parser.options('Dashboards'):
                    dash_views = {}
                    for view in view_names:
                        if view not in self.jira_views:
                            print('Found dashboard {} with invalid view: {}. Skipping init: manually remove from config.'.format(
                                dash, view))
                            break
                        dash_views[view] = self.jira_views[view]
                    self.jira_dashboards[dash] = JiraDashboard(dash, dash_views)

        # Initialize JiraProjects from locally cached files
        for file_name in os.listdir(jira_project_dir):
            full_path = os.path.join(jira_project_dir, file_name)
            print('Processing locally cached JiraProject: {}'.format(full_path))
            # Init based on matching the name of this connection and .cfg
            print_separator(30)
            try:
                new_jira_project = JiraProject.from_file(full_path, self)
                if new_jira_project is None:
                    print('Error initializing from {}. Skipping'.format(full_path))
                    break
                if new_jira_project.jira_connection is None:
                    add = get_input('Did not find JiraConnection for JiraProject: {}. Would you like to add one now? (y/n)')
                    if add == 'y':
                        new_jira_connection = self.add_connection(
                            'Name the connection (reference url: {}):'.format(new_jira_project.url))
                        if new_jira_connection is None:
                            print('Error during connection add. Cannot link and use JiraProject.')
                            continue
                        new_jira_connection.save_config()
                        new_jira_project.jira_connection = new_jira_connection
                    else:
                        print('Did not add JiraConnection, so cannot link and use JiraProject.')
                        continue
                print('Updating with new data from JIRA instance')
                if Config.SkipUpdate:
                    print('Skipping initial update due to -s flag.')
                else:
                    new_jira_project.refresh()

                new_jira_project.jira_connection.add_and_link_jira_project(new_jira_project)
            except (configparser.NoSectionError, ConfigError) as e:
                print('WARNING! Encountered error initializing JiraProject from file {}: {}'.format(full_path, e))
                print('This JiraProject will not be initialized. Remove it manually from disk in conf/jira/projects and data/jira/')

        if len(self._jira_connections) == 0:
            print_separator(30)
            print('No JIRA Connections found. Prompting to add first connection.')
            self.add_connection()

        if os.path.exists('conf/custom_params.cfg'):
            config_parser = configparser.RawConfigParser()
            config_parser.read('conf/custom_params.cfg')
            custom_projects = config_parser.get('CUSTOM_PROJECTS', 'project_names').split(',')

            for project_name in custom_projects:
                argus_debug('Processing immutable config for custom project: {}'.format(project_name))
                # Find the JiraConnection w/matching URL, if any
                url = config_parser.get(project_name, 'url').rstrip('/')

                jira_project = self.maybe_get_cached_jira_project(url, project_name)
                if jira_project is not None:
                    # Don't need to cache since already done on ctor for JiraProject
                    argus_debug('Project already initialized. Skipping.')
                    continue

                # Didn't find the JiraProject, so we need to build one, cache, and link.
                custom_fields = {}
                field_names = config_parser.get(project_name, 'custom_fields').split(',')
                for field in field_names:
                    custom_fields[field] = config_parser.get(project_name, field)

                parent_jira_connection = None
                for jira_connection in list(self._jira_connections.values()):
                    if jira_connection.url == url:
                        parent_jira_connection = jira_connection
                        break

                # Create a JiraConnection for this JiraProject if we do not yet have one
                if parent_jira_connection is None:
                    print('WARNING! Did not find JiraConnection for project: {}, attempting to match url: {}'.format(project_name, url))
                    print('Known JiraConnections and their urls:')
                    for jira_connection in list(self._jira_connections.values()):
                        print('   {}: {}'.format(jira_connection.connection_name, jira_connection.url))
                    if is_yes('Would you like to add one now?'):
                        parent_jira_connection = self.add_connection('Name the connection (reference url: {}):'.format(url))
                        if parent_jira_connection is None:
                            print('Ran into error adding parent connection. Skipping.')
                    else:
                        print('JiraProject data and config will not be added nor cached. Either add it manually or restart Argus and reply y')
                        break

                new_jira_project = JiraProject(parent_jira_connection, project_name, url, custom_fields)
                if parent_jira_connection is not None:
                    parent_jira_connection.add_and_link_jira_project(new_jira_project)
        print('Resolving dependencies between JiraIssues')
        self._resolve_issue_dependencies()
        print('JiraManager initialization complete.')

    def add_connection(self, prompt: str = 'Name this connection:') -> Optional[JiraConnection]:
        """
        Swallows exceptions to allow for errors during JiraProject caching w/out invalidating addition of JiraConnection
        """
        connection_name = get_input(prompt)
        if is_empty(connection_name):
            return None

        url = get_input('JIRA url (example: http://issues.apache.org/jira/):').rstrip('/')
        if is_empty(url):
            return None

        user = get_input('JIRA user name:')
        if is_empty(user):
            return None

        password = getpass.getpass()

        new_jira_connection = JiraConnection(connection_name, url, user, password)
        self._jira_connections[new_jira_connection.connection_name] = new_jira_connection

        print('Must locally cache at least one project\'s JIRA history. Please select a project.')
        new_jira_connection.cache_new_jira_project(self)
        try:
            while True:
                if not is_yes('Add another project?'):
                    break
                new_jira_connection.cache_new_jira_project(self)
        except (JIRAError, IOError):
            print('Encountered exception processing JiraProjects. Saving base JiraConnection')
            traceback.print_exc()

        self._save_config()
        return new_jira_connection

    def remove_connection(self) -> None:
        """
        Removes an existing url/user/pass JIRA connection and the corresponding Jira object
        """
        selection = pick_value('Remove which jira connection? ', list(self._jira_connections.keys()), True, 'Cancel')
        if selection is None:
            return
        print('About to delete: {}, all related views, and all offline cached JiraProject data.'.format(selection))
        if is_yes('Are you sure?'):
            jira_connection = self._jira_connections[selection]
            jira_connection.delete_owned_views(self)
            jira_connection.delete_cached_project_data()
            del self._jira_connections[selection]
            self._save_config()

    def get_jira_connection(self, connection_name: str) -> JiraConnection:
        if connection_name not in list(self._jira_connections.keys()):
            raise ConfigError('Failed to find connection: {}'.format(connection_name))
        return self._jira_connections[connection_name]

    def get_jira_issue(self, jira_issue_key: str) -> Optional[JiraIssue]:
        """
        Iterates through all locally cached JiraProjects looking for the project associated with the input jira issue key. If we
        find it, we return that JiraIssue. Otherwise, None.
        """
        project_name = jira_issue_key.split('-')[0]
        jira_projects = self.get_all_cached_jira_projects()
        if project_name not in jira_projects:
            return None
        return jira_projects[project_name].get_issue(jira_issue_key)

    def delete_jira_view(self, jira_view_name: str) -> None:
        print('Deleting jira view: {}'.format(jira_view_name))
        del self.jira_views[jira_view_name]

    def possible_connections(self) -> List[str]:
        return list(self._jira_connections.keys())

    def list_all_jira_views(self) -> None:
        print('Defined JiraViews:')
        for jira_view in list(self.jira_views.values()):
            print('   {}'.format(jira_view))

    def display_view(self) -> None:
        view_name = pick_value('Which view?', list(self.jira_views.keys()), True, 'Back')
        if view_name is None:
            return
        self.jira_views[view_name].display_view(self)
        self._save_config()

    def add_view(self) -> None:
        if len(self._jira_connections) == 0:
            if is_yes('No JiraConnections to add a JiraView to. Would you like to add a connection now?'):
                self.add_connection()
            else:
                return None
        view_name = get_input('Name this view:')
        jira_connection_name = pick_value('Which JIRA Connection does this belong to?', list(self._jira_connections.keys()))
        if jira_connection_name is None:
            return
        new_view = JiraView(view_name, self._jira_connections[jira_connection_name])
        self.jira_views[view_name] = new_view
        new_view.edit_view(self, self.team_manager)
        self._save_config()

    def edit_view(self)-> None:
        if len(self.jira_views) == 0:
            if is_yes('No views to edit. Would you like to add a view?'):
                self.add_view()
            else:
                return
        view_name = pick_value('Select a view to edit', list(self.jira_views.keys()))
        if view_name is None:
            return
        view = self.jira_views[view_name]
        view.edit_view(self, self.team_manager)
        if view.is_empty():
            print('Jira View is empty. Remove it?')
            conf = get_input('Jira View is empty. Remove it? (q to cancel):')
            if conf == 'y':
                del self.jira_views[view_name]
        self._save_config()

    def remove_view(self) -> None:
        if len(self.jira_views) == 0:
            print('No views to remove.')
            return
        to_remove = pick_value('Select a view to delete or [q]uit: ', list(self.jira_views.keys()))
        if to_remove is None:
            return

        # Build list of Dashboards this is going to invalidate to confirm
        affected_dashes = []
        for dash in list(self.jira_dashboards.values()):
            if dash.contains_jira_view(to_remove):
                print('WARNING: Removing this view will also remove JiraDashboard: {}.'.format(dash))
                affected_dashes.append(dash.name)

        if is_yes('Are you sure you want to delete {}?'.format(to_remove)):
            self.jira_views[to_remove].delete_config()
            del self.jira_views[to_remove]

            # Determine if any dashboards exist w/this view and delete them
            for dash_name in affected_dashes:
                del self.jira_dashboards[dash_name]

            self._save_config()

    def list_dashboards(self) -> None:
        if len(self.jira_dashboards) == 0:
            print('No dashboards. Create one first.')
            return

        clear()
        print('Dashboards]')
        for dashboard in list(self.jira_dashboards.values()):
            print('{}'.format(dashboard))

    def display_dashboard(self) -> None:
        if len(self.jira_dashboards) == 0:
            print('No dashboards. Create one first.')
            return
        dn = pick_value('Display which dashboard\'s results?', list(self.jira_dashboards.keys()), True, 'Cancel')
        if dn is None:
            return

        self.jira_dashboards[dn].display_dashboard(self, self.jira_views)

    def add_dashboard(self) -> None:
        new_dash = JiraDashboard.build(self.jira_views)
        if new_dash is None:
            return
        self.jira_dashboards[new_dash.name] = new_dash
        self._save_config()

    def edit_dashboard(self) -> None:
        dn = pick_value('Which dashboard?', list(self.jira_dashboards.keys()), True, 'Cancel')
        if dn is None:
            return
        dash = self.jira_dashboards[dn]
        dash.edit_dashboard(self.jira_views)
        self._save_config()

    def remove_dashboard(self) -> None:
        dn = pick_value('Remove which dashboard?', list(self.jira_dashboards.keys()), True, 'Cancel')
        if dn is None:
            return
        prompt = get_input('About to delete [{}]. Are you sure?'.format(dn))
        if prompt == 'y':
            del self.jira_dashboards[dn]
            self._save_config()

    def display_escalations(self) -> None:
        jira_connection_name = pick_value('Select a JIRA Connection to view Escalation type tickets:',
                                          list(self._jira_connections.keys()))
        if jira_connection_name is None:
            return
        jira_connection = self._jira_connections[jira_connection_name]
        jira_issues = JiraUtils.get_issues_by_query(jira_connection,
                                                    'type = \'Escalation\' AND resolution = unresolved')
        issue_keys = []
        for issue in jira_issues:
            issue_keys.append(issue.issue_key)

        df = DisplayFilter.default()
        while True:
            print_separator(30)
            print(os.linesep + 'Escalations' + os.linesep)
            print_separator(30)
            clear()
            df.display_and_return_sorted_issues(self, jira_issues)
            i = get_input('[#] Integer to open issue in browser. [q] to quit.')
            if i == 'q':
                break
            try:
                c_input = int(i) - 1
                JiraUtils.open_issue_in_browser(jira_connection.url, issue_keys[c_input])
            except ValueError:
                print('Bad input. Try again')
                pause()

    def run_debug(self) -> None:
        while True:
            print_separator(80)
            print('Debug menu:')
            print('t: print a specific ticket\'s data')
            print('l: list custom fields for a JiraProject')
            print('r: (run current transient) - test print width formatting stuff')
            print('q: quit back to main menu')
            print_separator(80)
            menu_choice = get_input(':')
            if menu_choice == 't':
                ticket_name = get_input('Print what ticket? Note: this will fail unless you\'ve cached this project locally:', lowered=False)
                project_name = JiraIssue.get_project_from_ticket(ticket_name)

                if project_name == '' or project_name is None:
                    print('Failed to parse project name from ticket: {}. Try again.'.format(ticket_name))
                    continue

                jira_project = self.maybe_get_cached_jira_project_no_url(project_name)
                if jira_project is None:
                    print('Could not find cached version of {}. Add via project menu and try again.'.format(project_name))
                    continue

                ticket = jira_project.get_issue(ticket_name)
                if ticket is None:
                    print('Failed to get jira issue {} from project {}. Are you sure it is correct and/or cached?'.format(ticket_name, project_name))
                    continue

                if jira_project.jira_connection is not None:
                    print('Ticket: {}'.format(ticket.pretty_print(jira_project.jira_connection)))
            elif menu_choice == 'r':
                print('TEST: [{:{width}.{width}}]'.format('I am testing a 5.5 thing', width=5))
            elif menu_choice == 'l':
                jira_connection = self.pick_jira_connection('Show fields for project on which connection?')
                if jira_connection is None:
                    print('Nothing selected. Continuing.')
                    continue
                project = self.get_jira_connection(jira_connection.connection_name).pick_and_get_jira_project()
                if project is not None:
                    print('Showing custom fields for project: {}'.format(project.project_name))
                    for key, value in project._custom_fields:
                        print('Key: {}. Value: {}'.format(key, value))
            elif menu_choice == 'q':
                break
            else:
                print('Bad choice. Try again.')
            pause()

    def search_projects(self) -> None:
        """
        Does a one-off ad-hoc search for strings in all cached fields for all cached JiraProjects.
        Keeping at scope of JiraManager as search is a meta-scoped search of all cached JiraProjects independent of JiraConnection
        :return:
        """
        tinput = get_input('Search [o]pen issues only, [c]losed, or [a]ll?')
        substring = get_input('Search for what substring?')
        matches = []
        jira_projects = self.get_all_cached_jira_projects()

        # cache list of seen columns for the query
        columns = {}
        for project in list(jira_projects.values()):
            results = project.get_matching_issues(substring, tinput)
            for r in results:
                matches.append(r)
                for k, v in r.items():
                    # This is going to blast out our ability to filter on reviewer or reviewer 2. For now.
                    if 'custom' not in k:
                        columns[k] = True
        original_list = JiraUtils.sort_custom_jiraissues_by_key(matches)
        display_list = original_list

        df = DisplayFilter.default()
        while True:
            df.display_and_return_sorted_issues(self, display_list)
            print_separator(30)
            cinput = get_input(
                '[#] to open an issue in browser, [c] to clear column filters, [f] to specify a specific field to match on, [q] to return to menu:')
            if str.lower(cinput) == 'f':
                col_name = pick_value('Filter on which column?', list(columns.keys()), False)
                newlist = []
                for ji in display_list:
                    if col_name in ji:
                        if substring in ji[col_name]:
                            newlist.append(ji)
                display_list = newlist
            elif str.lower(cinput) == 'c':
                display_list = original_list
            elif not str.lower(cinput) == 'q':
                try:
                    jira_issue = display_list[int(cinput) - 1]
                    JiraUtils.open_issue_in_browser(
                        self._jira_connections[jira_issue.jira_connection_name].url, jira_issue.issue_key)
                except ValueError:
                    print('Bad input. Try again.')
            elif str.lower(cinput) == 'q':
                break

    def is_project_name_used(self, name: str) -> bool:
        """
        Convenience method so, upon addition of a new JiraProject, we can check whether or not the project name is already in use.
        This is relevant for dependency resolution as we key off issue only, so duplicate project names would cause problems.
        """
        for project in self.get_all_cached_jira_projects().values():
            if project.project_name == name:
                return True
        return False

    def _resolve_issue_dependencies(self) -> None:
        """
        Since JiraIssues contain str-based 'pointers' to other JiraIssues as dependents, we need to perform this evaluation
        in batch separately from a single issue or project caching addition.
        """
        self.missing_project_counts = {}
        for jira_project in self.get_all_cached_jira_projects().values():
            jira_project.resolve_dependencies(self)

        if len(self.missing_project_counts) > 0:
            print_separator(30)
            print('Encountered some missing offline cached JiraProjects during dependency resolution. Consider caching some of the following projects locally.')
            for project in sorted(self.missing_project_counts, key=self.missing_project_counts.get, reverse=True):
                print('Missing locally cached projects during dependency resolution. Project: {}. Count: {}'.format(project, self.missing_project_counts[project]))

    def create_non_cached_issue(self, issue_key: str) -> JiraIssue:
        """
        Exists in this scope to avoid circular dependencies
        """
        return JiraIssue.non_cached_issue(issue_key)

    def list_projects(self) -> None:
        jira_projects = self.get_all_cached_jira_projects()
        for project in list(jira_projects.values()):
            if project.jira_connection is None:
                continue
            print(' (Conn:{conn} Name:{name}). Issue count: {count}. Updated: {updated}'.format(
                conn=project.jira_connection.connection_name,
                name=project.project_name,
                count=len(project.jira_issues),
                updated=project.updated))

    def change_password(self) -> None:
        # Need to save config to re-encrypt all the username/password info w/new pass
        self._save_config()

    def add_multi_jira_dashboard(self) -> None:
        options = sorted(self._jira_connections.keys())
        add_new = 'Add a new Jira Connection'
        options.append(add_new)

        pairs = []  # type: List[Tuple[Optional[JiraConnection], str]]
        while True:
            print('Current contents of report]')
            for jira_connection, user in pairs:
                if jira_connection is None:
                    continue
                print('   Connection: {} User: {}'.format(jira_connection.connection_name, user))

            command = pick_value('[Connection inclusion]', options, True, 'Done', False)
            if command is None:
                break
            elif command == add_new:
                new_conn = self.add_connection()
                if new_conn is None:
                    return
            else:
                new_conn = self._jira_connections[command]

            print('Selecting user name from {}'.format(new_conn.connection_name))
            # Make mypy happy...
            if new_conn is None:
                return
            picked = new_conn.pick_single_assignee()
            if picked is None:
                return
            pairs.append((new_conn, picked))
        # Any error in the user addition process can bubble up with only 1 user selected
        if len(pairs) <= 1:
            print('Found less than the required minimum of 2 entries. Not adding report.')
            return

        name = ''
        while name == '':
            name = get_input('Name this report:')
        new_dash = JiraDashboard(name, {})

        # Create a JiraView for each of these and then dump them into the dashboard
        for jira_connection, user in pairs:
            # Make mypy happy...
            if jira_connection is None:
                continue
            view_name = '{}_{}'.format(jira_connection.connection_name, user)
            if view_name in list(self.jira_views.keys()):
                print('Already found a view named {} in jira_views. Using that instead.'.format(view_name))
                new_jira_view = self.jira_views[view_name]
            else:
                new_jira_view = JiraView('{}_{}'.format(jira_connection.connection_name, user), jira_connection)
                new_jira_view.add_single_filter('assignee', user, 'i', 'OR')
                new_jira_view.add_single_filter('reviewer', user, 'i', 'OR')
                new_jira_view.add_single_filter('reviewer2', user, 'i', 'OR')
                new_jira_view.add_single_filter('resolution', 'unresolved', 'i', 'AND')
                self.jira_views[new_jira_view.name] = new_jira_view
            new_dash.add_jira_view(new_jira_view)

        self.jira_dashboards[name] = new_dash
        print('Completed configuration of new report: {}'.format(name))
        self._save_config()

    def add_label_view(self) -> None:
        name = get_input('Name this view: ')
        jira_connection_name = pick_value('Which JIRA Connection does this belong to? ', list(self._jira_connections.keys()))
        if jira_connection_name is None:
            return
        jira_connection = self._jira_connections[jira_connection_name]
        new_view = JiraView(name, jira_connection)
        self.jira_views[name] = new_view
        jira_filter = JiraFilter('labels', jira_connection)
        while True:
            label = get_input('Add which label? ([q] to quit)')
            if label == 'q':
                break
            if label.isspace() or label == '':
                continue
            print('Adding label: [{}]'.format(label))
            jira_filter.include(label)
        res_jf = JiraFilter('Resolution', jira_connection)
        res_jf.include('unresolved')
        new_view.add_raw_filter(jira_filter)
        new_view.add_raw_filter(res_jf)
        self._save_config()
        new_view.display_view(self)
        print('Creating new view with label(s): {}'.format(','.join(jira_filter._includes)))

    def report_fix_version(self) -> None:
        """
        Creates a report of all tickets, including dependencies, to the input FixVersion.
        """
        # Only support creating of this on a single JiraConnection, with the assumption that multiple projects on that
        # connection can share a FixVersion, but these won't straddle to exterior Jira instances
        target_connection = self.pick_jira_connection('FixVersion report for which JiraConnection?')
        if target_connection is None:
            return

        open_only = is_yes('Show only unresolved issues?')

        to_match = get_input('Input substring to search fixversions for:', False)
        available_versions = set()
        for jira_project in target_connection.cached_projects:
            for jira_issue in jira_project.jira_issues.values():
                for fix in jira_issue['fixVersions'].split(','):
                    if to_match in fix:
                        available_versions.add(fix)

        report_version = pick_value('Generate report for which FixVersion?', list(available_versions))
        if report_version is None:
            return

        print('Generating report on: {}'.format(report_version))

        # Now find all "primary root" members on this FixVersion, generate a list of matching, then display w/dependency
        # chains enabled
        matching_issues = set()
        for jira_project in target_connection.cached_projects:
            for jira_issue in jira_project.jira_issues.values():
                if jira_issue.has_fix_version(report_version):
                    if (open_only and jira_issue.is_open) or not open_only:
                        matching_issues.add(jira_issue)

        df = DisplayFilter.default()
        df.open_only = open_only
        df.include_column('fixVersions', 'FixVersion', 10, 2)

        # sort our keys by issuekey
        sorted_results = JiraUtils.sort_custom_jiraissues_by_key(list(matching_issues))
        del matching_issues

        issues = df.display_and_return_sorted_issues(self, sorted_results, 1, None, True)
        while True:
            choice = get_input('[#] to open an issue in browser, [p] to print report again, [q] to quit report: ')
            if choice == 'q':
                break
            elif choice == 'p':
                df.display_and_return_sorted_issues(self, sorted_results, 1, None, True)
            try:
                int_choice = int(choice) - 1
                if int_choice < 0 or int_choice > len(issues) - 1:
                    raise ValueError('oops')
                chosen_issue = issues[int_choice]
                if not chosen_issue.is_cached:
                    print('Cannot open browser for non-cached issue (don\'t know url). Cache offline to inspect {}.'.format(chosen_issue.issue_key))
                else:
                    jira_conn = self._jira_connections[chosen_issue.jira_connection_name]
                    JiraUtils.open_issue_in_browser(jira_conn.url, chosen_issue.issue_key)
            except ValueError:
                print('Bad input. Try again.')

    def add_single_user_report(self) -> None:
        pass

    def _prompt_connection_add_if_none(self) -> bool:
        """
        :return: True if either a new connection is added or connections already exist
        """
        if len(self._jira_connections) == 0:
            if is_yes('Did not find any JiraConnections to cache a JiraProject. Would you like to add one now?'):
                self.add_connection()
                return True
            else:
                return False
        return True

    def pick_jira_connection(self, prompt: str = 'Which JIRA connection?') -> Optional[JiraConnection]:
        if not self._prompt_connection_add_if_none():
            return None

        choice = pick_value(prompt, list(self._jira_connections.keys()), True)
        if choice is None:
            return None

        return self._jira_connections[choice]

    def jira_connections(self) -> List[JiraConnection]:
        return list(self._jira_connections.values())

    def get_all_cached_jira_projects(self) -> Dict[str, JiraProject]:
        cached_projects = {}
        for jira_connection in list(self._jira_connections.values()):
            for jira_project in jira_connection.cached_projects:
                cached_projects[jira_project.project_name] = jira_project
        return cached_projects

    def maybe_get_cached_jira_project(self, url: str, project_name: str) -> Optional[JiraProject]:
        for jira_connection in list(self._jira_connections.values()):
            if jira_connection.url == url:
                return jira_connection.maybe_get_cached_jira_project(project_name)
        return None

    def maybe_get_cached_jira_project_no_url(self, project_name: str) -> Optional[JiraProject]:
        """
        Doesn't match on url, just returns whichever connection has the first matching project name.
        """
        # TODO: This will require rethinking / checking for duplication if we ever support duplicate JiraProject names
        for jira_connection in list(self._jira_connections.values()):
            maybe_project = jira_connection.maybe_get_cached_jira_project(project_name)
            if maybe_project:
                return maybe_project
        return None

    def cache_new_jira_project_data(self) -> None:
        if not self._prompt_connection_add_if_none():
            return

        jira_connection_name = pick_value('Cache project data for which JiraConnection?',
                                          [x.connection_name for x in list(self._jira_connections.values())])
        if jira_connection_name is None:
            return

        self._jira_connections[jira_connection_name].cache_new_jira_project(self)
        self._resolve_issue_dependencies()

    def delete_cached_jira_project(self) -> None:
        jira_connection_name = pick_value('Delete cached project data for which JiraConnection?',
                                          [x.connection_name for x in self.jira_connections()])
        if jira_connection_name is None:
            return

        jira_connection = self._jira_connections[jira_connection_name]
        project_cache_to_delete = pick_value('Delete cached data for which JiraProject?',
                                             jira_connection.cached_project_names)
        if project_cache_to_delete is None:
            return

        if is_yes('About to delete locally cached content: {}. Are you sure?'.format(
                jira_connection.maybe_get_cached_jira_project(project_cache_to_delete))):
            jira_connection.delete_cached_jira_project(project_cache_to_delete)

    def list_jira_connections(self) -> None:
        print('Known JiraConnection objects:')
        for jira_connection in list(self._jira_connections.values()):
            print('   {}'.format(jira_connection))

    def update_cached_jira_project_data(self, needs_pause=True) -> None:
        for jira_connection in list(self._jira_connections.values()):
            jira_connection.update_all_cached_jira_projects()
        if needs_pause:
            pause()

    def jira_connection_count(self) -> int:
        return len(self._jira_connections)

    def _save_config(self) -> None:
        """
        Saves config for JiraManager, all connections, and all views
        """
        config_parser = configparser.RawConfigParser()
        config_parser.add_section('JiraManager')
        config_parser.set('JiraManager', 'Connections', ','.join(list(self._jira_connections.keys())))
        # Need to re-save all jira connections to encode w/new password
        for jc in self._jira_connections:
            self._jira_connections[jc].save_config()
        print('Saved {} Jira Connections'.format(len(self._jira_connections)))
        if len(self.jira_views) > 0:
            config_parser.set('JiraManager', 'Views', ','.join(list(self.jira_views.keys())))
            for vn in list(self.jira_views.keys()):
                self.jira_views[vn].save_config()
            print('Saved {} Jira Views'.format(len(self.jira_views)))
        if len(self.jira_dashboards) > 0:
            config_parser.add_section('Dashboards')
            for dash in self.jira_dashboards:
                self.jira_dashboards[dash].save_config(config_parser)

        save_argus_config(config_parser, jira_conf_file)
