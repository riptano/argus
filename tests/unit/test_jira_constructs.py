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
import jira
from typing import Dict

from src import utils;
from src.jira_view import JiraView

utils.unit_test = True
from src.jira_connection import JiraConnection
from src.jira_filter import JiraFilter
from src.jira_issue import JiraIssue
from src.jira_project import JiraProject
from tests.argus_test import Tester


class TestJiraFilter(Tester):

    def setUp(self):
        # Need directory structure created for tests
        super().setUp()

        utils.debug = True

        self._jira_connection = JiraConnection('test_connection')  # type: JiraConnection
        new_project = JiraProject(self._jira_connection,
                                  'TEST',
                                  'http://nope.com',
                                  {'custom_field1': 'reviewer', 'custom_field2': 'reviewer2'})
        self._jira_connection.add_and_link_jira_project(new_project)
        issue_dict = {
            'project': {'id': 123},
            'summary': 'New issue from jira-python',
            'description': 'Test',
            'issuetype': {'name': 'Bug'},
            'assignee': 'jmckenzie',
            'custom_field1': 'jmckenzier',
            'custom_field2': 'jmckenzier2',
            'resolution': 'unresolved',
            'fixversion': ['1.0', '2.0'],
        }
        new_issue = jira.Issue(None, None)  # type: jira.Issue
        new_issue.key = 'TEST-1'
        new_issue.fields = jira.Issue._IssueFields()
        new_issue.fields.__dict__ = issue_dict
        self._jira_issue = JiraIssue(self._jira_connection, new_issue)  # type: JiraIssue
        new_project.add_issue(self._jira_issue)

    def test_match_one(self):
        """
        Confirm match w/single acceptable
        """
        jira_filter = JiraFilter('assignee', self._jira_connection, 'AND')  # type: JiraFilter
        jira_filter.include('jmckenzie')
        assert jira_filter.matches_jira_issue(self._jira_issue)

    def test_matches_or(self):
        """
        Confirm matches w/two entries in the Filter where JiraIssue matches on one w/OR
        """
        jira_filter = JiraFilter('assignee', self._jira_connection, 'OR')  # type: JiraFilter
        jira_filter.include('jmckenzie')
        jira_filter.include('fred')
        assert jira_filter.matches_jira_issue(self._jira_issue)

    def test_not_match_and(self):
        """
        Confirm logic fails if we don't match
        """
        jira_filter = JiraFilter('assignee', self._jira_connection, 'AND')  # type: JiraFilter
        jira_filter.include('jmckenzie')
        jira_filter.include('fred')
        assert not jira_filter.matches_jira_issue(self._jira_issue)

    def test_not_match_or(self):
        """
        Confirm we fail out correctly w/multiple things that don't match on or
        """
        jira_filter = JiraFilter('assignee', self._jira_connection, 'OR')  # type: JiraFilter
        jira_filter.include('bob')
        jira_filter.include('fred')
        assert not jira_filter.matches_jira_issue(self._jira_issue)

    def test_matches_two_and(self):
        """
        With multiple entries in fixversion, we should match if we have both
        """
        jira_filter = JiraFilter('fixversion', self._jira_connection, 'AND')  # type: JiraFilter
        jira_filter.include('1.0')
        jira_filter.include('2.0')
        assert jira_filter.matches_jira_issue(self._jira_issue)

    def test_fails_two_and(self):
        """
        Confirm that with multiple AND in the filter where we only have one, we match
        """
        jira_filter = JiraFilter('fixversion', self._jira_connection, 'AND')  # type: JiraFilter
        jira_filter.include('1.0')
        jira_filter.include('3.0')
        assert not jira_filter.matches_jira_issue(self._jira_issue)


class TestJiraView(Tester):

    def setUp(self):
        # Need directory structure created for tests
        super().setUp()

        utils.debug = True

        self._jira_connection = JiraConnection('test_connection')  # type: JiraConnection
        new_project = JiraProject(self._jira_connection,
                                  'TEST',
                                  'http://nope.com',
                                  {'custom_field1': 'reviewer', 'custom_field2': 'reviewer2'})
        self._jira_connection.add_and_link_jira_project(new_project)
        issue_dict = {
            'project': {'id': 123},
            'summary': 'New issue from jira-python',
            'description': 'Test',
            'issuetype': {'name': 'Bug'},
            'assignee': 'jmckenzie',
            'custom_field1': 'jmckenzier',
            'custom_field2': 'jmckenzier2',
            'resolution': 'unresolved',
            'fixversion': ['1.0', '2.0'],
        }
        new_issue = jira.Issue(None, None)  # type: jira.Issue
        new_issue.key = 'TEST-1'
        new_issue.fields = jira.Issue._IssueFields()
        new_issue.fields.__dict__ = issue_dict
        self._jira_issue = JiraIssue(self._jira_connection, new_issue)  # type: JiraIssue
        new_project.add_issue(self._jira_issue)

    def test_empty_view(self):
        """
        Accidentally had this one come up in another test. Empty JiraView shouldn't match anything.
        """
        jv = JiraView('test_view', self._jira_connection)
        assert len(jv.get_matching_issues()) == 0

    def test_include_two(self):
        """
        Confirm that JiraViews with 2 matching filters works
        """
        jv = JiraView('test_view', self._jira_connection)
        jv.add_single_filter('assignee', 'jmckenzie', 'i', 'AND')
        jv.add_single_filter('reviewer', 'jmckenzier', 'i', 'AND')

        matching = len(jv.get_matching_issues())
        assert matching == 1, 'Expected len of matches to be 1, got: {}'.format(matching)

    def test_include_with_exclude(self):
        """
        Confirm JiraView with an include and an exclude work -> should exclude
        """
        jv = JiraView('test_view', self._jira_connection)
        jv.add_single_filter('assignee', 'jmckenzie', 'i', 'AND')
        jv.add_single_filter('reviewer', 'jmckenzier', 'e', 'AND')

        assert len(jv.get_matching_issues()) == 0, "JiraView with exclusion on reviewer should not have matched!"

    def test_match_only_one(self):
        """
        Test that, if only one of the 2 included JiraViews match, it correctly matches the value
        """
        jv = JiraView('test_view', self._jira_connection)
        jv.add_single_filter('assignee', 'jmckenzie', 'i', 'AND')
        jv.add_single_filter('reviewer', 'DO NOT MATCH', 'i', 'AND')

        matching = len(jv.get_matching_issues())
        assert matching == 1, 'Expected len of matches to be 1, got: {}'.format(matching)
