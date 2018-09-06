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

import datetime
import itertools

from dateutil import parser

from src.jira_issue import JiraIssue
from src.member_issues_by_status import MemberIssuesByStatus
from src.utils import get_input
from typing import Dict, List, Optional, Set


class ReportType:

    UNKNOWN = -1
    MOMENTUM = 1
    CURRENT_LOAD = 2
    TEST_LOAD = 3
    REVIEW_LOAD = 4
    FIXVERSION = 5
    META = 6

    @classmethod
    def from_int(cls, value: int) -> int:
        if value == 1:
            return ReportType.MOMENTUM
        elif value == 2:
            return ReportType.CURRENT_LOAD
        elif value == 3:
            return ReportType.TEST_LOAD
        elif value == 4:
            return ReportType.REVIEW_LOAD
        elif value == 5:
            return ReportType.FIXVERSION
        elif value == 6:
            return ReportType.META
        else:
            return ReportType.UNKNOWN


class ReportFilter:

    """
    Base report, not to be used directly
    """
    header = 'Base ReportFilter -> something is busted if you\'re seeing this...'
    name_width = 30
    col_width = 20

    # Based description, leaving blank
    description = 'No detail provided for this report'

    def __init__(self) -> None:
        # We store issues in a manner reflecting of their final visualization. For example, if we want to see 'closed'
        # tickets, we have self.columns['Closed'] defined and self.issues['Closed'] defined. This allows us to arbitrarily
        # define groupings and customize only their logic on child-classes of ReportFilter.
        self.columns = []  # type: List[str]

        self.issues = {}  # type: Dict[str, List[JiraIssue]]

        # JiraIssue keys, used to determine if report contains issue in question
        self.known_issues = set()  # type: Set[str]

        # Many reports are time-bound, so we store this here for convenience rather than replicating it in each child class
        # This should be stored as a datetime object
        self.since = None  # type: Optional[datetime.datetime]

    def clear(self) -> None:
        for column in self.columns:
            self.issues[column] = []
        self.known_issues = set()

    def column_headers(self) -> str:
        # 4 pad to cover #'s for detail breakdown
        result = '{:<{width}.{width}} '.format('Name', width=self.name_width)
        for column in self.columns:
            result += '{:<{width}.{width}}'.format(column, width=self.col_width)
        return result

    def process_issues(self, member_issues: MemberIssuesByStatus) -> None:
        raise NotImplementedError()

    def matches(self, jira_issue: JiraIssue) -> bool:
        raise NotImplementedError()

    def _add_matching_issues(self, column_name: str, jira_issues: List[JiraIssue]) -> None:
        """
        Adds issues matching this report filters criteria to the specified column. Relies on self.matches to determine
        which issues match what this report is looking for
        """
        matching_issues = [x for x in jira_issues if self.matches(x)]
        self.issues[column_name].extend(matching_issues)
        for jira_issue in matching_issues:
            self.known_issues.add(jira_issue.issue_key)

    def issue_count(self, issue_type: str) -> int:
        return len(self.issues[issue_type])

    def print_all_counts(self, name: str) -> str:
        result = '{:<{width}.{width}} '.format(name, width=self.name_width)
        for column in self.columns:
            result += '{:<{width}}'.format(len(self.issues[column]), width=self.col_width)
        return result

    def get_issues(self, issue_type: str) -> List[JiraIssue]:
        return self.issues[issue_type]

    def contains_issue(self, jira_issue: JiraIssue) -> bool:
        """
        Used after report population to determine if an issue should be displayed by a MemberIssuesByStatus
        """
        return jira_issue.issue_key in self.known_issues

    def set_header(self, new_header: str) -> None:
        self.header = new_header

    def print_description(self) -> None:
        print(self.description)

    @staticmethod
    def get_since() -> str:
        return get_input('Since what date? (-2m or -1y or -5w or -2d, etc)')

    @property
    def needs_duration(self) -> bool:
        """
        Determines whether to prompt for and store self.since on this report for matching purposes.
        """
        return False

    def prompt_for_data(self) -> None:
        """
        Prompt user for necessary data for this report. Defaults to a no-op
        """
        pass

    def _matches_time(self, jira_issue: JiraIssue) -> bool:
        """
        Compares against self.since to determine if the jira_issue should be included or not
        """
        # JIRA resolutiondate time format: 2016-12-12T08:58:11.588-0600
        assert self.since is not None, 'Attempted to match time against ReportFilter without initialized self.since'

        # As we expect self.since to be set externally, we need to assert that it's been set correctly before attempting to use it
        assert isinstance(self.since, datetime.datetime),\
            'Attempted to match time against incorrectly formatted self.since. Expected datetime.datetime type, got: {}'.format(type(self.since))

        # Currently open tickets match any time bound as we strictly do >= comparisons
        if jira_issue.is_open or jira_issue.resolved is None or jira_issue.resolved == 'None':
            return True

        issue_time = parser.parse(jira_issue.resolved)
        return issue_time >= self.since

    def print_all_keys(self) -> None:
        print('Printing all keys for report: {}. Total count: {}'.format(self.header, len(self.issues)))
        for issue_key in self.issues:
            print('   Key: {}'.format(issue_key))


