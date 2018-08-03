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
import traceback
from typing import TYPE_CHECKING

from jira import JIRAError

from src import time_utils
from src.jira_manager import JiraManager
from src.jira_utils import JiraUtils
from src.member_issues_by_status import JiraUserName, MemberIssuesByStatus
from src.team import Team
from src.team_reports import (ReportCurrentLoad, ReportFilter, ReportFixVersion, ReportMeta, ReportMomentum,
                              ReportReviewLoad, ReportTestLoad, ReportType)
from src.utils import (clear, conf_dir, get_input, is_yes, pause, pick_value,
                       print_separator, save_argus_config)

if TYPE_CHECKING:
    from typing import Dict, List, Optional


class TeamManager:

    """
    Contains data structures to link individuals to one another in a Team, link across multiple JIRA instances in a
    LinkedMember, and various functions to query out tickets on a per-team basis and generate
    reports for summation across issues
    """
    def __init__(self):
        self._teams = {}

    def prompt_for_team_addition(self, jira_manager):
        name = get_input('Name this new team:', lowered=False)

        jira_connection_name = pick_value('Which JIRA Connection owns this team?', jira_manager.possible_connections(), True, 'Cancel')
        if jira_connection_name is None:
            return
        self._teams[name] = Team(name, jira_connection_name)
        self.edit_team(jira_manager, name)

    def add_existing_team(self, new_team):
        # type: (Team) -> None
        self._teams[new_team.name] = new_team

    def list_teams(self):
        print_separator(40)
        print('Currently defined teams:')
        for team in list(self._teams.values()):
            print('{}'.format(team))
        print_separator(40)

    def pick_team(self):
        # type: () -> Optional[Team]
        team_name = pick_value('Select a team', list(self._teams.keys()), True, 'Cancel')
        if team_name is None:
            return None
        return self._teams[team_name]

    def get_team_by_name(self, team_name):
        return self._teams[team_name]

    def edit_team(self, jira_manager, team_name=None):
        # type: (JiraManager, str) -> None
        if team_name is None:
            team_name = pick_value('Edit which team?', list(self._teams.keys()), True, 'Cancel')
            if team_name is None:
                return None

        team = self._teams[team_name]
        jira_connection = jira_manager.get_jira_connection(team.jira_connection_name)

        while True:
            clear()
            print('-------------------------')
            print('[Edit {}]'.format(team))
            print('-------------------------')
            cmd = get_input('[A]dd more members, [R]emove a member, or [Q]uit?')
            if cmd == 'a':
                assignees = jira_connection.pick_assignees(sys.maxsize)
                if assignees is None or len(assignees) == 0:
                    print('No assignees chosen. Returning.')
                    return None
                for assignee in assignees:
                    if assignee in team.member_names:
                        print('Assignee already exists in {}. Skipping.'.format(team.name))
                        continue
                    else:
                        team.add_member(assignee, jira_connection)
                        print('Added {} to {}.'.format(assignee, team.name))
                        self._save_config()
            elif cmd == 'r':
                assignee = pick_value('Remove which assignee?', team.member_names, True, 'Cancel')
                if assignee is None:
                    continue
                confirm = get_input('Delete {} from {}: Are you sure?'.format(assignee, team.name))
                if confirm == 'y':
                    team.delete_member(assignee)
            elif cmd == 'q':
                break
            else:
                print('Bad input. Valid input: A, R, or Q.')
                pause()
        self._save_config()

    def remove_team(self):
        # type: () -> Optional[str]
        """
        :return: Name of team that was removed, None if none.
        """
        if len(self._teams) == 0:
            print('No teams currently defined.')
            return None
        to_remove = pick_value('Remove which team?', list(self._teams.keys()), True, 'Cancel')
        if to_remove is None:
            return None
        if is_yes('Are you sure you want to delete {}?'.format(to_remove)):
            del self._teams[to_remove]
            self._save_config()
            return to_remove
        return None

    def create_new_member_alias(self, jira_manager):
        # type: (JiraManager) -> None
        """
        This linkage is performed on the logical 'Team' level rather than per JiraConnection.
        """
        if len(self._teams) == 0:
            print('Must first add a team before adding a linked member.')
            return

        count = 0
        for team in list(self._teams.values()):
            count += len(team.members)
        if count == 0:
            print('No members found on any teams. Add members before attempting to link members.')
            return

        # The linkage allows addition of >= 1 linked JiraUserName to whatever root member we want to add to.
        target_member = self._pick_member_for_linkage_operation('Add')

        changed = False
        while True:
            print('Current state of user: {}'.format(target_member))
            jira_connection_to_alias = jira_manager.pick_jira_connection('Alias to a user account on which JIRA connection?')
            if jira_connection_to_alias is None:
                break

            # We have our target jira username at this point.
            user_to_alias_to = jira_connection_to_alias.pick_single_assignee()
            if user_to_alias_to is None:
                break

            new_user_alias = JiraUserName(user_to_alias_to, jira_connection_to_alias.connection_name, 'alias')
            target_member.add_alias(new_user_alias)
            changed = True

            if not is_yes('Add another alias?'):
                break
        if changed:
            self._save_config()

    def _pick_member_for_linkage_operation(self, action):
        # type: (str) -> Optional[MemberIssuesByStatus]
        """
        Prompts for both team to remove from and then member. Used on both addition and deletion paths.
        """
        target_team_name = pick_value('{} a linked member on which team?'.format(action), list(self._teams.keys()))
        if target_team_name is None:
            return None
        target_team = self._teams[target_team_name]
        print_separator(40)
        print('Detailed status of team members:')
        for member in target_team.members:
            print('   {}'.format(member))
        print_separator(40)
        target_member_name = pick_value('{} a linked JIRA user-name on which member?'.format(action), target_team.member_names)
        if target_member_name is None:
            return None
        return target_team.get_member(target_member_name)

    def remove_linked_member(self):
        target_member = self._pick_member_for_linkage_operation('Remove')
        if target_member is None:
            return
        if target_member.remove_alias():
            self._save_config()

    def run_team_reports(self, jira_manager):
        """
        Sub-menu driven method to run some specific reports of interest against teams. This will take into account
        linked members and run the report for all tickets across multiple JIRA connections.
        """
        selected_team = None

        if len(self._teams) == 0:
            # We don't prompt for addition now since we'd have to pass in main menu context to do that from here.
            print('No teams found. Please use the Team Management menu to define a new team before running a report.')
            pause()
            return

        reports = {
            ReportType.MOMENTUM: ReportMomentum(),
            ReportType.CURRENT_LOAD: ReportCurrentLoad(),
            ReportType.TEST_LOAD: ReportTestLoad(),
            ReportType.REVIEW_LOAD: ReportReviewLoad(),
            ReportType.FIXVERSION: ReportFixVersion(),
            ReportType.META: ReportMeta()
        }

        while True:
            clear()
            if selected_team is None:
                selected_team = self.pick_team()
                # None return from pick_team == cancel
                if selected_team is None:
                    return
                TeamManager.populate_owned_jira_issues(jira_manager, selected_team.members)

            print('---------------------')
            print('-    Team Menu      -')
            print('---------------------')
            print('t: Change active root team. Current: {}'.format(selected_team.name))
            print('{}: Run a momentum report: closed tickets, closed test tickets, closed reviews for a custom time frame'.format(ReportType.MOMENTUM))
            print('{}: Team load report: assigned bugs, assigned tests, assigned features, assigned reviews, patch available reviews'.format(ReportType.CURRENT_LOAD))
            print('{}: Test load report: snapshot of currently assigned tests and closed tests in a custom time frame'.format(ReportType.TEST_LOAD))
            print('{}: Review load report: snapshot of currently assigned reviews, Patch Available reviews, and finished reviews in a custom time frame'.format(ReportType.REVIEW_LOAD))
            print('{}: FixVersion report: show data for all tickets on a fixversion over time frame'.format(ReportType.FIXVERSION))
            print('{}: Meta report: show data for meta workload for a team'.format(ReportType.META))
            print('q: Cancel')
            print('---------------------')
            choice = get_input(':')
            if choice == 'q':
                return
            elif choice == 't':
                selected_team = None
            try:
                report_type = ReportType.from_int(int(choice))
                if report_type == ReportType.UNKNOWN:
                    print('Bad input: {}. Try again.'.format(choice))
                    pause()
                else:
                    TeamManager._run_report(jira_manager, selected_team, reports[report_type])
            except (ValueError, TypeError) as e:
                print('Error on input: {}. Try again'.format(e))
                traceback.print_exc()
                pause()

    @staticmethod
    def populate_owned_jira_issues(jira_manager, team_members):
        # type: (JiraManager, List[MemberIssuesByStatus]) -> None
        related_jira_connections = set()
        # clear out any cached data on this team and build a set of JiraConnections we want to add tickets from
        for member in team_members:
            member.clear()
            related_jira_connections.update(member.connection_names)

        count_added = 0
        print('Adding tickets to members. Please wait...')
        # On each connection that this team is related to, we add all owned issues to this team member
        # For every JiraIssue per JiraProject per JiraConnection, find all the members that are "owners' and link the
        # JiraIssue to that MemberIssuesByStatus
        for jira_connection_name in related_jira_connections:
            jira_connection = jira_manager.get_jira_connection(jira_connection_name)
            cached_issue_lists = jira_connection.cached_jira_issues
            for list_of_issues in cached_issue_lists:
                for jira_issue in list_of_issues:
                    for member in team_members:
                        # Can't short-circuit here since one member may be assignee and another reviewer
                        if member.add_if_owns(jira_connection, jira_issue):
                            count_added += 1

        print('Sorting tickets by key. Please wait...')
        for member in team_members:
            member.sort_tickets()

    @staticmethod
    def _run_report(jira_manager: JiraManager, team: Team, report_filter: ReportFilter) -> None:
        # We prompt for a new 'since' on each iteration of the loop
        if report_filter.needs_duration:
            report_filter.since = time_utils.since_now(ReportFilter.get_since())

        report_filter.prompt_for_data()

        try:
            sorted_member_issues = sorted(team.members, key=lambda s: s.primary_name.user_name)

            while True:
                # Print out a menu of the meta information for each team member
                print_separator(40)
                report_filter.print_description()
                print_separator(40)
                print('[{}]'.format(report_filter.header))
                print(report_filter.column_headers())

                count = 1

                for member_issues in sorted_member_issues:
                    report_filter.clear()
                    # We perform pre-processing and one-off prompting for time duration in .process call
                    report_filter.process_issues(member_issues)
                    print('{:5}: {}'.format(count, report_filter.print_all_counts(member_issues.primary_name.user_name)))
                    count += 1

                print_separator(40)
                cmd = get_input('[#] Integer value to see a detailed breakdown by category. [q] to return to menu:')
                if cmd == 'q':
                    break

                # Received detailed breakdown input
                try:
                    c_input = int(cmd) - 1

                    # Pull out the MemberIssuesByStatus object for the chosen member for detailed printing
                    # We need to re-populate this report filter with this user for matching logic to work
                    full_member_issues = sorted_member_issues[c_input]
                    report_filter.clear()
                    report_filter.process_issues(full_member_issues)
                    displayed_issues = full_member_issues.display_member_issues(jira_manager, report_filter)

                    while True:
                        if len(displayed_issues) == 0:
                            print('No issues found matching category.')
                            pause()
                            break
                        cmd = get_input('[#] Integer value to open JIRA issue in browser. [q] to return to report results:')
                        if cmd == 'q':
                            break
                        try:
                            jira_issue = displayed_issues[int(cmd) - 1]
                            jira_connection = jira_manager.get_jira_connection(jira_issue.jira_connection_name)
                            JiraUtils.open_issue_in_browser(jira_connection.url, jira_issue.issue_key)
                        except ValueError as ve:
                            print('Bad input. Try again.')
                            print('ValueError : {}'.format(ve))
                            pause()
                except ValueError:
                    break
        except JIRAError as je:
            print('Caught a JIRAError attempting to run a query: {}'.format(je))
            pause()

    @classmethod
    def from_file(cls):
        config_parser = configparser.RawConfigParser()
        try:
            result = TeamManager()

            if not os.path.exists(os.path.join(conf_dir, 'teams.cfg')):
                return result

            config_parser.read(os.path.join(conf_dir, 'teams.cfg'))

            # Add teams
            if not config_parser.has_section('manager'):
                return result
            team_roots = config_parser.get('manager', 'team_names').split(',')
            for team_root in team_roots:
                # Skip trailing ,
                if team_root == '':
                    continue
                name, jira_connection_name = team_root.split(':')
                result._teams[name] = Team(name, jira_connection_name)

            # Add MemberIssuesByStatus
            for member_root_name in config_parser.sections():
                if member_root_name == 'manager':
                    continue
                new_member = MemberIssuesByStatus.from_file(member_root_name, config_parser)
                team = result.get_team_by_name(new_member.primary_team)
                if team is None:
                    raise ValueError('Failed to find a constructed team with name: {}'.format(new_member.primary_team))
                team.add_existing_member(new_member)

            return result
        except (AttributeError, ValueError, IOError) as e:
            print('Exception during creation of TeamManager. Config file name: {}. Exception stack follows:'.format(os.path.join(conf_dir, 'teams.cfg')))
            traceback.print_exc()
            raise e

    def _save_config(self):
        config_parser = configparser.RawConfigParser()
        # Save team names comma delim
        config_parser.add_section('manager')

        # Root names are name:jira_conn_name
        # Need to append a comma if we only have 1, else it'll treat it as an array of char instead of array of str on read
        root_names = ','.join([x.root_name for x in list(self._teams.values())])
        if len(list(self._teams.values())) == 1:
            root_names = root_names + ','
        print('Saving root names as: {}'.format(root_names))
        config_parser.set('manager', 'team_names', root_names)

        for team in list(self._teams.values()):
            for member in team.members:
                member.save_config(config_parser)

        config_path = os.path.join(conf_dir, 'teams.cfg')
        save_argus_config(config_parser, config_path)
