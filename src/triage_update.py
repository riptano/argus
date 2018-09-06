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

import sys
import time
import traceback

from typing import Dict, List, Optional

from src.jira_connection import JiraConnection
from src.jira_project import JiraProject
from src.jira_issue import JiraIssue
from src.utils import time_format_string


class TriageUpdate:

    """
    Logic to update data for input CSV data for JIRA issues and output same format w/updated field values
    """

    def __init__(self, jira_connections: Dict[str, JiraConnection], jira_projects: Dict[str, JiraProject]) -> None:
        self._jira_connections = jira_connections
        self._jira_projects = jira_projects

        # TriageIssues
        self._open_issues: List[TriageIssue] = []
        self._closed_issues: List[TriageIssue] = []

    def process(self, in_file_name: str, out_file_name: str = None) -> None:
        # Update jira projects before querying
        for name, jp in self._jira_projects.items():
            jp.refresh()

        with open(in_file_name, 'r') as issue_file:
            temp_issues = []
            # First, get the .csv data into TriageIssue objects to be updated
            for line in issue_file:
                if 'Last argus cleaning' in line or 'Open Issues' in line:
                    continue
                line = line.rstrip()
                ti = TriageIssue(line)
                # Skip header or empty rows
                if ti.key == '' or ti.key == 'Key':
                    continue
                temp_issues.append(ti)

            # Parse out project name and link to JiraConnection, so we can use the connection_name to build a
            # complex name and map to an offline cached JiraProject.
            missed = False
            for triage_issue in temp_issues:
                found = False
                for name, conn in self._jira_connections.items():
                    if conn.contains_project(triage_issue.project):
                        found = True
                        triage_issue.set_connection_name(conn.connection_name)
                        try:
                            jira_project = self._jira_projects[triage_issue.project]

                            # Grab the data from the offline cached results and update our TriageIssue with it
                            jira_issue = jira_project.get_issue(triage_issue.key)
                            if jira_issue is None:
                                print('WARNING! Got null JiraIssue for key: [{}]. Skipping.'.format(triage_issue.key))
                                continue

                            # Update the contents of the triage issue before adding it to one of our result sets
                            triage_issue.update_self(jira_issue, jira_project)

                            # we can now determine if this is an open or closed issue
                            if jira_issue.is_open:
                                self._open_issues.append(triage_issue)
                            else:
                                self._closed_issues.append(triage_issue)
                            break
                        except ValueError as e:
                            print('---------------------------------------')
                            print('Encountered exception on issue: {}. Exception: {}'.format(triage_issue, e))
                            traceback.print_exc()
                            print('It\'s possible you haven\'t cached a jira project locally for issue: {}'.format(triage_issue))
                            for name, jira_project in self._jira_projects.items():
                                print('Known jira projects cached locally: {}'.format(name))
                            print('---------------------------------------')
                if not found:
                    print('Failed to find any Jira Connection that owned the issue: {}. Will not update.'.format(triage_issue.key))
                    print('Attempted to find project name: [{}]'.format(triage_issue.project))
                    print('Enumerating known projects:')
                    for name, conn in self._jira_connections.items():
                        print('conn name: {}'.format(name))
                        print('known projects: {}'.format(','.join(conn.possible_projects)))
                        print('result of whether this conn knows that project: {}'.format(conn.contains_project(triage_issue.project)))
                    missed = True
            if missed:
                print('Use the projects menu in the interface to locally cache data from that project in order to run triage.')

        # Sort by: component, prio, repro reverse, scope reverse
        # Reverse order since multi w/order aren't supported
        TriageUpdate.sort_triaged_issues(self._open_issues)
        TriageUpdate.sort_triaged_issues(self._closed_issues)

        if out_file_name is not None:
            with open(out_file_name, 'w') as out_file:
                self._print_csv(out_file)
        else:
            self._print_csv(sys.stdout)
        exit(0)

    def _print_csv(self, out_handle) -> None:
        count = 0
        out_handle.write('Last updated w/Argus,{},,Master Link:,{}\n'.format(
            time.strftime(time_format_string()), '=HYPERLINK(CONCATENATE(if(regexmatch(B4, $O$3), $P$3, $R$3), B4),"Link")'))
        out_handle.write('Open Issues\n')
        out_handle.write(',Key,Summary,assignee,reviewer,status,resolution,Prio,Repro,Scope,Type,Component,,\n')
        for triage_issue in self._open_issues:
            try:
                out_handle.write('{}\n'.format(triage_issue))
                count += 1
            except (ValueError, TypeError) as e:
                print('Failed to output line. issue key with problem field: {}. Exception: {}'.format(triage_issue.key, e))
        out_handle.write('\n')
        out_handle.write('Closed Issues\n')
        for triage_issue in self._closed_issues:
            out_handle.write('{}\n'.format(triage_issue))
            count += 1
        print('Wrote {} issues to {}'.format(count, out_handle))

    @staticmethod
    def sort_triaged_issues(triaged_issues: List['TriageIssue']) -> None:
        # Oh glorious hack. Set component to Z if prio is N so component sort will put it at the end.
        for i in triaged_issues:
            if i.prio == 'N':
                i.set_component('ZZZ')

        triaged_issues.sort(key=lambda x: x.scope, reverse=True)
        triaged_issues.sort(key=lambda x: x.repro, reverse=True)
        triaged_issues.sort(key=lambda x: x.prio, reverse=False)
        triaged_issues.sort(key=lambda x: x.component, reverse=False)


