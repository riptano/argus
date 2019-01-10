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
from typing import TYPE_CHECKING, Dict, List, Optional, Set

from jira import JIRAError

from src import time_utils
from src.jira_utils import JiraUtils
from src.member_issues_by_status import JiraUserName, MemberIssuesByStatus
from src.team import Team
from src.team_reports import (InProgressReport, ReportCurrentLoad, ReportFilter, ReportFixVersion, ReportMeta,
                              ReportMomentum, ReportReviewLoad, ReportTestLoad, ReportType)
from src.utils import (as_int, build_separator, clear, conf_dir, get_input, is_yes, pause, pick_value,
                       print_separator, save_argus_config, argus_debug)

if TYPE_CHECKING:
    from src.jira_manager import JiraManager


class TeamManager:

    """
    Contains data structures to link individuals to one another in a Team, link across multiple JIRA instances in a
    LinkedMember, and various functions to query out tickets on a per-team basis and generate
    reports for summation across issues
    """
    reports = {
        ReportType.MOMENTUM: ReportMomentum(),
        ReportType.CURRENT_LOAD: ReportCurrentLoad(),
        ReportType.TEST_LOAD: ReportTestLoad(),
        ReportType.REVIEW_LOAD: ReportReviewLoad(),
        ReportType.FIXVERSION: ReportFixVersion(),
        ReportType.META: ReportMeta(),
        ReportType.IN_PROGRESS: InProgressReport()
    }

    def __init__(self) -> None:
        self._teams = {}  # type: Dict[str, Team]
        self._organizations = {}  # type: Dict[str, Set[str]]

    def prompt_for_team_addition(self, jira_manager: 'JiraManager') -> None:
        name = get_input('Name this new team:', lowered=False)

        jira_connection_name = pick_value('Which JIRA Connection owns this team?', jira_manager.possible_connections(), True, 'Cancel')
        if jira_connection_name is None:
            return
        self._teams[name] = Team(name, jira_connection_name)
        self.edit_team(jira_manager, name)

    def add_existing_team(self, new_team: Team) -> None:
        self._teams[new_team.name] = new_team

    def add_organization(self) -> None:
        while True:
            if len(self._organizations.keys()) != 0:
                print('Known organizations:')
            for known_org in self._organizations.keys():
                print('   {}'.format(known_org))
            org_name = get_input('Enter a new org name, [q] to quit:', False)
            if org_name == 'q':
                break
            new_org = set()  # type: Set[str]
            while True:
                clear()
                print('Org: {}'.format(org_name))
                for team_name in new_org:
                    print('   {}'.format(team_name))
                choice = get_input('[a]dd a new team to this org, [q]uit')
                if choice == 'q':
                    break
                elif choice == 'a':
                    new_team = self.pick_team(list(new_org))
                    if new_team is not None:
                        new_org.add(new_team.name)
                else:
                    print('Bad choice. Try again.')
                    pause()
            if new_org is not None:
                self._organizations[org_name] = new_org
                self._save_config()
                print('New org {} added.'.format(org_name))
                break

    def remove_organization(self) -> None:
        selection = pick_value('Remove which organization?', list(self._organizations.keys()))
        if selection is None:
            return
        del self._organizations[selection]
        self._save_config()

    def list_teams(self) -> None:
        print_separator(40)
        print('Currently defined teams:')
        for team in list(self._teams.values()):
            print('{}'.format(team))
        print_separator(40)

    def pick_team(self, skip_list: Optional[List[str]] = None) -> Optional[Team]:
        if skip_list is None:
            valid_names = list(self._teams.keys())
        else:
            valid_names = [x for x in self._teams.keys() if x not in skip_list]
        team_name = pick_value('Select a team', valid_names, True, 'Cancel')
        if team_name is None:
            return None
        return self._teams[team_name]

    def get_team_by_name(self, team_name: str) -> Team:
        return self._teams[team_name]

    def edit_team(self, jira_manager: 'JiraManager', team_name: str = None) -> None:
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
                to_delete = pick_value('Remove which assignee?', team.member_names, True, 'Cancel')
                if to_delete is None:
                    continue
                confirm = get_input('Delete {} from {}: Are you sure?'.format(to_delete, team.name))
                if confirm == 'y':
                    team.delete_member(to_delete)
            elif cmd == 'q':
                break
            else:
                print('Bad input. Valid input: A, R, or Q.')
                pause()
        self._save_config()

    def remove_team(self) -> Optional[str]:
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

    def create_new_member_alias(self, jira_manager: 'JiraManager') -> None:
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
        if target_member is None:
            return

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

    def _pick_member_for_linkage_operation(self, action: str) -> Optional[MemberIssuesByStatus]:
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
        return target_team.get_member_issues(target_member_name)

    def remove_linked_member(self) -> None:
        target_member = self._pick_member_for_linkage_operation('Remove')
        if target_member is None:
            return
        if target_member.remove_alias():
            self._save_config()

    def run_org_report(self, jira_manager: 'JiraManager') -> None:
        """
        Sub-menu driven method to run a specific type of report across multiple teams within an organization
        """
        org_name = None

        if len(self._organizations) == 0:
            # We don't prompt for addition now since we'd have to pass in main menu context to do that from here.
            print('No organizations found. Please use the Team Management menu to define a new organization before running a report.')
            pause()
            return

        while True:
            clear()
            if org_name is None:
                print_separator(40)
                org_name = pick_value('Run reports against which organization?', list(self._organizations.keys()))
                # None return from pick_team == cancel
                if org_name is None:
                    return
                for team_name in sorted(self._organizations[org_name]):
                    active_team = self._teams[team_name]
                    print('Populating tickets for team: {}'.format(active_team.name))
                    TeamManager.populate_owned_jira_issues(jira_manager, active_team.members)

            print('---------------------')
            print('-    Org Menu      -')
            print('---------------------')
            print('t: Change active org. Current: {}'.format(org_name))
            self._print_report_menu()
            print('q: Cancel')
            print('---------------------')
            choice = get_input(':')
            if choice == 'q':
                return
            elif choice == 't':
                org_name = None
            try:
                report_type = ReportType.from_int(int(choice))
                if report_type == ReportType.UNKNOWN:
                    print('Bad input: {}. Try again.'.format(choice))
                    pause()
                else:
                    report_to_run = TeamManager.reports[report_type]
                    if TeamManager.reports[report_type].needs_duration:
                        report_to_run.since = time_utils.since_now(ReportFilter.get_since())
                    # making mypy happy
                    assert org_name is not None
                    self._run_org_report(jira_manager, org_name, report_to_run)
                    pause()
            except (ValueError, TypeError) as e:
                print('Error on input: {}. Try again'.format(e))
                traceback.print_exc()
                pause()

    def run_team_reports(self, jira_manager: 'JiraManager') -> None:
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

        while True:
            clear()
            if selected_team is None:
                print('No active team. Please select a team:')
                selected_team = self.pick_team()
                # None return from pick_team == cancel
                if selected_team is None:
                    return
                TeamManager.populate_owned_jira_issues(jira_manager, selected_team.members)

            print('---------------------')
            print('-    Team Menu      -')
            print('---------------------')
            print('t: Change active root team. Current: {}'.format(selected_team.name))
            self._print_report_menu()
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
                    assert selected_team is not None
                    TeamManager._run_team_report(jira_manager, selected_team, TeamManager.reports[report_type])
            except (ValueError, TypeError) as e:
                print('Error on input: {}. Try again'.format(e))
                traceback.print_exc()
                pause()

    @staticmethod
    def _print_report_menu() -> None:
        print('{}: Run a momentum report: closed tickets, closed test tickets, closed reviews for a custom time frame'.format(ReportType.MOMENTUM))
        print('{}: Team load report: assigned bugs, assigned tests, assigned features, assigned reviews, patch available reviews'.format(ReportType.CURRENT_LOAD))
        print('{}: Test load report: snapshot of currently assigned tests and closed tests in a custom time frame'.format(ReportType.TEST_LOAD))
        print('{}: Review load report: snapshot of currently assigned reviews, Patch Available reviews, and finished reviews in a custom time frame'.format(ReportType.REVIEW_LOAD))
        print('{}: FixVersion report: show data for all tickets on a fixversion over time frame'.format(ReportType.FIXVERSION))
        print('{}: Meta report: show data for meta workload for a team'.format(ReportType.META))
        print('{}: In Progress report: show all open tickets marked "In Progress" for each user'.format(ReportType.IN_PROGRESS))

    @staticmethod
    def populate_owned_jira_issues(jira_manager: 'JiraManager', team_members: List[MemberIssuesByStatus]) -> None:
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

    def _run_org_report(self, jira_manager: 'JiraManager', org_name: str, report_filter: ReportFilter) -> None:
        """
        Spins within a menu to pull up details on individuals.
        """
        while True:
            # Print out a menu of the meta information for this report
            print_separator(40)
            report_filter.print_description()
            print_separator(40)
            print('Report for org: {}'.format(org_name))
            print('[{}]'.format(report_filter.header))

            count = 1
            # Store displayed order at top level, sorted on per-team basis
            meta_sorted_issues = []
            with open('last_report.txt', 'w') as fh:
                for team_name in self._organizations[org_name]:
                    fh.write('{}{}'.format(build_separator(30), os.linesep))
                    fh.write('[Team: {}]{}'.format(team_name, os.linesep))
                    fh.write('{}{}'.format(report_filter.column_headers(), os.linesep))

                    team_members = self._teams[team_name].members
                    sorted_members = sorted(team_members, key=lambda s: s.primary_name.user_name)
                    meta_sorted_issues.extend(sorted_members)

                    # Display in sorted order per team.
                    for member_issues in sorted_members:
                        report_filter.clear()
                        # We perform pre-processing and one-off prompting for time duration in .process call
                        report_filter.process_raw_issues(member_issues)
                        report_filter.print_main_data(count, member_issues, fh)
                        count += 1

            with open('last_report.txt', 'r') as fh:
                print(fh.read())

            selection = get_input('[#] to open details for a team member, [q] to return to previous menu')
            if selection == 'q':
                break
            int_sel = as_int(selection)
            if int_sel is None:
                continue

            # 0 indexed on List
            int_sel -= 1
            if int_sel > len(meta_sorted_issues) or int_sel < 0:
                print('Bad value.')
                continue
            tickets = meta_sorted_issues[int_sel]
            TeamManager._print_member_details(jira_manager, tickets, report_filter)

    @staticmethod
    def _run_team_report(jira_manager: 'JiraManager', team: Team, report_filter: ReportFilter) -> None:
        # We prompt for a new 'since' on each iteration of the loop in non-org reporting
        if report_filter.needs_duration:
            report_filter.since = time_utils.since_now(ReportFilter.get_since())

        report_filter.prompt_for_data()

        try:
            sorted_member_issues = sorted(team.members, key=lambda s: s.primary_name.user_name)

            while True:
                with open('last_report.txt', 'w') as fh:
                    # Print out a menu of the meta information for each team member
                    fh.write('{}{}'.format(build_separator(40), os.linesep))
                    fh.write('{}{}'.format(report_filter.description, os.linesep))
                    fh.write('{}{}'.format(build_separator(40), os.linesep))
                    fh.write('[{}]{}'.format(report_filter.header, os.linesep))
                    fh.write('{}{}'.format(report_filter.column_headers(), os.linesep))

                    count = 1

                    for member_issues in sorted_member_issues:
                        report_filter.clear()
                        # We perform pre-processing and one-off prompting for time duration in .process call
                        report_filter.process_raw_issues(member_issues)
                        report_filter.print_main_data(count, member_issues, fh)
                        count += 1

                    fh.write('{}{}'.format(build_separator(40), os.linesep))

                with open('last_report.txt', 'r') as fh:
                    print(fh.read())

                cmd = get_input('[#] Integer value to see a detailed breakdown by category. [q] to return to menu:')
                if cmd == 'q':
                    break
                selection = as_int(cmd)
                if selection is None:
                    break

                selection -= 1
                if selection < 0 or selection > len(sorted_member_issues):
                    print('Bad Selection.')
                    continue
                full_member_issues = sorted_member_issues[selection]
                TeamManager._print_member_details(jira_manager, full_member_issues, report_filter)
        except JIRAError as je:
            print('Caught a JIRAError attempting to run a query: {}'.format(je))
            pause()

    @staticmethod
    def _print_member_details(jira_manager: 'JiraManager', tickets: MemberIssuesByStatus, report_filter: ReportFilter) -> None:
        # We need to re-populate this report filter with this user for matching logic to work
        report_filter.clear()
        report_filter.process_raw_issues(tickets)
        displayed_issues = tickets.display_member_issues(jira_manager, report_filter)

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

    @classmethod
    def from_file(cls) -> 'TeamManager':
        print('Loading Team config from file')
        config_parser = configparser.RawConfigParser()
        try:
            result = TeamManager()

            if not os.path.exists(os.path.join(conf_dir, 'teams.cfg')):
                argus_debug('Did not find any existing conf/teams.cfg file. Empty TeamManager.')
                return result

            config_parser.read(os.path.join(conf_dir, 'teams.cfg'))

            # Add teams
            if config_parser.has_section('manager'):
                team_roots = config_parser.get('manager', 'team_names').split(',')
                for team_root in team_roots:
                    # Skip trailing ,
                    if team_root == '':
                        continue
                    name, jira_connection_name = team_root.split(':')
                    result._teams[name] = Team(name, jira_connection_name)
                    argus_debug('TeamManager.init: Adding team: {} from config'.format(name))

            # Add MemberIssuesByStatus
            for member_root_name in config_parser.sections():
                # TODO: Consider removing these two manualy bypasses. Kind of hacky to assume everything in config is member root.
                if member_root_name == 'manager' or member_root_name == 'organizations':
                    continue
                new_member = MemberIssuesByStatus.from_file(member_root_name, config_parser)
                team = result.get_team_by_name(new_member.primary_team)
                if team is None:
                    raise ValueError('Failed to find a constructed team with name: {}'.format(new_member.primary_team))
                team.add_existing_member(new_member)
                argus_debug('TeamManager init: Adding team member: {}'.format(new_member.full_name))

            # Init Orgs
            if config_parser.has_section('organizations'):
                for org_name in config_parser.get('organizations', 'org_names').split(','):
                    new_org = set()
                    try:
                        for team_name in config_parser.get('organizations', org_name).split(','):
                            new_org.add(team_name)
                        result._organizations[org_name] = new_org
                    except configparser.NoOptionError:
                        # Expected path if we don't have an org active. Saved as empty
                        pass

            return result
        except (AttributeError, ValueError, IOError) as e:
            print('Exception during creation of TeamManager. Config file name: {}. Exception stack follows:'.format(os.path.join(conf_dir, 'teams.cfg')))
            traceback.print_exc()
            raise e

    def _save_config(self) -> None:
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

        # [organizations] [org_names=org_1, org_2, org_3]
        # [organizations] [org=team_1, team_2, team_3]
        config_parser.add_section('organizations')
        config_parser.set('organizations', 'org_names', ','.join(list(self._organizations.keys())))
        for org in self._organizations.keys():
            config_parser.set('organizations', org, ','.join(list(self._organizations[org])))

        config_path = os.path.join(conf_dir, 'teams.cfg')
        save_argus_config(config_parser, config_path)
