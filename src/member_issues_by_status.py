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

import itertools
from configparser import RawConfigParser
from typing import Dict, List, Optional, TYPE_CHECKING

from src.display_filter import DisplayFilter
from src.jira_connection import JiraConnection
from src.jira_issue import JiraIssue
from src.jira_utils import JiraUtils
from src.utils import pick_value

if TYPE_CHECKING:
    from src.jira_manager import JiraManager
    from src.team_reports import ReportFilter


class JiraUserName:
    """
    It's a little too irritating to have a bunch of tuple manipulation and str conversion lying around. Since we can
    have duplicate user names across multiple jira instances, we have to store the combined object and check for its presence
    instead of just one or the other. We also store the team name since these are used in team context only. A JiraUserName
    is uniquely identified by a: the name, b: the jira connection, and c: the team.
    """

    def __init__(self, user_name: str, jira_connection_name: str, team_name: str) -> None:
        self.user_name = user_name
        self.jira_connection_name = jira_connection_name
        self.team_name = team_name

    @property
    def to_combined_string(self) -> str:
        return '{}:{}:{}'.format(self.user_name, self.jira_connection_name, self.team_name)

    @classmethod
    def from_combined_string(cls, combined_string: str) -> 'JiraUserName':
        sa = combined_string.split(':')
        if len(sa) != 3:
            raise Exception('Got bad string to JiraUserName.from_combined_string. Expected : delim with 3 members, got: {}'.format(combined_string))
        return JiraUserName(sa[0], sa[1], sa[2])

    def __str__(self) -> str:
        return self.to_combined_string


