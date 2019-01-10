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

from configparser import RawConfigParser
from typing import TYPE_CHECKING, List, Optional

from src.utils import argus_debug, get_input, pick_value

if TYPE_CHECKING:
    from src.jira_connection import JiraConnection
    from src.jira_manager import JiraManager
    from src.jira_issue import JiraIssue


class JiraFilter:

    """
    Contains one or many attributes to filter a jira query on.
    Different data requested by the filter is housed here.
    The reason we cache the JiraConnection is that custom field translation depends on metadata from the JiraConnection.
    To make translation of custom fields not require passing in the JiraConnection, we cache it
    """

    def __init__(self,
                 field: str,
                 jira_connection: 'JiraConnection',
                 query_type: str = 'AND',
                 includes: Optional[List[str]] = None,
                 excludes: Optional[List[str]] = None) -> None:
        self.field = field
        self._jira_connection = jira_connection

        self._query_type = query_type

        # Stored in easy plain-text, not custom-field name. Translated to custom field on a per-project basis.
        self._includes = [] if includes is None else includes
        self._excludes = [] if excludes is None else excludes

    def include(self, value: str) -> None:
        # Special case. Use 'None' field as Unresolved in JIRA
        # NOTE: Upon addition of a 2nd mapping such as this, consider refactoring to a local Dict[str:str] of mappings
        if self.field == 'resolution' and value.lower() == 'unresolved':
            self._includes.append('None')
        else:
            self._includes.append(value)

    def exclude(self, value: str) -> None:
        #   Special case. Use 'None' field as Unresolved in JIRA
        if self.field == 'resolution' and value == 'unresolved':
            self._excludes.append('None')
        else:
            self._excludes.append(value)

    def remove_filter(self) -> None:
        print('Removing from JiraFilter: {}'.format(self))
        action = get_input('Remove [i]nclude, [e]xclude, or [q]uit')
        if action == 'i':
            to_remove = pick_value('Remove which include?', self._includes)
            if to_remove is None:
                return
            self._includes.remove(to_remove)
        elif action == 'e':
            to_remove = pick_value('Remove which exclude?', self._excludes)
            if to_remove is None:
                return
            self._excludes.remove(to_remove)

    def is_empty(self) -> bool:
        return len(self._includes) + len(self._excludes) == 0

    def set_or(self) -> None:
        self._query_type = 'OR'

    def set_and(self) -> None:
        self._query_type = 'AND'

    def query_type(self) -> str:
        return self._query_type

    def _translate_field(self, jira_issue: 'JiraIssue') -> str:
        """
        For this issue, parse out the JiraProject it belongs to and translate our local field's readable text to
        whatever cf* is on the project side
        """
        jira_project = self._jira_connection.maybe_get_cached_jira_project(jira_issue.project_name)
        if jira_project is None:
            argus_debug('jira_project is none. Returning None in _translate_field.')
            return 'None'
        argus_debug('JiraFilter: Attempting to translate {} for jira_issue: {}'.format(
            self.field, jira_issue.issue_key))
        return jira_project.translate_custom_field(self.field)

    def _internal_match(self, jira_issue: 'JiraIssue', to_match: List[str]) -> bool:
        """
        For a given list of strings to match for (either inclusion list or exclusion from the JiraFilter), determine
        whether the translated field from the JiraIssue matches that list + taking into account if it matches
        the AND / OR logic.
        """
        matches_one = False
        matches_all = True

        # can't match what we don't have
        if len(to_match) == 0:
            argus_debug('      We don\'t have any entries for this category - returning False.')
            return False

        translated = self._translate_field(jira_issue)
        argus_debug('list of possible value matches: {}'.format(to_match))
        argus_debug('translated value: {}'.format(translated))

        if translated in jira_issue:
            argus_debug('found translated value in jira_issue')
            for match in to_match:
                if match in jira_issue[translated]:
                    matches_one = True
                else:
                    matches_all = False

        argus_debug('matches_one: {} and matches_all: {}'.format(matches_one, matches_all))

        if self.query_type() == 'OR':
            argus_debug('query_type is OR, returning matches_one: {}'.format(matches_one))
            return matches_one

        argus_debug('query_type not OR, returning matches_all: {}'.format(matches_all))
        return matches_all

    def matches_jira_issue(self, jira_issue: 'JiraIssue') -> bool:
        matches = self.includes_jira_issue(jira_issue)
        argus_debug('   included determined to be: {}'.format(matches))
        excluded = self.excludes_jira_issue(jira_issue)
        argus_debug('   excluded determined to be: {}'.format(excluded))
        return matches and not excluded

    def includes_jira_issue(self, jira_issue: 'JiraIssue') -> bool:
        return self._internal_match(jira_issue, self._includes)

    def excludes_jira_issue(self, jira_issue: 'JiraIssue') -> bool:
        return self._internal_match(jira_issue, self._excludes)

    def extract_value(self, jira_issue: 'JiraIssue') -> str:
        translated = self._translate_field(jira_issue)
        if translated not in jira_issue:
            return 'N/A'
        return jira_issue[translated]

    @property
    def field_name(self) -> str:
        return self.field

    def set_field_name(self, value: str) -> None:
        self.field = value

    @classmethod
    def from_file(cls, jira_manager: 'JiraManager', filter_field: str, config_parser: RawConfigParser) -> 'JiraFilter':
        jira_connection_name = config_parser.get(filter_field, 'jira_connection')
        jira_connection = jira_manager.get_jira_connection(jira_connection_name)
        result = JiraFilter(filter_field, jira_connection)

        and_or = config_parser.get(filter_field, 'query_type')
        if str(and_or) == 'AND':
            result.set_and()
        else:
            result.set_or()

        if config_parser.has_option(filter_field, 'inclusions'):
            includes = config_parser.get(filter_field, 'inclusions').split(',')
            for i in includes:
                result.include(i)
        if config_parser.has_option(filter_field, 'exclusions'):
            excludes = config_parser.get(filter_field, 'exclusions').split(',')
            for e in excludes:
                result.exclude(e)

        return result

    def save_config(self, config_parser: RawConfigParser) -> None:
        config_parser.add_section(self.field)
        config_parser.set(self.field, 'name', self.field)
        config_parser.set(self.field, 'jira_connection', self._jira_connection.connection_name)
        config_parser.set(self.field, 'query_type', self._query_type)
        if len(self._includes) > 0:
            config_parser.set(self.field, 'inclusions', ','.join(self._includes))
        if len(self._excludes) > 0:
            config_parser.set(self.field, 'exclusions', ','.join(self._excludes))

    def __str__(self) -> str:
        return 'name: {} type: {} _includes: {} _excludes: {}'.format(self.field, self._query_type, ','.join(self._includes), ','.join(self._excludes))
