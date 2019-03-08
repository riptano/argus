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
from subprocess import Popen
from typing import Dict, Optional, TYPE_CHECKING


from src.jira_view import JiraView
from src.utils import (browser, get_input, is_yes, pause, pick_value,
                       print_separator)

from .display_filter import DisplayFilter

if TYPE_CHECKING:
    from src.display_filter import Column
    from src.jira_manager import JiraManager


class JiraDashboard:

    """
    Contains multiple JiraViews linked together into a single display
    """

    def __init__(self, name: str, jira_views: Dict[str, JiraView]) -> None:
        self.name = name
        self._jira_views = jira_views

    @classmethod
    def build(cls, jira_views: Dict[str, JiraView]) -> Optional['JiraDashboard']:
        """
        Links 2 or more JiraViews together, combining their results for display
        """
        if len(jira_views) <= 1:
            print('Need at least 2 JiraViews to create a dashboard. Please create more JiraViews first.')
            return None

        view_name_options = list(jira_views.keys())
        dash_name = get_input('Name this dashboard:', lowered=False)
        view_name = pick_value('Include which view?', view_name_options, True, 'Cancel')
        if view_name is None:
            return None

        dash_views = {view_name: jira_views[view_name]}
        view_name_options.remove(view_name)

        view_name = pick_value('Second view?', view_name_options, False)
        # make mypy happy - doesn't realize False means we can't have None
        if view_name is None:
            return None
        dash_views[view_name] = jira_views[view_name]
        view_name_options.remove(view_name)

        while len(view_name_options) > 0:
            if is_yes('Add another?'):
                view_name = pick_value('What view?', view_name_options, True, '[q] Cancel')
                if view_name == 'q' or view_name is None:
                    break
                dash_views[view_name] = jira_views[view_name]
                view_name_options.remove(view_name)
            else:
                break

        return JiraDashboard(dash_name, dash_views)

    def display_dashboard(self, jira_manager: 'JiraManager', jira_views: Dict[str, JiraView]) -> None:
        df = DisplayFilter.default()

        matching_issues = []
        for jira_view in list(self._jira_views.values()):
            matching_issues.extend(list(jira_view.get_matching_issues().values()))

        filters = {}  # type: Dict[Column, str]
        while True:
            filtered_issues = df.display_and_return_sorted_issues(jira_manager, matching_issues, 1, filters)
            print_separator(60)
            prompt = 'Input [#] integer value to open ticket in browser, [f] to filter column by string, [c] to clear filters, [q] to quit'
            custom = get_input(prompt)
            if custom == 'q':
                return
            elif custom == 'f':
                column_name = pick_value('Filter against which column?', [column.name for column in df.included_columns], True)
                if column_name is None:
                    continue
                to_match = get_input('Filter for what string?', False)

                column_list = [col for col in df.included_columns if col.name == column_name]
                assert len(column_list) == 1, 'Expected only 1 match with column name {}, got {}'.format(column_name, len(column_list))
                filters[column_list[0]] = to_match
            elif custom == 'c':
                filters = {}
            elif custom.isdigit():
                intval = int(custom) - 1
                issue = filtered_issues[intval]

                # As we cache JiraProject data on a JiraConnection basis, we need to reach into the JiraView, to their
                # contained JiraConnections, and check for presence of the owning JiraProject for this issuekey
                # in order to determine our base url to open a browser to this issue. I'm not in love with this.
                base_url = 'unknown'
                for jira_view in list(jira_views.values()):
                    jira_connection = jira_view.jira_connection
                    for jira_project in jira_connection.cached_projects:
                        if jira_project.owns_issue(issue):
                            base_url = jira_connection.url
                if base_url == 'unknown':
                    print('Failed to find JiraConnection for issuekey: {}. Something went wrong.'.format(issue.issue_key))
                else:
                    issue_url = '{}browse/{}'.format(base_url, issue)
                    try:
                        Popen([browser(), issue_url])
                        print('Opened {}. Press enter to continue.'.format(issue_url))
                        pause()
                    except OSError as oe:
                        print('Failed to open browser [{}]. Probably need to configure your environment or update from main menu. Exception: {}'.format(browser(), oe))
            else:
                print('Oops... Unrecognized input. Please try again.')
                pause()

    def edit_dashboard(self, all_views: Dict[str, JiraView]) -> None:
        # Remove currently held from list of all for iteration
        for view_name in list(self._jira_views.keys()):
            all_views.pop(view_name)

        cmd = ''
        while cmd != 'q':
            cmd = get_input('[A]dd a view, [R]emove a view, [Q]uit:')
            if cmd == 'r':
                to_remove = pick_value('Remove which view?', list(self._jira_views.keys()), True, 'Cancel')
                if to_remove is None:
                    continue
                all_views.update({to_remove: self._jira_views[to_remove]})
                self._jira_views.pop(to_remove)
            elif cmd == 'a':
                to_add = pick_value('Add which view?', list(all_views.keys()), True, 'Cancel')
                if to_add is None:
                    continue
                self._jira_views[to_add] = all_views[to_add]
                all_views.pop(to_add)

    def add_jira_view(self, jira_view: JiraView) -> None:
        self._jira_views[jira_view.name] = jira_view

    def remove_jira_view(self, jira_view_name: str) -> None:
        if jira_view_name in self._jira_views:
            del self._jira_views[jira_view_name]

    def contains_jira_view(self, jira_view_name: str) -> bool:
        return jira_view_name in self._jira_views

    def save_config(self, config_parser: RawConfigParser) -> None:
        config_parser.set('Dashboards', self.name, ','.join(list(self._jira_views.keys())))

    def __str__(self) -> str:
        result = 'Name: {}'.format(self.name)
        for view in self._jira_views:
            result += ', View: {}'.format(view)
        return result