class ReportMomentum(ReportFilter):

    """
    Closed non-test, reviewed, and closed test tickets in that order. Time bound report.
    """
    header = 'Closed tickets'

    def __init__(self) -> None:
        ReportFilter.__init__(self)
        self.columns = ['Closed non-test', 'Reviewed', 'Closed Test']
        self.issues = {'Closed non-test': [], 'Reviewed': [], 'Closed Test': []}

    def process_issues(self, member_issues: MemberIssuesByStatus) -> None:
        assert member_issues is not None, 'process_issues call on a null MemberIssuesByStatus object.'

        self._add_matching_issues('Closed non-test', [x for x in member_issues.closed if not x.is_test])
        self._add_matching_issues('Closed Test', [x for x in member_issues.closed if x.is_test])
        self._add_matching_issues('Reviewed', member_issues.reviewed)

    def matches(self, jira_issue: JiraIssue) -> bool:
        """
        We only care about whether or not this ticket was resolved in our timespan
        """
        return self._matches_time(jira_issue)

    @property
    def needs_duration(self) -> bool:
        return True


class ReportCurrentLoad(ReportFilter):

    """
    bug, test, feature, review, PA review
    """
    header = 'Current work load'

    def __init__(self) -> None:
        ReportFilter.__init__(self)
        self.columns = ['bug', 'test', 'feature', 'review', 'PA review', 'Total']
        self.issues = {'bug': [], 'test': [], 'feature': [], 'review': [], 'PA review': [], 'Total': []}

    def process_issues(self, member_issues: MemberIssuesByStatus) -> None:
        self._add_matching_issues('bug', [x for x in member_issues.assigned if 'Bug' == x.issuetype])
        self._add_matching_issues('test', [x for x in member_issues.assigned if x.is_test])
        self._add_matching_issues('feature', [x for x in member_issues.assigned if x.is_feature])
        self._add_matching_issues('review', [x for x in member_issues.reviewer if 'Patch Available' != x.status])
        self._add_matching_issues('PA review', [x for x in member_issues.reviewer if 'Patch Available' == x.status])
        self._add_matching_issues('Total', [x for x in itertools.chain(member_issues.assigned, member_issues.reviewer)])

    def matches(self, jira_issue: JiraIssue) -> bool:
        # Want unresolved issues only for open report. Don't need to time bound
        return jira_issue.is_open


