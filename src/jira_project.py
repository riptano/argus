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
import traceback
from typing import TYPE_CHECKING, List, Optional

from src import utils
from src.jira_filter import JiraFilter
from src.jira_issue import JiraIssue
from src.jira_utils import JiraUtils
from src.jira_view import JiraView
from src.utils import (ConfigError, argus_debug, jira_data_dir,
                       save_argus_config, jira_project_dir)

if TYPE_CHECKING:
    from src.jira_manager import JiraManager
    from src.jira_connection import JiraConnection
    from typing import Dict, Optional, List, Set


class JiraProject:
    """
    Caches JIRA data locally in data dir in JiraIssue format and contains logic to update / refresh
    itself since the last known time JIRA data was queried.
    """

    def __init__(self,
                 jira_connection,  # type: Optional['JiraConnection']
                 project_name,  # type: str
                 url,  # type: str
                 custom_fields=None,  # type: Optional[Dict[str, str]]
                 issues=None,  # type: Optional[Dict[str, JiraIssue]]
                 updated='1970/01/01 00:00'  # type: str
                 ) -> None:
        """
        :param url: str, used to map projects to JiraConnections since we serialize separately on disk. We pass this separately
            in order to allow for None jira_connection __init__ for default specified JiraProjects from custom_parems.cfg
        :param custom_fields: {}, field to customfield_NNN mappings
        :param issues: dict of issues to add to this project
        """
        if custom_fields is None:
            custom_fields = {}
        self.jira_connection = jira_connection  # type: Optional['JiraConnection']
        self.project_name = project_name
        self._custom_fields = custom_fields
        if url is not None:
            self._url = url.rstrip('/')
        else:
            self._url = ''

        # jira date format
        self.updated = updated

        # map of issue key to JiraIssue
        if issues is None:
            issues = {}
        self.jira_issues = issues  # type: Dict[str, JiraIssue]

        # Set our max timestamp based on issues in this object cache
        for jira_issue in list(self.jira_issues.values()):
            try:
                if jira_issue.updated is not None:
                    clean_ts = JiraProject.clean_ts(jira_issue.updated)
                    if self.updated is None or clean_ts > self.updated:
                        self.updated = clean_ts
            except KeyError:
                print('Error pulling updated ts from JiraIssue with key: {}. Skipping.'.format(jira_issue.issue_key))

        self._known_assignees = set()  # type: Set[str]
        self._known_reviewers = set()  # type: Set[str]

        if jira_connection is not None:
            jira_connection.add_and_link_jira_project(self)
        self.add_field_translations_from_file()

    @property
    def url(self) -> str:
        return self._url

    def populate_contributors(self) -> None:
        """
        Pulls from all cached JiraIssues to determine all assignees and reviewers
        """
        self._known_assignees = set()  # type: Set[str]
        self._known_reviewers = set()  # type: Set[str]

        for key, issue in self.jira_issues.items():
            if issue.assignee is not None:
                self._known_assignees.add(issue.assignee)
            if self.jira_connection is not None:
                if issue.reviewer(self.jira_connection) is not None:
                    to_add = issue.reviewer(self.jira_connection)
                    if to_add is not None:
                        self._known_reviewers.add(to_add)
                if issue.reviewer2(self.jira_connection) is not None:
                    to_add = issue.reviewer2(self.jira_connection)
                    if to_add is not None:
                        self._known_reviewers.add(to_add)

    def add_field_translations_from_file(self) -> None:
        """
        Pulls custom translations from conf/custom_params.cfg and initializes this JiraProject with them if they are
        not otherwise defined
        """
        if not os.path.exists('conf/custom_params.cfg'):
            return
        else:
            config_parser = configparser.RawConfigParser()
            config_parser.read('conf/custom_params.cfg')

        # Current limitation: one hard-coded set of config per project name. i.e. one URL
        if config_parser.has_section(self.project_name):
            url = config_parser.get(self.project_name, 'url').rstrip('/')
            if url != self._url:
                msg = 'WARNING! Found project {} but url mismatched (project: {} and file: {}). Not loading translations.'
                print(msg.format(self.project_name, self._url, url))
                return

            field_names = config_parser.get(self.project_name, 'custom_fields').split(',')
            changed = False
            for field in field_names:
                if field not in self._custom_fields:
                    for cf in list(self._custom_fields.keys()):
                        print('   Known: {}'.format(cf))
                    changed = True
                    translated_value = config_parser.get(self.project_name, field)
                    print('Adding missing custom field translation from conf/custom_params.cfg for '
                          'project: {} field: {} value: {}'.format(self.project_name, field, translated_value))
                    self._custom_fields[field] = translated_value
            if changed:
                print('Migrated custom params from conf/custom_params.cfg into project: {}. Saving config.'.format(
                    self.project_name))
                self.save_config()
            else:
                argus_debug('No changes from custom_params necessary for {}'.format(self.project_name))

    @staticmethod
    def clean_ts(ts: str) -> str:
        """
        Expects input in format YYYY-MM-DDTHH:MM:SS.000+0000
        Removes T, cuts out all past minute
        """
        # Sanitize the format from JIRA a bit since the stored JIRA format != the format JQL accepts later
        sa = ts.split(':')
        return '{}:{}'.format(sa[0], sa[1]).replace('T', ' ')

    @classmethod
    def from_file(cls, file_name: str, jira_manager: 'JiraManager') -> Optional['JiraProject']:
        """
        Associates JiraConnection with JiraProject on creation. Adds JiraProject to JiraConnection internal
        project collection.
        :param file_name: str name of config file on disk to load from
        :param jira_manager: JiraManager to pull JiraConnection from
        """
        try:
            # Load config data from .cfg file
            config_parser = configparser.RawConfigParser()
            config_parser.read(file_name)
            jira_connection_name = config_parser.get('Config', 'connection_name')
            jira_connection = jira_manager.get_jira_connection(jira_connection_name)
            project_name = config_parser.get('Config', 'project_name')
            updated = config_parser.get('Config', 'updated')
            url = config_parser.get('Config', 'url').rstrip('/')

            custom_fields = {}
            if config_parser.has_option('Config', 'custom_fields'):
                raw_fields = config_parser.get('Config', 'custom_fields')
                if raw_fields != '':
                    parsed_fields = raw_fields.split(',')
                    for field in parsed_fields:
                        custom_fields[field] = config_parser.get('Config', field)

            # load cached data if any is available
            data_file_name = JiraProject.data_file(jira_connection_name, project_name)
            jira_issues = {}
            if not os.path.exists(data_file_name):
                print('No data file found for JiraProject: {} (missing file: {}). Setting timestamp to epoch'.format(project_name, data_file_name))
                # reset last seen timestamp to epoch
                updated = '1970/01/01 00:00'
            else:
                print('Loading cached JIRA from disk for project: {}'.format(project_name))
                with open(data_file_name, 'rb') as data_file:
                    count = 0
                    while True:
                        if count != 0 and count % 1000 == 0:
                            print('Processed {} issues'.format(count))
                        count += 1
                        try:
                            parsed_issue = JiraIssue.deserialize(data_file)
                            jira_issues[parsed_issue.issue_key] = parsed_issue
                        except EOFError:
                            break

            new_jira_project = JiraProject(jira_connection=jira_connection, project_name=project_name, url=url,
                                           custom_fields=custom_fields, issues=jira_issues, updated=updated)
            jira_connection.add_and_link_jira_project(new_jira_project)
        except (IOError, configparser.NoOptionError):
            print('Failed to load cached data for project/connection from config file: {}'.format(file_name))
            traceback.print_exc()
            return None
        issue_count = len(new_jira_project.jira_issues.keys()) if new_jira_project.jira_issues is not None else 0
        print('Loaded project {} with {} issues cached. Last updated: {}'.format(new_jira_project.project_name,
                                                                                 issue_count,
                                                                                 new_jira_project.updated))
        new_jira_project.save_config()
        return new_jira_project

    def save_config(self) -> None:
        # .cfg file
        argus_debug('jira_project.save_config call.')
        config_parser = configparser.RawConfigParser()
        config_parser.add_section('Config')
        if self.jira_connection is not None:
            config_parser.set('Config', 'connection_name', self.jira_connection.connection_name)
        config_parser.set('Config', 'project_name', self.project_name)
        config_parser.set('Config', 'updated', self.updated)
        config_parser.set('Config', 'url', self._url)
        config_parser.set('Config', 'custom_fields', ','.join(list(self._custom_fields.keys())))
        for field in list(self._custom_fields.keys()):
            config_parser.set('Config', field, self._custom_fields[field])

        save_argus_config(config_parser, self.config_file())

        # Protect against saving during init wiping out the local data file. Shouldn't be an issue but seen it pop up
        # during dev once or twice.
        if len(self.jira_issues.keys()) > 0:
            JiraUtils.save_argus_data(list(self.jira_issues.values()), self._data_file())

    def delete_on_disk_files(self) -> None:
        if utils.unit_test:
            return

        if os.path.isfile(self.config_file()):
            os.remove(self.config_file())
        if os.path.isfile(self._data_file()):
            os.remove(self._data_file())

        print('Successfully deleted cached Jira data for project: {}'.format(self))
        self.jira_connection = None

    def refresh(self) -> None:
        assert self.jira_connection is not None
        new_issues = JiraUtils.get_issues_for_project(self.jira_connection, self.project_name, self.updated)
        if len(new_issues) > 0:
            print('Found {} updated/new issues for {}. Saving to disk.'.format(len(new_issues), self.project_name))
            for jira_issue in new_issues:
                if 'updated' not in jira_issue:
                    print('Missing updated field in issue: {}. Skipping in latest updated calculation.'.format(
                        jira_issue.issue_key))
                else:
                    clean_ts = JiraProject.clean_ts(jira_issue['updated'])
                    if clean_ts > self.updated:
                        self.updated = clean_ts
                self.jira_issues[jira_issue.issue_key] = jira_issue
            self.save_config()

    def link_jira_connection(self, jira_connection: 'JiraConnection') -> None:
        if jira_connection.url != self._url:
            raise ConfigError(
                'Attempted to link mismatched JiraConnection {} to JiraProject {}'.format(jira_connection, self))
        self.jira_connection = jira_connection

    def config_file(self) -> str:
        assert self.jira_connection is not None
        return os.path.join(jira_project_dir, '{}_{}.cfg'.format(self.jira_connection.connection_name, self.project_name))

    def _data_file(self) -> str:
        assert self.jira_connection is not None
        return JiraProject.data_file(self.jira_connection.connection_name, self.project_name)

    @staticmethod
    def data_file(connection_name: str, project_name: str) -> str:
        return os.path.join(jira_data_dir, '{}_{}.dat'.format(connection_name, project_name))

    def get_matching_issues(self, search_string: str, search_type: str = 'a') -> List[JiraIssue]:
        """
        :param search_type: 'a': all. 'o': open. 'c': closed
        """
        results = []
        if self.jira_connection is not None:
            for k, v in self.jira_issues.items():
                if v.matches(search_string):
                    if search_type == 'o' and v.is_open:
                        results.append(v)
                    elif search_type == 'c' and v.is_closed:
                        results.append(v)
                    elif search_type == 'a':
                        results.append(v)
        return results

    def get_filtered_issues(self, jira_filter: JiraFilter) -> List[JiraIssue]:
        """
        Applies a JiraFilter to all issues within this project
        """
        results = []  # type: List[JiraIssue]
        if self.jira_connection is None or len(self.jira_issues) == 0:
            return results

        for key, jira_issue in self.jira_issues.items():
            if jira_filter.includes_jira_issue(jira_issue) and not jira_filter.excludes_jira_issue(jira_issue):
                results.append(jira_issue)
        return results

    def get_issues_by_view(self, jira_view: JiraView) -> List[JiraIssue]:
        pass

    def owns_issue(self, issue: JiraIssue) -> bool:
        """
        Determines whether JiraConnection for issue matches this project and project_name matches
        """
        assert self.jira_connection is not None
        return issue.project_name == self.project_name and issue.jira_connection_name == self.jira_connection.connection_name

    def get_issue(self, issue_key: str) -> Optional[JiraIssue]:
        return None if issue_key not in self.jira_issues else self.jira_issues[issue_key]

    # TEST ONLY
    def add_issue(self, jira_issue: JiraIssue) -> None:
        self.jira_issues[jira_issue.issue_key] = jira_issue

    def translate_custom_field(self, field_name: str) -> str:
        """
        Returns original untralsnated name if field isn't custom
        """
        if field_name not in self._custom_fields:
            return field_name
        return self._custom_fields[field_name]

    def resolve_dependencies(self, jira_manager: 'JiraManager') -> None:
        """
        Resolves any links between jira tickets, translating from str repr to in-memory ref to JiraIssue
        """
        for jira_issue in self.jira_issues.values():
            jira_issue.resolve_dependencies(jira_manager)

    def __str__(self) -> str:
        conn_name = self.jira_connection.connection_name if self.jira_connection is not None else 'unknown'
        return '{}:{} {}:{} {}:{} {}:{} {}:{}'.format(
            'JiraProject', self.project_name,
            'url', self._url,
            'jira_connection_name', conn_name,
            'updated', self.updated,
            'JiraIssue count', len(list(self.jira_issues.keys()))
        )
