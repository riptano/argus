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
from typing import TYPE_CHECKING


from src.utils import time_format_string

if TYPE_CHECKING:
    from src.jira_connection import JiraConnection
    from src.jira_project import JiraProject
    from src.jira_issue import JiraIssue
    from typing import Dict, List


class TriageUpdate:

    """
    Logic to update data for input CSV data for JIRA issues and output same format w/updated field values
    """

    def __init__(self, jira_connections, jira_projects):
        # type: (Dict[str, JiraConnection], Dict[str, JiraProject]) -> None
        """
        :param jira_connections: {str connection name -> JiraConnection}
        :param jira_projects: {str complex names -> JiraProject}
        """
        self._jira_connections = jira_connections
        self._jira_projects = jira_projects

        # TriageIssues
        self._open_issues = []      # type: List[TriageIssue]
        self._closed_issues = []    # type: List[TriageIssue]

    def process(self, in_file_name, out_file_name=None):
        # Update jira projects before querying
        for name, jp in self._jira_projects.items():
            jp.refresh()

        with open(in_file_name, 'r') as issue_file:
            temp_issues = []
            # First, get the .csv data into TriageIssue objects to be updated
            for line in issue_file:
                line = line.rstrip()
                ti = TriageIssue(line)
                # Skip header or empty rows
                if ti.key() == '' or ti.key() == 'Key':
                    continue
                temp_issues.append(ti)

            # Parse out project name and link to JiraConnection, so we can use the connection_name to build a
            # complex name and map to an offline cached JiraProject.
            missed = False
            for triage_issue in temp_issues:
                found = False
                for name, conn in self._jira_connections.items():
                    if conn.contains_project(triage_issue.project()):
                        found = True
                        triage_issue.set_connection_name(conn.connection_name)
                        try:
                            jira_project = self._jira_projects[triage_issue.complex_name()]

                            # Grab the data from the offline cached results and update our TriageIssue with it
                            jira_issue = jira_project.get_issue(triage_issue.key())

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
                    print('Failed to find any Jira Connection that owned the issue: {}. Will not update.'.format(triage_issue.key()))
                    print('Attempted to find project name: [{}]'.format(triage_issue.project()))
                    print('Enumerating known projects:')
                    for name, conn in self._jira_connections.items():
                        print('conn name: {}'.format(name))
                        print('known projects: {}'.format(','.join(conn.possible_projects)))
                        print('result of whether this conn knows that project: {}'.format(conn.contains_project(triage_issue.project())))
                    missed = True
            if missed:
                print('Use the projects menu in the gui to locally cache data from that project in order to run triage.')

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

    def _print_csv(self, out_handle):
        count = 0
        out_handle.write('Last updated w/Argus,{},,Master Link:,{}\n'.format(
            time.strftime(time_format_string()), '=HYPERLINK(CONCATENATE(if(regexmatch(B4, $O$3), $P$3, $R$3), B4),"Link")'))
        out_handle.write('Open Issues\n')
        out_handle.write(',Key,Summary,assignee,reviewer,status,resolution,Prio,Repro,Scope,Type,Component,,\n')
        for i in self._open_issues:
            try:
                out_handle.write('{}\n'.format(i).encode('utf-8'))
                count += 1
            except (ValueError, TypeError) as e:
                print('Failed to output line. issue key with problem field: {}. Exception: {}'.format(i.key(), e))
        out_handle.write('\n')
        out_handle.write('Closed Issues\n')
        for i in self._closed_issues:
            out_handle.write('{}\n'.format(i).encode('utf-8'))
            count += 1
        print('Wrote {} issues to {}'.format(count, out_handle))

    @staticmethod
    def sort_triaged_issues(triaged_issues):
        """
        :param triaged_issues: [] of TriageIssue objects
        :return: None. Sorts in place.
        """
        # Oh glorious hack. Set component to Z if prio is N so component sort will put it at the end.
        for i in triaged_issues:
            if i.prio() == 'N':
                i.set_component('ZZZ')

        triaged_issues.sort(key=lambda x: x.scope(), reverse=True)
        triaged_issues.sort(key=lambda x: x.repro(), reverse=True)
        triaged_issues.sort(key=lambda x: x.prio(), reverse=False)
        triaged_issues.sort(key=lambda x: x.component(), reverse=False)


class TriageIssue:

    """
    A TriageIssue differs from a JiraIssue in terms of the source of the data. We expect this to come from an export
    of our combined google doc sheet we use to triage in lieu of replicating every OSS C* ticket we might want to work
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

    def __init__(self, line):
        """
        When we init from .csv, we assume we don't need to sanitize each field. Mostly because we *can't* init from
        .csv if we have , in the middle of fields... since it wouldn't be csv.
        """
        sa = line.split(',')
        self._jira_project = None
        self._data = sa
        # Strip out , and " from strings
        for i in range(0, len(self._data) - 1):
            self._data[i] = self._data[i].replace(',', ';').replace('"', '')

    def key(self):
        return self._data[1]

    def project(self):
        """
        Returns string representation consisting of the first half of the PROJECT-#### JIRA key
        :return:
        """
        return self._data[1].split('-')[0]

    def scope(self):
        return self._data[self.scope_index]

    def prio(self):
        return self._data[self.prio_index]

    def repro(self):
        return self._data[self.repro_index]

    def component(self):
        return self._data[self.component_index]

    def set_component(self, new_value):
        self._data[self.component_index] = new_value

    def update_self(self, jira_issue, jira_project):
        # type: (JiraIssue, JiraProject) -> None
        self._jira_project = jira_project

        self._data[self.assignee_index] = self._sanitize(jira_issue['assignee'])

        # Custom handling for reviewer
        self._data[self.reviewer_index] = self._sanitize(jira_issue[self.reviewer_field()])

        self._data[self.status_index] = self._sanitize(jira_issue['status'])
        self._data[self.resolution_index] = self._sanitize(jira_issue['resolution'])

        self._data[self.type_index] = jira_issue['issuetype']

        self._data[self.prio_index] = jira_issue['priority']

        combined = set()
        # Assume raw text string for component comes from .csv
        if self.component() != '':
            combined.add(self.component())

        # Component from JiraIssue is in the form of a JiraComponent object.
        for component in jira_issue.component_list():
            combined.add(component)
        self._data[self.component_index] = ':'.join(combined)

    @staticmethod
    def _sanitize(field):
        """
        Strips out , and "" from input, leaving behind something somewhat safer for csv processing
        :param field: str
        :return: str
        """
        return field.replace(',', ' ').replace('"', '')

    def reviewer_field(self):
        return self._jira_project.translate_custom_field('reviewer')

    def reviewer_two_field(self):
        return self._jira_project.translate_custom_field('reviewer2')

    def set_connection_name(self, conn_name):
        self._connection_name = conn_name

    # NOTE: Coupled with complex_name in JiraProject object
    def complex_name(self):
        return '{}_{}'.format(self._connection_name, self.project())

    def short_string(self):
        return 'key: {} status: {} resolution: {} assignee: {} reviewer: {}'.format(
            self.key(), self._data[self.status_index], self._data[self.resolution_index], self._data[self.assignee_index], self._data[self.reviewer_index])

    def raw_data(self):
        return self._data

    def __str__(self):
        # Handle link first
        result = 'OVERWRITEME,'

        try:
            for i in range(1, len(self._data) - 2):
                result += '{},'.format(self._data[i])
            result += '{}'.format(self._data[len(self._data) - 1])
            return result
        except (ValueError, TypeError) as e:
            print('Failed to encode issue as string. key with issue: {}. Exception: {}'.format(self.key(), e))
