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
import pydoc
from typing import TYPE_CHECKING, Dict, List, Optional, Set

from src import utils
from src.jira_dependency import JiraDependency
from src.jira_issue import JiraIssue
from src.jira_utils import JiraUtils

if TYPE_CHECKING:
    from src.jira_manager import JiraManager


class DisplayFilter:

    """
    A class containing a list of Columns to display, ColumnFilters to filter out specific JiraIssues, and the logic
    to traverse JiraDependencies on JiraIssues for display.
    """

    RELATIONSHIP_STRING = 'relationship'

    _key_len = 20

    # Used to track index internally of multiple calls on print / display. Since we use this index in order
    # to accept user input to open detailed browser window reports of issues, we want to make sure it's
    # a monotonically increasing number reflective of various filtering and ordering of issues.
    _current_index = 0

    # Used to print variable #'s of indentation on dependency chains
    _current_depth = 0

    _max_depth = 5

    # Set used to track JiraIssue keys we've already seen during a dependency chain traversal. This prevents infinite recursion.
    _seen_keys = set()  # type: Set[str]

    def __init__(self):
        self.included_columns = []  # type: List[Column]

        # column filters to apply to any input jira issues
        self._column_filters = {}  # type: Dict[str, ColumnFilter]

        # Used to easily filter to open only, since a Column-based match would require multiple filter entries (None, unresolved, etc)
        self.open_only = False

        # Allow per-report suppression of dependency resolution as some reports are not well served by them
        self.suppress_dependencies = False  # type: bool

        # Toggle between printing and using the system pager
        self.use_pager = True  # type: bool

    @classmethod
    def default(cls):
        df = DisplayFilter()
        df.include_column(DisplayFilter.RELATIONSHIP_STRING, DisplayFilter.RELATIONSHIP_STRING, 15)
        df.include_column('assignee', 'assignee', 10)
        df.include_column('reviewer', 'reviewer', 10)
        # df.include_column('reviewer2', 10)
        df.include_column('summary', 'summary', 50)
        df.include_column('issuetype', 'type', 6)
        df.include_column('priority', 'prio', 6)
        df.include_column('labels', 'labels', 15)
        df.include_column('resolution', 'resolution', 10)
        df.include_column('status', 'status', 8)
        # Need to unify on a single column to indicate a release for a ticket
        # df.include_column('fixVersion', 'fixVersion', 8)
        df.include_column('updated', 'updated', 10)
        return df

    @classmethod
    def team_details(cls):
        df = DisplayFilter()
        df.include_column(DisplayFilter.RELATIONSHIP_STRING, DisplayFilter.RELATIONSHIP_STRING, 15)
        df.include_column('summary', 'summary', 50)
        df.include_column('issuetype', 'type', 6)
        df.include_column('status', 'status', 8)
        df.include_column('priority', 'prio', 6)
        df.include_column('resolution', 'resolution', 10)
        df.suppress_dependencies = True
        df.use_pager = False
        return df

    def include_column(self, column_name: str, pretty_name: str, width: int, index: int = -1) -> None:
        """
        :param index: Index to append column to, -1 (default) to append at end of current list
        """
        new_col = Column(column_name, pretty_name, width)
        if index == -1:
            self.included_columns.append(new_col)
        else:
            self.included_columns.insert(index, new_col)

    def save_config(self):
        pass

    @classmethod
    def from_file(cls):
        pass

    def _format_spaced_column(self, issue, column):
        # Special handling for components, since it's an array of components in a JiraIssue
        if column.name == 'components' and column.name in issue:
            cl = issue.component_list
            for c in cl:
                print('FOUND COMPONENT: {}'.format(c))
            to_format = ','.join(issue.component_list)
        else:
            to_format = 'No Data' if column.name not in issue else issue[column.name]
        return '| {} '.format(to_format[:column.width].ljust(column.width))

    def _construct_header(self) -> str:
        header = '-------------------------------------------------------------------------\n'
        # Add 5 to key len to account for 4 char on numeric index + : separator
        header += 'Idx--Key'.ljust(self._key_len + 5)
        for column in list(self.included_columns):
            header += '| {} '.format(column.pretty_name[:column.width].ljust(column.width))
        return header + os.linesep

    def display_and_return_sorted_issues(self,
                                         jira_manager: 'JiraManager',
                                         issues: List[JiraIssue],
                                         start_idx: int = 1,
                                         filters: Optional[Dict['Column', str]] = None,
                                         force_show_dependencies: bool = False,
                                         ) -> List[JiraIssue]:
        """
        Returns a copy of the displayed collection so exterior sources can rely on sorting that took place in DisplayFilter
        instead of relying on sorting in JiraView
        :param: jira_manager: Needed in order to interpret custom columns during reporting
        :param: filters: dict of col to substr to filter on
        :return: an array of filtered issues
        """
        self._current_index = start_idx

        # add padding to account for numbered tickets
        if filters is None:
            filters = {}
        result = self._construct_header()

        filtered_count = 0
        displayed_issues = []  # type: List[JiraIssue]
        for issue in issues:
            # We reset our circular dependency sentinel for each issue so as not to exclude dependencies for already
            # viewed tickets while still preventing meaningless duplication on a chain.
            DisplayFilter._seen_keys = set()
            result += self._format_jira_issue(jira_manager, issue, filters, displayed_issues, None, force_show_dependencies)  # type: ignore

        if self.use_pager:
            pydoc.pager(result)
        else:
            print(result)

        if filtered_count != 0:
            print('Skipped {} filtered results'.format(filtered_count))
        return displayed_issues

    def _format_jira_issue(self,
                           jira_manager: 'JiraManager',
                           issue: JiraIssue,
                           filters: Dict['Column', str],
                           displayed_issues: List[JiraIssue],
                           dependency: Optional[JiraDependency] = None,
                           force_show_dependencies: bool = False
                           ) -> str:
        """
        If the input JiraIssue matches the filters passed in, formats and returns a string representation of the issue.
        Recursion to format sub-rows is handled in this method.
        """
        if self.open_only and issue.is_closed:
            return ''

        # Terminal condition of recursion
        if self._current_depth > self._max_depth:
            return ''

        result = self._build_issue_row(jira_manager, issue, filters, dependency)
        DisplayFilter._seen_keys.add(issue.issue_key)

        # if we're filtered out on this row, we move on
        if result == '':
            return result
        displayed_issues.append(issue)

        DisplayFilter._current_depth += 1
        if not self.suppress_dependencies and (force_show_dependencies or utils.show_dependencies):
            # Display all dependencies of this ticket
            for dependency in issue.dependencies:
                if dependency.target.issue_key in DisplayFilter._seen_keys:
                    continue
                # We only skip if both the report allow it and the global setting specifies it
                elif dependency.target.is_closed and utils.show_only_open_dependencies and self.open_only:
                    continue
                result += self._format_jira_issue(jira_manager, dependency.target, filters, displayed_issues, dependency)
        DisplayFilter._current_depth -= 1

        return result

    def _build_issue_row(self,
                         jira_manager: 'JiraManager',
                         issue: 'JiraIssue',
                         filters: Dict['Column', str],
                         dependency: Optional['JiraDependency'] = None
                         ) -> str:
        """
        :param filters: Inclusion-based column-value filters: skips entire row based on this inclusion.
        :param dependency: Optional JiraDependency. Presence of this field indicates this JiraIssue is a dependent ticket,
        which changes our logic somewhat on how we format things (paren, indentation, etc)
        """
        if dependency is None:
            issue_key = issue.issue_key
        else:
            # Preface with a hyphen per dependency depth
            issue_key = '{}{}'.format(
                '-' * DisplayFilter._current_depth,
                dependency.target.issue_key)

        issue_string = '{:4}:{}'.format(self._current_index, str(issue_key)[:self._key_len].ljust(self._key_len))

        for column in list(self.included_columns):
            if dependency is not None and column.pretty_name == DisplayFilter.RELATIONSHIP_STRING:
                val = dependency.pretty_type()
            else:
                val = JiraUtils.retrieve_field_value(jira_manager, issue, column.name)

            # filters are include-only, so if we don't have a value but do have includes, drop it
            if filters is not None:
                # On non-matches, we don't return this row at all
                if val is None and column.name in filters:
                    return ''
                elif column in filters and val is not None and filters[column] not in val:
                    return ''

            val = '' if val is None else val
            issue_string += '| {} '.format(str(val)[:column.width].ljust(column.width))
        issue_string += os.linesep
        self._current_index += 1
        return issue_string


class ColumnFilter:

    def __init__(self, column_name, filter_string, filter_type):
        self.column_name = column_name
        self.filter_string = filter_string
        # include or exclude
        self.filter_type = filter_type


class Column:

    def __init__(self, name, pretty_name, width):
        self.name = name
        self.pretty_name = pretty_name
        self.width = width

    @property
    def is_dependency(self) -> bool:
        return self.name == 'relationship'

    def __str__(self):
        return self.name
