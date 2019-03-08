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
import itertools
import os
import traceback
from typing import TYPE_CHECKING, List, Optional, Dict

import requests
from jira import Project
from jira.client import JIRAError, JIRA
from requests.auth import HTTPBasicAuth

from src import utils
from src.jira_filter import JiraFilter
from src.jira_issue import JiraIssue
from src.jira_project import JiraProject
from src.test_wrapped_jira_connection_stub import TestWrappedJiraConnectionStub
from src.utils import (ConfigError, clear, decode, encode,
                       encode_password, get_input, pick_value,
                       save_argus_config, jira_connection_dir, argus_debug)

if TYPE_CHECKING:
    from src.jira_manager import JiraManager


class JiraConnection:

    """
    Contains metadata for a jira connection and houses the resulting Jira object once connected
    """

    def __init__(self, connection_name='unknown', url='unknown', user_name='unknown', password='unknown', dummy=False) -> None:
        self.possible_projects = []  # type: List[str]

        self.connection_name = connection_name
        self._url = url.rstrip('/')
        self._user = user_name
        self._pass = password
        self._wrapped_jira_connection = None

        # Internal representation is simply name of project. We have a 1:many mapping of JiraConnection
        # to JiraProjects, and cannot have multiple projects with the same name on a single JIRA underlying object.
        self._cached_jira_projects = {}  # type: Dict[str, JiraProject]

        if connection_name == 'unknown':
            raise ConfigError('Got JiraConnection constructor call with no connection_name. Cannot use this.')

        # Create the JIRA connection, bailing if we have an error with auth
        try:
            if utils.unit_test or dummy:
                self._wrapped_jira_connection = TestWrappedJiraConnectionStub()
            else:
                self._wrapped_jira_connection = JIRA(server=self._url, basic_auth=(self._user, self._pass))
        except JIRAError as je:
            if '401' in str(je.response):
                print('Received HTTP 401 response. Likely a mistyped local argus password. Try again.')
            elif '404' in str(je.response):
                print('Recieved HTTP 404 response with url: {}'.format(je.url))
            else:
                print('Received HTTP error response. url: {} response: {}'.format(je.url, je.response))
            print('Exiting due to failed Jira Connection attempt.')
            exit()
        if utils.unit_test:
            print('DEBUG MODE. JiraConnection stubbed to locally generated names. Will not save config changes nor query.')
        else:
            print('JIRA connection active for {}.'.format(self.connection_name))

        if not dummy:
            self.save_config()

    @classmethod
    def from_file(cls, connection_name: str) -> Optional['JiraConnection']:
        """
        Raises ConfigError if file is missing, internal data fails validation, or assignee list fails to be queried
        """
        config_file = cls._build_config(connection_name)
        if not os.path.isfile(config_file):
            raise ConfigError('Cannot initialize JIRA instance: {}. Missing config file: {}'.format(
                connection_name, cls._build_config(connection_name)))

        try:
            cp = configparser.RawConfigParser()
            cp.read(cls._build_config(connection_name))
            url = cp.get('Connection', 'url').rstrip('/')
            user = decode(encode_password(), cp.get('Connection', 'user'))
            password = decode(encode_password(), cp.get('Connection', 'password'))

            result = JiraConnection(connection_name, url, user, password)
            result.possible_projects = cp.get('Connection', 'projects').split(',')

            return result
        except configparser.NoOptionError as e:
            print('Failed to create JiraConnection from file: {}. Error: {}'.format(config_file, str(e)))
            return None

    def save_config(self) -> None:
        """
        Blindly overwrites existing config file for connection.
        """
        config_parser = configparser.RawConfigParser()
        config_parser.add_section('Connection')
        config_parser.set('Connection', 'url', self._url)
        config_parser.set('Connection', 'user', encode(encode_password(), self._user))
        config_parser.set('Connection', 'password', encode(encode_password(), self._pass))
        config_parser.set('Connection', 'projects', ','.join(self.possible_projects))

        save_argus_config(config_parser, self._build_config(self.connection_name))

    def pick_single_assignee(self) -> Optional[str]:
        """
        Having pick_assignees return an array of size 1 is very error prone. This wraps that.
        """
        result = self.pick_assignees(1)
        if result is None:
            return None
        return result[0]

    def pick_assignees(self, max_count: int) -> Optional[List[str]]:
        """
        The available user count can be untenable for caching offline so we rely on the REST API rather than caching.
        :param: max_count [int] value >= 1 of max # of users to return
        :return: list of selected assignees
        """

        result = []  # type: List[str]

        while True:
            issue_key = get_input('Input ticket name (PROJ-#) to enumerate possible assignees:')

            if issue_key == 'q':
                return None
            elif '-' not in issue_key:
                print('Invalid issue key (missing -). Aborting.')
            else:
                break

        # case sensitive
        issue_key = issue_key.upper()

        msg = 'Enter a substring to search assignee names for (real name, not UserName), [q] to Quit:'
        try:
            while True:
                snippet = get_input(msg, lowered=False)
                if snippet == 'q':
                    return result
                url = '{}/rest/api/2/user/assignable/search?username={}&project={}&issueKey={}'.format(
                    self._url,
                    snippet,
                    issue_key.split('-')[0],
                    issue_key)
                print('Querying user matches...')
                response = requests.get(url, auth=HTTPBasicAuth(self._user, self._pass))
                if response.status_code == 404:
                    print('Got a 404 on url: {}. Likely a missing issue, but could be a bug. Try again.'.format(url))
                    return None
                elif response.status_code != 200:
                    raise ConfigError(
                        'Failed to retrieve assignees for project: {} matching substring: {}. HTTP return code: {}. url: {}'.format(
                            self.connection_name, snippet, response.status_code, url))

                matched = []
                for val in response.json():
                    matched.append(val['displayName'])
                if len(matched) != 0:
                    picked = pick_value(header='Which of the following assignees matching substring: {}?'.format(snippet),
                                        options=matched,
                                        allow_exit=True,
                                        exit_text='Enter another substring',
                                        sort=True,
                                        silent=False)
                    if picked is not None:
                        print('Added {}'.format(picked))
                        msg = 'Enter another substring to search for, [q] to Quit:'
                        result.append(picked)
                        if len(result) == max_count:
                            return result
        except (JIRAError, ConfigError):
            print('Received error attempting to query user from JIRA. Aborting.')
            traceback.print_exc()
            return None

    def pick_project(self, skip_cached: bool = False) -> Optional[str]:
        self._refresh_project_names()
        coll = self.possible_projects[:]
        if skip_cached:
            for project_name in list(self._cached_jira_projects.keys()):
                coll.remove(project_name)

        pick = None
        # Loop to allow trying different substrings
        while pick is None:
            ss = get_input('Enter portion of name (case sensitive) (\'q\' to quit):', lowered=False)
            if ss.lower() == 'q':
                return None
            matches = sorted([x for x in coll if ss in x])
            if len(matches) == 0:
                print('No matches found. Try again.')
                continue
            pick = pick_value('Which:', matches, True, 'Enter different substring')
            if pick is None:
                clear()
        return pick

    def _refresh_project_names(self) -> None:
        # Cache project names locally within this object
        projects = []  # type: List[Project]
        if self._wrapped_jira_connection is not None:
            projects = self._wrapped_jira_connection.projects()
        self.possible_projects = []
        for p in projects:
            if 'deprecated' not in p.name:
                self.possible_projects.append(p.key)

        if len(self.possible_projects) == 0:
            print('No projects found in {}.'.format(self.connection_name))

    def add_and_link_jira_project(self, jira_project: JiraProject) -> None:
        # just overwrite it if we already have one with this name. Expected on init.
        self._cached_jira_projects[jira_project.project_name] = jira_project
        jira_project.jira_connection = self
        self._refresh_project_names()

    def cache_new_jira_project(self, jira_manager: 'JiraManager') -> None:
        project_name = self.pick_project(True)
        if project_name is None:
            return
        # Since we key off issue name for dependency chain resolution, we disallow duplicate JiraProject names on multiple
        # JiraConnections.
        if jira_manager.is_project_name_used(project_name):
            print('WARNING! Requested use of duplicate project name {} which is already cached on an active JiraConnection. This is not currently supported.')
            return
        new_project = JiraProject(self, project_name, self._url)
        new_project.refresh()
        new_project.save_config()
        self._cached_jira_projects[project_name] = new_project

    def pick_and_get_jira_project(self) -> Optional[JiraProject]:
        project_name = self.pick_project()
        if project_name is None:
            return None
        return self.maybe_get_cached_jira_project(project_name)

    def maybe_get_cached_jira_project(self, project_name: str) -> Optional[JiraProject]:
        if project_name not in self._cached_jira_projects:
            return None
        return self._cached_jira_projects[project_name]

    def get_matching_jira_issues(self, jira_filter: JiraFilter) -> List[JiraIssue]:
        results = []  # type: List[JiraIssue]
        for name, jira_project in self._cached_jira_projects.items():
            pre_len = len(results)
            results.extend(jira_project.get_filtered_issues(jira_filter))
            post_len = len(results)
            argus_debug('Added {} matching jira issues from jira_project: {}'.format(post_len - pre_len, name))
        return results

    @property
    def cached_project_names(self) -> List[str]:
        return list(self._cached_jira_projects.keys())

    @property
    def cached_projects(self) -> List[JiraProject]:
        return list(self._cached_jira_projects.values())

    @property
    def cached_jira_issues(self) -> List[List[JiraIssue]]:
        return list(itertools.chain([list(x.jira_issues.values()) for x in list(self._cached_jira_projects.values())]))

    def update_all_cached_jira_projects(self) -> None:
        for cached_project in list(self._cached_jira_projects.values()):
            cached_project.refresh()

    def delete_cached_jira_project(self, cached_project_name: str) -> None:
        jira_project = self._cached_jira_projects.pop(cached_project_name, None)
        if jira_project is None:
            return
        jira_project.delete_on_disk_files()

    def delete_cached_project_data(self):
        for cached_data in list(self._cached_jira_projects.values()):
            cached_data.delete_on_disk_files()

    def delete_owned_views(self, jira_manager: 'JiraManager') -> None:
        to_remove = []
        for jira_view in list(jira_manager.jira_views.values()):
            if jira_view.owned_by(self):
                to_remove.append(jira_view.name)

        for view_to_delete in to_remove:
            jira_manager.delete_jira_view(view_to_delete)

    def contains_project(self, project_name) -> bool:
        return project_name in self.possible_projects

    # Not annotating type since it can return a List or a ResultList
    def search_issues(self, *args, **kwargs):
        return self._wrapped_jira_connection.search_issues(*args, **kwargs)

    @property
    def url(self) -> str:
        return self._url

    @classmethod
    def _build_config(cls, name: str) -> str:
        return os.path.join(jira_connection_dir, '{}.cfg'.format(name))

    def __str__(self) -> str:
        result = 'JiraConnection:{conn} URL:{url} User:{user}'.format(
            conn=self.connection_name,
            url=self._url,
            user=self._user)
        for cached_project in list(self._cached_jira_projects.values()):
            result += os.linesep + '   |-{}'.format(cached_project)
        return result