class TriageIssue:

    """
    A TriageIssue differs from a JiraIssue in terms of the source of the data. We expect this to come from an export
    of our combined google doc sheet we use to triage in lieu of replicating every external ticket we might want to work
    on into our private JIRA. TriageIssues contain index offsets, logic to initialize from a comma-delimited line, some
    logic to take data from a JiraIssue and glob it in, and output logic.
    """
    # Correspond to location in spreadsheet
    key_index = 1
    summary_index = 2
    assignee_index = 3
    reviewer_index = 4
    status_index = 5
    resolution_index = 6
    prio_index = 7
    repro_index = 8
    scope_index = 9
    type_index = 10
    component_index = 11

    def __init__(self, line: str) -> None:
        """
        When we init from .csv, we assume we don't need to sanitize each field. Mostly because we *can't* init from
        .csv if we have , in the middle of fields... since it wouldn't be csv.
        """
        sa = line.split(',')
        self._jira_project = None  # type: Optional[JiraProject]
        self._connection_name = ''  # type: str
        self._data = sa  # type: List[str]
        # Strip out , and " from strings
        for i in range(0, len(self._data) - 1):
            self._data[i] = self._data[i].replace(',', ';').replace('"', '')

    @property
    def key(self) -> str:
        return self._data[1]

    @property
    def project(self) -> str:
        """
        Returns string representation consisting of the first half of the PROJECT-#### JIRA key
        """
        return self._data[1].split('-')[0]

    @property
    def scope(self) -> str:
        return self._data[self.scope_index]

    @property
    def prio(self) -> str:
        return self._data[self.prio_index]

    @property
    def repro(self) -> str:
        return self._data[self.repro_index]

    @property
    def component(self) -> str:
        return self._data[self.component_index]

    def set_component(self, new_value):
        self._data[self.component_index] = new_value

    @staticmethod
    def validate(field: Optional[str]) -> str:
        if field is None:
            return 'UNKNOWN'
        return field

    def update_self(self, jira_issue: JiraIssue, jira_project: JiraProject) -> None:
        assert jira_issue is not None, 'Got null JiraIssue in update_self. Aborting.'
        self._jira_project = jira_project

        self._data[self.assignee_index] = TriageIssue.sanitize(self.validate(jira_issue.assignee))

        # Custom handling for reviewer
        self._data[self.reviewer_index] = TriageIssue.sanitize(self._get_reviewer(jira_issue))
        self._data[self.status_index] = TriageIssue.sanitize(self.validate(jira_issue.status))
        self._data[self.resolution_index] = TriageIssue.sanitize(self.validate(jira_issue.resolution))
        self._data[self.type_index] = self.validate(jira_issue.issuetype)
        self._data[self.prio_index] = self.validate(jira_issue.priority)

        combined = set()
        # Assume raw text string for component comes from .csv
        if self.component != '':
            combined.add(self.component)

        # Component from JiraIssue is in the form of a JiraComponent object.
        for component in jira_issue.component_list:
            combined.add(component)
        self._data[self.component_index] = ':'.join(combined)

    def _get_reviewer(self, jira_issue: JiraIssue) -> str:
        if self.reviewer_field in jira_issue:
            return jira_issue[self.reviewer_field]
        return 'unassigned'

    @staticmethod
    def sanitize(field: str) -> str:
        """
        Strips out , and "" from input, leaving behind something somewhat safer for csv processing
        :param field: str
        :return: str
        """
        if field is None:
            return ''
        return field.replace(',', ' ').replace('"', '')

    @property
    def reviewer_field(self) -> str:
        assert self._jira_project is not None
        return self._jira_project.translate_custom_field('reviewer')

    @property
    def reviewer_two_field(self) -> str:
        assert self._jira_project is not None
        return self._jira_project.translate_custom_field('reviewer2')

    def set_connection_name(self, conn_name: str) -> None:
        self._connection_name = conn_name

    @property
    def short_string(self) -> str:
        return 'key: {} status: {} resolution: {} assignee: {} reviewer: {}'.format(
            self.key, self._data[self.status_index], self._data[self.resolution_index], self._data[self.assignee_index], self._data[self.reviewer_index])

    def raw_data(self) -> List[str]:
        return self._data

    def __str__(self) -> str:
        # Handle link first
        result = 'OVERWRITEME,'

        try:
            for i in range(1, len(self._data) - 2):
                result += '{},'.format(self._data[i])
            result += '{}'.format(self._data[len(self._data) - 1])
            return result
        except (ValueError, TypeError) as e:
            print('Failed to encode issue as string. key with issue: {}. Exception: {}'.format(self.key, e))
            return 'UNKNOWN - FAILURE: {}'.format(self.key)
