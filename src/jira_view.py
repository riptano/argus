import configparser
import os
import traceback
from typing import TYPE_CHECKING, Dict, List

from jira import JIRAError

from src import utils
from src.display_filter import DisplayFilter
from src.jira_connection import JiraConnection
from src.jira_filter import JiraFilter
from src.jira_issue import JiraIssue
from src.jira_utils import JiraUtils
from src.team_manager import TeamManager
from src.utils import (ConfigError, argus_debug, get_input, pick_value,
                       print_separator, save_argus_config, jira_view_dir, pause)

if TYPE_CHECKING:
    from src.jira_manager import JiraManager
    from src.team import Team


class JiraView:

    """
    Uses locally cached JiraConnection to determine offline cached JiraProjects to search through for matching JiraIssues
    """
    # pre-populated filters
    PRE_FILTERS = sorted(['assignee', 'reviewer', 'reviewer2', 'component', 'fixVersion', 'target Release',
                          'target Branch', 'type', 'priority', 'resolution', 'labels', 'related customers',
                          'external impact', 'blocks', 'is_blocked', 'linked'])
    PRE_FILTERS = ['Project'] + PRE_FILTERS

    _known_fields = {
        'type': sorted(['Epic', 'Issue', 'Bug', 'Documentation', 'Sub-task']),
        'resolution': sorted(['Done', 'Cannot Reproduce', 'Duplicate', 'Fixed', 'Incomplete', 'Invalid',
                              'Not Planned', 'Unresolved', 'Won\'t Do', 'Won\'t Fix'])
    }

    def __init__(self, name: str, jira_connection: JiraConnection) -> None:
        self.name = name
        self.jira_connection = jira_connection

        # Collection of filters, keyed by the name of the field they filter on
        self._jira_filters = {}  # type: Dict[str, JiraFilter]

        self._teams = {}  # type: Dict[str, Team]

        self.display_filter = DisplayFilter()

    def add_single_filter(self, field: str, value: str, filter_type: str, and_or: str) -> None:
        """
        :param field: field name
        :param value: value to match against
        :param filter_type: 'i' to include, else exclude
        :param and_or: 'AND' or 'OR'
        """
        assert and_or == 'AND' or and_or == 'OR', 'Expected AND or OR to add_single_filter. Got: {}'.format(and_or)
        if field not in self._jira_filters:
            self._jira_filters[field] = JiraFilter(field, self.jira_connection, and_or)

        # Overwrite fields if it already exists.
        jira_filter = self._jira_filters[field]
        jira_filter.field = field
        if filter_type == 'i':
            jira_filter.include(value)
        else:
            jira_filter.exclude(value)

    def add_raw_filter(self, jira_filter: JiraFilter) -> None:
        self._jira_filters[jira_filter.field_name] = jira_filter

    def owned_by(self, jira_connection: JiraConnection) -> bool:
        return jira_connection == self.jira_connection

    @classmethod
    def _build_config(cls, name: str) -> str:
        return os.path.join(jira_view_dir, '{}.cfg'.format(name))

    def delete_config(self) -> None:
        td = self._build_config(self.name)
        os.remove(td)

    @classmethod
    def from_file(cls, jira_manager: 'JiraManager', config_file_name: str, team_manager: 'TeamManager') -> 'JiraView':
        """
        Throws ConfigError on error
        """
        config_file = JiraView._build_config(config_file_name)
        if not os.path.isfile(config_file):
            raise ConfigError('Failed to find jira view config file: {}'.format(config_file))

        config_parser = configparser.RawConfigParser()
        config_parser.read(config_file)

        name = config_parser.get('JiraView', 'name')
        jira_connection = jira_manager.get_jira_connection(config_parser.get('JiraView', 'jira_connection'))

        new_jira_view = JiraView(name, jira_connection)
        # Due to init order dep, we init teams empty here then fill them out separately from team_manager
        if config_parser.has_option('JiraView', 'Teams'):
            for t in config_parser.get('JiraView', 'Teams').split(','):
                new_jira_view._teams[t] = team_manager.get_team_by_name(t)

        sections = config_parser.sections()
        for section_name in sections:
            if section_name == 'JiraView':
                continue
            new_jira_filter = JiraFilter.from_file(jira_manager, section_name, config_parser)
            new_jira_view.add_raw_filter(new_jira_filter)

        return new_jira_view

    def save_config(self) -> None:
        config_parser = configparser.RawConfigParser()
        config_parser.add_section('JiraView')
        config_parser.set('JiraView', 'name', self.name)
        config_parser.set('JiraView', 'jira_connection', self.jira_connection.connection_name)
        if len(self._teams) > 0:
            config_parser.set('JiraView', 'Teams', ','.join(list(self._teams.keys())))
        for fn in list(self._jira_filters.keys()):
            self._jira_filters[fn].save_config(config_parser)

        save_argus_config(config_parser, self._build_config(self.name))

    def display_view(self, jira_manager: 'JiraManager') -> None:
        df = DisplayFilter.default()

        working_issues = list(self.get_issues().values())
        while True:
            try:
                issues = df.display_and_return_sorted_issues(jira_manager, working_issues)
                print_separator(60)
                print('[JiraView operations for {}]'.format(self.name))
                input_prompt = ("[f] to manually enter a substring to regex issues in the view\n"
                                "[c] to clear all regex filtering\n"
                                "[#] Integer value to open ticket in browser\n"
                                "[q] to quit\n"
                                ":")
                custom = get_input(input_prompt)
                if custom == 'q':
                    return
                elif custom == 'f':
                    string = get_input('substring to match:', lowered=False)
                    new_issues = []
                    for jira_issue in working_issues:
                        if jira_issue.matches(self.jira_connection, string):
                            new_issues.append(jira_issue)
                    working_issues = new_issues
                elif custom == 'c':
                    working_issues = list(self.get_issues().values())
                elif len(issues) == 0:
                    print('No matching jira issues found. Skipping attempt to open.')
                    pause()
                else:
                    try:
                        JiraUtils.open_issue_in_browser(
                            self.jira_connection.url, issues[int(custom) - 1].issue_key)
                    except ValueError:
                        print('Bad input. Try again.')
            except JIRAError as je:
                print('Caught an error: {}'.format(je))
                traceback.print_exc()
                return

    def edit_view(self, jira_manager: 'JiraManager', team_manager: TeamManager) -> None:
        print('Current view contents: {}'.format(self))

        while True:
            print_separator(40)
            print('-  JiraView Menu: {}'.format(self.name))
            print_separator(40)
            print('a: Add a filter on View')
            print('r: Remove a filter on a JiraView')
            print('t: Edit teams in View')
            print('d: Display issues matching this view.')
            print('q: Return to previous menu')
            print_separator(40)
            choice = get_input(':')
            if choice == 'q':
                return
            elif choice == 't':
                self.edit_team(team_manager)
            elif choice == 'a':
                self.add_filter()
            elif choice == 'r':
                self.remove_filter()
            elif choice == 'd':
                self.display_view(jira_manager)

    def edit_team(self, team_manager: TeamManager) -> None:
        if len(self._teams) > 0:
            print('Currently contained teams:')
            for t in list(self._teams.keys()):
                team = self._teams[t]
                print('   Name: {}'.format(team.name))
                print('      Assignees: {}'.format(','.join([str(x) for x in team.members])))

        cmd = get_input('[A]dd a team, [R]emove a team, or [Q]uit?')
        if cmd == 'q':
            return
        elif cmd == 'a':
            if 'assignee' in self._jira_filters or 'reviewer' in self._jira_filters or 'reviewer2' in self._jira_filters:
                conf = get_input('Adding a team will remove all active assignee or reviewer filters. Are you sure?')
                if conf == 'n':
                    return
                del self._jira_filters['assignee']
                del self._jira_filters['reviewer']
                del self._jira_filters['reviewer2']
            to_add = team_manager.pick_team()
            if to_add is None:
                return
            self._teams[to_add.name] = to_add
        elif cmd == 'r':
            tr = pick_value('Remove which team?', list(self._teams.keys()), True, 'Cancel')
            if tr is None:
                return
            conf = get_input('About to delete {}. Are you sure?'.format(tr))
            if conf == 'y':
                del self._teams[tr]

    def add_filter(self) -> None:
        filter_value = None
        # Adding to prevent PEP complaint.
        filter_name = None
        while filter_value is None:
            filters = JiraView.PRE_FILTERS[:]
            filters.append('Remove a filter')
            filters.append('Other')
            filter_name = pick_value('Select a field to filter on:', filters, True, 'Cancel view edit')
            if filter_name is None:
                return

            # Special logic to handle things we have known values for
            if filter_name in self._known_fields:
                filter_value = pick_value('Select {}'.format(filter_name), self._known_fields[filter_name])
            # since potential assignees vary by project, we don't store them in _known_fields
            elif filter_name == 'assignee' or filter_name == 'reviewer' or filter_name == 'reviewer2' or filter_name == 'reporter':
                # Disallow addition of assignee/reviewer/reviewer2 if a team filter is active
                if len(self._teams) > 0:
                    if filter_name != 'reporter':
                        print('Cannot add a[n] {} filter when a team filter is active. Remove team filter if you would like to add this.'.format(filter_name))
                        return
                filter_value = self.jira_connection.pick_single_assignee()
                if filter_value is None:
                    return
            elif filter_name == 'Project':
                filter_value = self.jira_connection.pick_project()
                if filter_value is None:
                    return
            elif filter_name == 'Remove a filter':
                self.remove_filter()
                return
            else:
                filter_value = get_input('{}:'.format(filter_name))

        while True:
            filter_type = get_input('[i]nclude or [e]xclude?')
            if not filter_type == 'i' and not filter_type == 'e':
                print('Try again.')
            else:
                break

        self.add_single_filter(filter_name, filter_value, filter_type, 'AND')

    def remove_filter(self) -> None:
        to_remove = pick_value('Remove value from which JiraFilter?', list(self._jira_filters.keys()))
        if to_remove is None:
            return
        self._jira_filters[to_remove].remove_filter()
        if self._jira_filters[to_remove].is_empty():
            del self._jira_filters[to_remove]
        self.save_config()

    def is_empty(self) -> bool:
        return len(self._jira_filters) == 0

    def get_issues(self, string_matches: List[str] = None) -> Dict[str, JiraIssue]:
        """
        Applies nested JiraFilters to all associated cached JiraProjects for the contained JiraConnection
        :param string_matches: substring(s) to match against JiraIssue fields for further refining of a search
        :return: {} of key -> JiraIssue that match JiraFilters and input regexes
        """

        if string_matches is None:
            string_matches = []

        source_issues = self.jira_connection.cached_jira_issues

        matching_issues = {}
        excluded_count = 0

        for issue_list in source_issues:
            for jira_issue in issue_list:
                matched = False

                has_or = False
                matched_or = False

                if utils.debug:
                    print_separator(30)
                    argus_debug('Matching against JiraIssue with key: {key}, assignee: {assignee}, rev: {rev}, rev2: {rev2}, res: {res}'.format(
                        key=jira_issue.issue_key,
                        assignee=jira_issue['assignee'],
                        rev=jira_issue.get_value(self.jira_connection, 'reviewer'),
                        rev2=jira_issue.get_value(self.jira_connection, 'reviewer2'),
                        res=jira_issue.get_value(self.jira_connection, 'resolution')
                    ))
                    for jira_filter in list(self._jira_filters.values()):
                        argus_debug('Processing filter: {}'.format(jira_filter))

                excluded = False
                argus_debug('Checking jira_filter match for issue: {}'.format(jira_issue.issue_key))
                for jira_filter in list(self._jira_filters.values()):
                    argus_debug('Processing filter: {}'.format(jira_filter))
                    # if we have an OR filter in the JiraFilter, we need to match at least one to be valid
                    if jira_filter.query_type() == 'OR':
                        has_or = True

                    if not jira_issue.matches_any(self.jira_connection, string_matches):
                        argus_debug('   Skipping {}. Didn\'t match regexes: {}'.format(
                            jira_filter.extract_value(jira_issue), ','.join(string_matches)))
                        excluded_count += 1
                        break

                    if jira_filter.includes_jira_issue(jira_issue):
                        argus_debug('   Matched: {} with value: {}'.format(
                            jira_filter, jira_filter.extract_value(jira_issue)))
                        matched = True
                        if jira_filter.query_type() == 'OR':
                            matched_or = True
                    elif jira_filter.excludes_jira_issue(jira_issue):
                        argus_debug('   Excluded by: {} with value: {}'.format(
                            jira_filter, jira_filter.extract_value(jira_issue)))
                        matched = True
                        excluded = True
                        break
                    # Didn't match and is required, we exclude this JiraIssue
                    elif jira_filter.query_type() == 'AND':
                        argus_debug('   Didn\'t match: {} with value: {} and was AND. Excluding.'.format(
                            jira_filter, jira_filter.extract_value(jira_issue)))
                        excluded = True
                    # Didn't match and was OR, don't flag anything
                    else:
                        argus_debug('   Didn\'t match: {} with value and was OR. Doing nothing: {}'.format(
                            jira_filter, jira_filter.extract_value(jira_issue)))

                    # Cannot short-circuit on match since exclusion beats inclusion and we have to keep checking, but can
                    # on exclusion bool
                    if excluded:
                        excluded_count += 1
                        break

                argus_debug('      key: {} matched: {}. excluded: {}'.format(jira_issue.issue_key, matched, excluded))

                if not excluded:
                    if has_or and not matched_or:
                        argus_debug('   has_or on filter, did not match on or field. Excluding.')
                    elif matched:
                        matching_issues[jira_issue.issue_key] = jira_issue

        print('Returning total of {} JiraIssues matching JiraView {}. Excluded count: {}'.format(
            len(list(matching_issues.keys())),
            self.name,
            excluded_count))

        return matching_issues

    def contains_team(self, team: str) -> bool:
        return team in self._teams

    def clone(self) -> 'JiraView':
        result = JiraView('{}_clone'.format(self.name), self.jira_connection)
        for key, jf in self._jira_filters.items():
            result.add_raw_filter(jf)
        return result

    def __str__(self) -> str:
        result = os.linesep + '[{}]'.format(self.name)
        result += os.linesep + '   Jira Connection: {}'.format(self.jira_connection)
        if len(self._jira_filters) > 0:
            result += os.linesep + '   Jira Filters:'
            for i in sorted(self._jira_filters.keys()):
                result += os.linesep + '      {}'.format(self._jira_filters[i])
        if len(self._teams) > 0:
            result += os.linesep + '   Teams:'
            for t in sorted(self._teams):
                result += str(t)
        return result