class ReportMeta(ReportFilter):
    """
    GOAL: get a snapshot of both the total open workload for an engineer and the
    total throughput by ticket count, split out by the priority of the tickets as
    a proxy for size/intensity of the work. Want to be able to fight bias (both
    positive and negative) about engineers and spot potential underperformers, or
    engineers not "equally contributing" to collective team work (reviews, tests, etc)

    Key: C=Critical, H=High, E=Else, X=Test, T=Total, O=Owned, R=Reviewer
    [Date range: <X> to <Y>]
    ---------------[Workload]---------------------------------- |-------------[Closed]--------------------------------- |
    ----------  CO---CR---HO---HR---EO---ER---XO---XR---TO---TR |-CO---CR---HO---HR---EO---ER---XO---XR---TO---TR------ |
    <name>      #    #    #    #    #    #    #    #    #    #    #    #    #    #    #    #    #    #    #    #

    [w to sort by total owned, x to sort by total review open, y to sort by closed owned,
    z to sort by closed reviewed, i to invert current sort category order, c to print csv,
    d to change date range]

    <name> should be first initial last name, truncated
    """
    header = 'Meta Workload Report'
    col_width = 5
    description = 'Key: C=Critical, H=High, E=Else, X=Test, T=Total, A=Assignee, R=Reviewer, prefix C=Closed'

    def __init__(self) -> None:
        ReportFilter.__init__(self)
        self.columns = ['CA', 'CR', 'HA', 'HR', 'EA', 'ER', 'XA', 'XR', 'TA', 'TR', 'CCA', 'CCR', 'CHA', 'CHR', 'CEA', 'CER', 'CXA', 'CXR', 'CTA', 'CTR']
        self.issues = {
            'CA': [],
            'CR': [],
            'HA': [],
            'HR': [],
            'EA': [],
            'ER': [],
            'XA': [],
            'XR': [],
            'TA': [],
            'TR': [],
            'CCA': [],
            'CCR': [],
            'CHA': [],
            'CHR': [],
            'CEA': [],
            'CER': [],
            'CXA': [],
            'CXR': [],
            'CTA': [],
            'CTR': []
        }

    def process_issues(self, member_issues: MemberIssuesByStatus) -> None:
        # First half -> the open issues
        self._add_matching_issues('CA', [x for x in member_issues.assigned if 'Critical' == x.priority and x.not_test])
        self._add_matching_issues('CR', [x for x in member_issues.reviewer if 'Critical' == x.priority and x.not_test])
        self._add_matching_issues('HA', [x for x in member_issues.assigned if 'High' == x.priority and x.not_test])
        self._add_matching_issues('HR', [x for x in member_issues.reviewer if 'High' == x.priority and x.not_test])
        self._add_matching_issues('EA', [x for x in member_issues.assigned if x.mid_low_prio and x.not_test])
        self._add_matching_issues('ER', [x for x in member_issues.reviewer if x.mid_low_prio and x.not_test])
        self._add_matching_issues('XA', [x for x in member_issues.assigned if x.is_test])
        self._add_matching_issues('XR', [x for x in member_issues.reviewer if x.is_test])
        self._add_matching_issues('TA', member_issues.assigned)
        self._add_matching_issues('TR', member_issues.reviewer)

        # Second half -> the closed issues
        self._add_matching_issues('CCA', [x for x in member_issues.closed if 'Critical' == x.priority and x.not_test])
        self._add_matching_issues('CCR', [x for x in member_issues.reviewed if 'Critical' == x.priority and x.not_test])
        self._add_matching_issues('CHA', [x for x in member_issues.closed if 'High' == x.priority and x.not_test])
        self._add_matching_issues('CHR', [x for x in member_issues.reviewed if 'High' == x.priority and x.not_test])
        self._add_matching_issues('CEA', [x for x in member_issues.closed if x.mid_low_prio and x.not_test])
        self._add_matching_issues('CER', [x for x in member_issues.reviewed if x.mid_low_prio and x.not_test])
        self._add_matching_issues('CXA', [x for x in member_issues.closed if x.is_test])
        self._add_matching_issues('CXR', [x for x in member_issues.reviewed if x.is_test])
        self._add_matching_issues('CTA', [x for x in member_issues.closed if x.not_test])
        self._add_matching_issues('CTR', [x for x in member_issues.reviewed if x.not_test])

    def matches(self, jira_issue: JiraIssue) -> bool:
        return self._matches_time(jira_issue)

    @property
    def needs_duration(self):
        return True