class MemberIssuesByStatus:
    """
    JiraConnection agnostic list of issues owned by the given team member. Multiple names and their JiraConnection name
    are cached in the object to denote the various JiraIssue ownership relationships this member has.
    """

    def __init__(self, jira_user_name: JiraUserName) -> None:
        # Use to identify the primary user name. Do not include in known names list so we don't duplicate serialization
        self.primary_name = jira_user_name

        self._aliased_names = {}  # type: Dict[str, JiraUserName]

        # WARNING: These containers also need to be reflected in self.clear and self.sort_tickets
        self.assigned: List[JiraIssue] = []
        self.closed: List[JiraIssue] = []
        self.reviewer: List[JiraIssue] = []
        self.reviewed: List[JiraIssue] = []

    def clone_empty(self) -> 'MemberIssuesByStatus':
        """
        Creates a clone of this member without any populated JiraIssues
        """
        result = MemberIssuesByStatus(self.primary_name)
        for alias in list(self._aliased_names.values()):
            result.add_alias(alias)
        return result

    def save_config(self, config_parser: RawConfigParser) -> None:
        config_parser.add_section(self.full_name)

        # Create comma delimited list of : delimited known names for this linked user
        config_parser.set(self.full_name, 'aliases', ','.join(list(self._aliased_names.keys())))

        # Don't need to serialize _jira_connection_names as they're a redundant ease-of-use structure
        # We do not serialize the issues we iterate over within this object

    @classmethod
    def from_file(cls, root_name: str, config_parser: RawConfigParser) -> 'MemberIssuesByStatus':
        new_user = JiraUserName.from_combined_string(root_name)
        result = MemberIssuesByStatus(new_user)

        tokens = config_parser.get(root_name, 'aliases')
        if len(tokens) > 0:
            for token in config_parser.get(root_name, 'aliases').split(','):
                result.add_alias(JiraUserName.from_combined_string(token))
        return result

    @property
    def connection_names(self) -> List[str]:
        result = [self.primary_name.jira_connection_name]
        for combined_name in list(self._aliased_names.values()):
            result.append(combined_name.jira_connection_name)
        return result

    @property
    def full_name(self) -> str:
        return self.primary_name.to_combined_string

    @property
    def primary_user_name(self) -> str:
        return self.primary_name.user_name

    @property
    def primary_team(self) -> str:
        return self.primary_name.team_name

    def add_alias(self, jira_user_name: JiraUserName) -> None:
        self._aliased_names[jira_user_name.to_combined_string] = jira_user_name

    def remove_alias(self) -> bool:
        if len(self._aliased_names) == 0:
            print('No aliases. Returning.')
            return False

        to_remove = pick_value('Remove which alias from this member?', list(self._aliased_names.keys()))
        if to_remove is None:
            return False

        del self._aliased_names[to_remove]
        return True

    def closed_test_count(self) -> int:
        return len([x for x in self.closed if x.is_test])

    def add_if_owns(self, jira_connection: JiraConnection, jira_issue: JiraIssue) -> bool:
        """
        Note: this can theoretically leave duplicate JiraIssues in various lists
        Definition of "owns" in this context is: is assignee or reviewer of project
        """
        assert len(self.connection_names) > 0, 'add_if_owns on a member with no cached jira connection names'

        if jira_connection.connection_name not in self.connection_names:
            return False

        # We could optimize this by adding to the appropriate connection on determination of relationship with the
        # JiraUserName, but we need to use the 'does this MemberIssuesByStatus object own this ticket' logic during
        # ReportFilter detail processing as well. Consider optimization here later as needed.
        owning_jira_name = self.get_owning_jira_user_name(jira_connection, jira_issue)
        if owning_jira_name is None:
            return False

        owning_name = owning_jira_name.user_name
        if jira_issue.is_closed:
            if jira_issue.is_reviewer(jira_connection, owning_name):
                self.reviewed.append(jira_issue)
            elif jira_issue.assignee == owning_name:
                self.closed.append(jira_issue)
        else:
            if jira_issue.is_reviewer(jira_connection, owning_name):
                self.reviewer.append(jira_issue)
            elif jira_issue.assignee == owning_name:
                self.assigned.append(jira_issue)
            else:
                print('LOGIC ERROR! owning_name: {} assignee: {} reviewer: {} reviewer2: {}'.format(owning_name, jira_issue.assignee, jira_issue.get_reviewer(jira_connection), jira_issue.get_value(jira_connection, 'reviewer2')))
                raise Exception('owning_name is: {} but we did not match assignee nor reviewer on ticket: {}'.format(owning_name, jira_issue.issue_key))
        return True

    @staticmethod
    def _debug_ticket(jira_issue, to_print: str) -> None:
        """
        Developer tool to debug matching / JiraIssue categorization logic for reports
        """
        if MemberIssuesByStatus.is_debug_jira_issue(jira_issue):
            print('DEBUG: {}'.format(to_print))

    @staticmethod
    def is_debug_jira_issue(jira_issue: JiraIssue) -> bool:
        # Change XXX-1234 to the ticket you'd like to debug, add calls to _debug_ticket in relevant locations
        # return jira_issue.issue_key == 'XXX-1234'
        # TODO: Make this init from a flat config file, debug_issues.txt
        return False

    def get_owning_jira_user_name(self, jira_connection: JiraConnection, jira_issue: JiraIssue) -> Optional[JiraUserName]:
        """
        Determines which, if any, of the JiraUserNames associated with this MemberIssuesByStatus worked on this JiraIssue
        """
        for jira_user_name in itertools.chain(list(self._aliased_names.values()), [self.primary_name]):
            if jira_user_name.jira_connection_name != jira_connection.connection_name:
                continue

            user_name = jira_user_name.user_name
            if jira_issue.assignee == user_name or jira_issue.is_reviewer(jira_connection, user_name):
                return jira_user_name
        if self.is_debug_jira_issue(jira_issue):
            print('NO MATCH')
        return None

    @classmethod
    def formatted_header(cls) -> str:
        return '{:40} {:15} {:15} {:15} {:15} {:15}'.format(
            'name(s)', 'assigned', 'reviewer', 'closed test', 'closed', 'reviewed')

    def formatted_summary(self) -> str:
        return '{:40} {:<15} {:<15} {:<15} {:<15} {:<15}'.format(
            str(sorted(self._aliased_names.keys()))[:40].ljust(40), len(self.assigned), len(self.reviewer),
            self.closed_test_count(), len(self.closed),
            len(self.reviewed))

    def sort_tickets(self) -> None:
        self.assigned = JiraUtils.sort_jira_issues(self.assigned)
        self.closed = JiraUtils.sort_jira_issues(self.closed)
        self.reviewer = JiraUtils.sort_jira_issues(self.reviewer)
        self.reviewed = JiraUtils.sort_jira_issues(self.reviewed)

    def clear(self) -> None:
        self.assigned = []
        self.closed = []
        self.reviewer = []
        self.reviewed = []

    @property
    def all_tickets(self) -> List[JiraIssue]:
        return self.assigned + self.closed + self.reviewer + self.reviewed

    def display_member_issues(self, jira_manager: 'JiraManager', report_filter: 'ReportFilter') -> List[JiraIssue]:
        """
        Prints details for tickets by category. This method is always executed in the context of having a relevant
        ReportFilter in use for the display. Can use a no-op all-inclusive ReportFilter if you want to report all issues
        for this MemberIssuesByStatus.
        :param: jira_manager: Needed for display of 'pretty names' of custom columns by DisplayFilter
        :param: report_filter: Used to determine which issues to display
        :return: Sorted list of keys printed in this report
        """
        print('[Detailed report for {}]'.format(self.primary_name))

        df = DisplayFilter.team_details()

        idx = 1
        issues_displayed = []

        # Use a scratch array so we don't print a summary for something we don't have details for
        scratch = [x for x in self.assigned if report_filter.contains_issue(x)]
        if len(scratch) > 0:
            print('\n[ASSIGNED]')
            sorted_issues = df.display_and_return_sorted_issues(jira_manager, scratch, idx)
            idx += len(sorted_issues)
            for jira_issue in sorted_issues:
                issues_displayed.append(jira_issue)

        scratch = [x for x in self.reviewer if report_filter.contains_issue(x)]
        if len(scratch) > 0:
            print('\n[REVIEWER]')
            sorted_issues = df.display_and_return_sorted_issues(jira_manager, scratch, idx)
            idx += len(sorted_issues)
            for jira_issue in sorted_issues:
                issues_displayed.append(jira_issue)

        closed_test = []
        closed_non_test = []
        for jira_issue in [x for x in self.closed if report_filter.contains_issue(x)]:
            # Note: designation of tickets as being 'test' related is via a label, not a component or issuetype
            if jira_issue.matches_label('test', False):
                closed_test.append(jira_issue)
                issues_displayed.append(jira_issue)
            else:
                closed_non_test.append(jira_issue)
                issues_displayed.append(jira_issue)

        if len(closed_test) > 0:
            print('\n[CLOSED TEST]')
            printed = df.display_and_return_sorted_issues(jira_manager, closed_test, idx)
            idx += len(printed)

        if len(closed_non_test) > 0:
            print('\n[CLOSED NON-TEST]')
            printed = df.display_and_return_sorted_issues(jira_manager, closed_non_test, idx)
            idx += len(printed)

        scratch = [x for x in self.reviewed if report_filter.contains_issue(x)]
        if len(scratch) > 0:
            print('\n[REVIEWED]')
            printed = df.display_and_return_sorted_issues(jira_manager, scratch, idx)
            idx += len(printed)
            for jira_issue in printed:
                issues_displayed.append(jira_issue)

        return issues_displayed

    def __str__(self) -> str:
        return 'primary name: {} known aliases: {} assigned: {} reviewer: {} closed test: {} closed: {} reviewed: {}'.format(
            self.primary_name,
            sorted(self._aliased_names.keys()),
            len(self.assigned), len(self.reviewer), self.closed_test_count(),
            len(self.closed), len(self.reviewed))
