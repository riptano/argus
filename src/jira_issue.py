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
import pickle
import re
from typing import TYPE_CHECKING, Dict, List, Optional, Set

import six
from jira import Issue
from jira.resources import Version

from src.jira_dependency import JiraDependency
from src.utils import ConfigError

if TYPE_CHECKING:
    from src.jira_connection import JiraConnection
    from src.jira_project import JiraProject


class JiraIssue(dict):

    """
    Decorated dictionary member that contains an issue_key and the name of the jira_connection this JiraIssue belongs to.
    As the base jira objects coming back from the JIRA library are dict entries, we just decorate them.
    """

    # self.version reference:
    #   1: offline cached w/dependency chain resolution
    #      adds [.version: int] and [.is_cached: bool]

    def __init__(self, jira_connection: Optional['JiraConnection'], issue: Issue, **kwargs: Dict) -> None:
        """
        :exception ConfigError: On deser, if we encounter an unknown conversion from an old version we raise ConfigError.
            All other values are blindly stored in the object, so we may run into corruption that transparently passes
            through here.
        """
        super(JiraIssue, self).__init__(**kwargs)
        if jira_connection:
            self.jira_connection_name = jira_connection.connection_name
        else:
            self.jira_connection_name = 'None'
        self.issue_key = issue.key
        self.dependencies = set()  # type: Set[JiraDependency]
        self.version = 1

        # bool indicates whether this is a fully functional JiraIssue or just a dummy placeholder w/issuekey for dep resolution
        self.is_cached_offline = True

        # We convert from the issue.fields dict object into local attributes of the JiraIssue rather than nesting
        # them inside a separate collection.
        # Protect against None on unit test stubs
        if issue.fields:
            for k, v in six.iteritems(issue.fields.__dict__):
                # Convert issuelinks to a local id:type dependency mapping. We store a list of strings as issuelinks.
                # Since we can have multiple relationships to a single ticket, we store a list and allow duplicate
                # issuekey entries.
                if k == 'issuelinks' and len(v) > 0:
                    result = ''
                    for member in v:
                        if hasattr(member, 'inwardIssue'):
                            relation_direction = 'inward'
                            related_key = member.inwardIssue
                        else:
                            relation_direction = 'outward'
                            related_key = member.outwardIssue
                        result += '{}:{}:{},'.format(related_key, member.type, relation_direction)
                    dict.__setitem__(self, 'issuelinks', result)

                elif k == 'fixVersions' and len(v) > 0:
                    result = []

                    # Some backwards compat logic necessary here based on serialized version on disk.
                    # This can be stored as a jira.resources.Version object, a raw string comma delim with name=, or a
                    # comma delim string of just id's (latest format)
                    for version in v:
                        # If serialized in a jira.resources.Version object, we only care about fixver string
                        if type(version) == Version:
                            result.append(str(version.name))
                        # Otherwise we convert from an interim raw string format to a parsed array of version strings:
                        #     [<JIRA Version: name='1.1.2', id='12321445'>, <JIRA Version: name='1.2.0 beta 1', id='12319262'>]
                        elif isinstance(version, str) and 'name' in version:
                            result_match = re.search('name=\'([0-9A-Za-z_\.]+)\'', version)
                            if not result_match:
                                raise ConfigError('WARNING! Discovered fixVersions string with unexpected format. Expected "name=([value])" and got: {}.'.format(version))
                            result.append(result_match.group(1))
                        # If it's a list, we assume it's the list of the versions we're interested in. May need to revisit
                        # this assumption later.
                        elif isinstance(version, list):
                            result.append(version)
                        else:
                            raise ConfigError('Received unexpected type in fixVersion: {} for ticket: {}'.format(type(version), self.issue_key))
                    self['fixVersions'] = ','.join(result)
                else:
                    dict.__setitem__(self, str(k), str(v))

    @staticmethod
    def non_cached_issue(issue_key: str) -> 'JiraIssue':
        """
        Used to represent a non-cached JiraIssue for use during dependency resolution storage / visualization
        :return: a JiraIssue w/out an active connection or any fields outside the issue key
        """
        new_issue = Issue(None, None)
        new_issue.key = issue_key
        result = JiraIssue(None, new_issue)
        result['relationship'] = 'MISSING CHAIN'
        result['summary'] = 'BREAK IN CHAIN. Cache offline to see deps.'
        result.is_cached_offline = False

        # hard-code it to being open since we don't know
        result['resolution'] = None
        return result

    def matches(self, jira_connection: 'JiraConnection', find: str) -> bool:
        """
        Tests all values in the ticket to see if they match the input string.
        Requires input of the JiraConnection you want to compare against to protect against
        duplicate project names across different JIRA instances.
        """
        if self.jira_connection_name == jira_connection.connection_name:
            # Test against issue key separately
            if find in self.issue_key:
                return True
            for value in list(self.values()):
                if find in value:
                    return True
        return False

    def matches_any(self, jira_connection: 'JiraConnection', to_match: List[str]) -> bool:
        """
        Batches multiple regex matches for JiraView usage. If regexes is empty, we consider that fully inclusive and matching
        """
        # A touch redundant as we re-check in matches, but should prevent a lot of overchecking on each field
        if self.jira_connection_name == jira_connection.connection_name:
            if len(to_match) == 0:
                return True
            for regex in to_match:
                if self.matches(jira_connection, regex):
                    return True
        return False

    # ----------------------------------------------------------------------------------------------------
    # Some convenience Accessors
    @property
    def is_open(self):
        return self['resolution'] is None or self['resolution'] == 'None' or self['resolution'] == 'Unresolved'

    @property
    def is_closed(self):
        return not self.is_open

    @property
    def project_name(self):
        return self.issue_key.split('-')[0]

    @property
    def resolved(self) -> Optional[str]:
        # Don't have to use get_field for non-custom fields, so no need for a JiraConnection
        # JIRA lib in python uses resolutiondate instead of resolved. argh.
        return None if 'resolutiondate' not in self else self['resolutiondate']

    @property
    def assignee(self) -> Optional[str]:
        # Don't have to use get_field for non-custom fields, so no need for a JiraConnection
        return None if 'assignee' not in self else self['assignee']

    @property
    def labels(self) -> List[str]:
        if 'labels' not in self:
            return []
        return self['labels']

    @property
    def issuetype(self) -> Optional[str]:
        return self['issuetype']

    @property
    def status(self) -> Optional[str]:
        return self['status']

    @property
    def is_feature(self) -> bool:
        return 'New Feature' == self.issuetype or 'Improvement' == self.issuetype

    @property
    def is_test(self) -> bool:
        if self.matches_label('test', False) or self.issuetype == 'Test':
            return True
        return False

    # ----------------------------------------------------------------------------------------------------

    def has_fix_version(self, version: str) -> bool:
        return version in self['fixVersions']

    def is_owned_by(self, jira_connection: 'JiraConnection', name: str) -> bool:
        """
        Checks fields to see if this issue is owned by the member name passed in, as either assignee or reviewer(2)
        """
        return name == self.assignee or self.is_reviewer(jira_connection, name)

    def get_reviewer(self, jira_connection: 'JiraConnection') -> Optional[str]:
        custom_field = self.translate_custom_field(jira_connection, 'reviewer')
        return None if custom_field not in self else self[custom_field]

    def is_reviewer(self, jira_connection: 'JiraConnection', name: str) -> bool:
        """
        Checks if 'reviewer' or 'reviewer2''s custom translation matches the input name
        :param jira_connection: we need the JiraConnection for per-project custom field translation
        """
        return self.matches_field(jira_connection, 'reviewer', name) or self.matches_field(jira_connection, 'reviewer2', name)

    def matches_field(self, jira_connection: 'JiraConnection', field: str, value: str) -> bool:
        """
        Returns whether or not the ticket matches a regex on a given field name.
        Missing a field translates into no match.
        """
        local_value = self.get_value(jira_connection, field)
        if local_value is None:
            return False
        return value == local_value

    def has_label(self, label: str) -> bool:
        """
        Explicit case-sensitive label match.
        """
        return label in self.labels

    def matches_label(self, to_match: str, case_sensitive: bool=True) -> bool:
        """
        Regex match for inclusion of part of a string in labels.
        """
        to_match = to_match.lower() if not case_sensitive else to_match
        for label in self.labels:
            label = label.lower() if not case_sensitive else label
            if to_match in label:
                return True
        return False

    def get_jira_project(self, jira_connection: 'JiraConnection') -> 'JiraProject':
        """
        :exception IOError: if we fail to find locally cached data files for this JiraProject, this will raise an exception.
        """
        jira_project = jira_connection.maybe_get_cached_jira_project(self.project_name)
        if jira_project is None:
            raise IOError('Failed to find JiraProject {} on JiraConnection {} for issue: {}. Delete the locally cached data and re-download the project.'.format(
                self.project_name, self.jira_connection_name, self.issue_key))
        return jira_project

    def translate_custom_field(self, jira_connection: 'JiraConnection', field: str) -> str:
        jira_project = self.get_jira_project(jira_connection)
        return jira_project.translate_custom_field(field)

    def get_value(self, jira_connection: 'JiraConnection', field: str) -> Optional[str]:
        field_name = self.translate_custom_field(jira_connection, field)
        if field_name not in self:
            return None
        return self[field_name]

    def component_list(self) -> List[str]:
        """
        Returns a colon-delimited list of components in this JiraIssue
        """
        return re.findall("name=u'([A-Za-z0-9_ \-]+)'", self['components'])

    def resolve_dependencies(self, jira_manager):
        """
        issuelinks field is stored as a string with format ['issue1','issue2','issue3']. We do this for ser/deser cleanliness
        and then materialize those links in memory as references to other JiraIssues after all cached projects are loaded
        from disk.
        """
        # Create the object if pickle loading didn't deser the empty set
        if not hasattr(self, 'dependencies'):
            self.dependencies = set()  # type: Set[JiraDependency]

        if len(self['issuelinks']) != 0:
            dep_array = self['issuelinks'].split(',')
            for dep_str in dep_array:
                # We have a few ways this can 'no-op', so we protect against them and skip here.
                if dep_str is None or dep_str == '' or dep_str == '[]':
                    continue

                try:
                    dependency = JiraDependency(dep_str, jira_manager)
                except AssertionError as ae:
                    print('Got bad input as dependency string on issue: {}.'.format(self.issue_key))
                    print(ae)
                    continue

                self.dependencies.add(dependency)

    def __hash__(self):
        """
        Hash on issue_key. This will need to be revisited if we ever allow duplicate JiraProject names across different
        JiraConnections
        """
        return hash(self.issue_key)

    def __str__(self):
        result = 'key:{},'.format(self.issue_key)
        result += os.linesep + '   jira_connection_name:{}'.format(self.jira_connection_name)
        result += os.linesep + '   [FIELDS]'
        for k, v in self.items():
            result += os.linesep + '   {}:{},'.format(k, v)
        return result

    def serialize(self, file_handle):
        # Do not save dummy placeholders to disk
        if not self.is_cached_offline:
            return
        pickle.dump(self, file_handle)

    @staticmethod
    def deserialize(file_handle):
        result = pickle.load(file_handle)
        # Initial Non-versioned serialization on disk to versioned conversion
        if not hasattr(result, 'version'):
            result.version = 1
        if not hasattr(result, 'is_cached'):
            result.is_cached = True
        return result