class ReportFixVersion(ReportFilter):

    """
    bug, test, feature, review, PA review
    Filters based on fixversion

    """
    header = 'FixVersion Momentum Report'

    def __init__(self) -> None:
        ReportFilter.__init__(self)
        self.columns = ['Assigned', 'Closed non-test', 'Reviewed', 'Closed Test', 'Total']
        self.issues = {'Assigned': [], 'Closed non-test': [], 'Reviewed': [], 'Closed Test': [], 'Total': []}
        self._fix_version = None  # type: Optional[str]

    def process_issues(self, member_issues: MemberIssuesByStatus) -> None:
        assert member_issues is not None, 'process_issues call on a null MemberIssuesByStatus object.'

        self._add_matching_issues('Assigned', [x for x in member_issues.assigned])
        self._add_matching_issues('Closed non-test', [x for x in member_issues.closed if not x.is_test])
        self._add_matching_issues('Closed Test', [x for x in member_issues.closed if x.is_test])
        self._add_matching_issues('Reviewed', member_issues.reviewed)
        self._add_matching_issues('Total', member_issues.all_tickets)

    def set_fix_version(self, new_version: str) -> None:
        self._fix_version = new_version

    def matches(self, jira_issue: JiraIssue) -> bool:
        """
        Match against FixVersion, any ticket type, any status
        """
        assert self._fix_version is not None, 'Need to populate FixVersion in report before matching and populating'
        if self._matches_time(jira_issue):
            return jira_issue.has_fix_version(self._fix_version)
        return False

    def prompt_for_data(self) -> None:
        self._fix_version = get_input('Run report against what FixVersion?', False)
        if not self._fix_version:
            raise Exception('Must input non-empty value for fixversion')

    @property
    def needs_duration(self) -> bool:
        return True


class ReportTestLoad(ReportFilter):

    """
    assigned, closed
    """
    header = 'Test Load'

    def __init__(self) -> None:
        ReportFilter.__init__(self)
        self.columns = ['assigned', 'closed']
        self.issues = {'assigned': [], 'closed': []}

    def process_issues(self, member_issues: MemberIssuesByStatus) -> None:
        self._add_matching_issues('assigned', member_issues.assigned)
        self._add_matching_issues('closed', member_issues.closed)

    def matches(self, jira_issue: JiraIssue) -> bool:
        # Open issues or filtered by recency only, test issues only. Test is denoted by a label at this point
        if not jira_issue.is_test:
            return False
        return jira_issue.is_open or self._matches_time(jira_issue)

    @property
    def needs_duration(self) -> bool:
        return True


class ReportReviewLoad(ReportFilter):

    """
    reviewer actively not PA, PA review, closed
    """
    header = 'Review Load'

    def __init__(self) -> None:
        ReportFilter.__init__(self)
        self.columns = ['reviewer', 'PA reviewer', 'reviewed']
        self.issues = {'reviewer': [], 'PA reviewer': [], 'reviewed': []}

    def process_issues(self, member_issues: MemberIssuesByStatus) -> None:
        self._add_matching_issues('reviewer', [x for x in member_issues.reviewer if x.status != 'Patch Available'])
        self._add_matching_issues('PA reviewer', [x for x in member_issues.reviewer if x.status == 'Patch Available'])
        self._add_matching_issues('reviewed', member_issues.reviewed)

    def matches(self, jira_issue: JiraIssue) -> bool:
        # Unresolved or within recency time frame
        return self._matches_time(jira_issue)

    @property
    def needs_duration(self) -> bool:
        return True
