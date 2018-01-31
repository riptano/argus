import datetime
from typing import TYPE_CHECKING

from dateutil import parser

from src.jira_issue import JiraIssue
from src.member_issues_by_status import MemberIssuesByStatus
from src.utils import get_input

if TYPE_CHECKING:
    from typing import List


class ReportType:

    UNKNOWN = -1
    MOMENTUM = 1
    CURRENT_LOAD = 2
    TEST_LOAD = 3
    REVIEW_LOAD = 4

    @classmethod
    def from_int(cls, value):
        # type: (int) -> int
        if value == 1:
            return ReportType.MOMENTUM
        elif value == 2:
            return ReportType.CURRENT_LOAD
        elif value == 3:
            return ReportType.TEST_LOAD
        elif value == 4:
            return ReportType.REVIEW_LOAD
        else:
            return ReportType.UNKNOWN


class ReportFilter:

    """
    Base report, not to be used directly
    """
    header = 'Base ReportFilter -> something is busted if you\'re seeing this...'
    namelen = 30

    def __init__(self):
        # We store issues in a manner reflecting of their final visualization. For example, if we want to see 'closed'
        # tickets, we have self.columns['Closed'] defined and self.issues['Closed'] defined. This allows us to arbitrarily
        # define groupings and customize only their logic on child-classes of ReportFilter.
        self.columns = []

        # Dict[str:List[JiraIssue]]
        self.issues = {}

        # set(str) -> JiraIssue keys, used to determine if report contains issue in question
        self.known_issues = set()

        # Many reports are time-bound, so we store this here for convenience rather than replicating it in each child class
        # This should be stored as a datetime object
        self.since = None

    def clear(self):
        for column in self.columns:
            self.issues[column] = []
        self.known_issues = set()

    def column_headers(self):
        # 4 pad to cover #'s for detail breakdown
        result = '      {:<30}'.format('Name')
        for column in self.columns:
            result += '{:<20}'.format(column)
        return result

    def process_issues(self, member_issues):
        # type: (MemberIssuesByStatus) -> None
        raise NotImplementedError()

    def matches(self, jira_issue):
        # type (JiraIssue) -> bool
        raise NotImplementedError()

    def _add_matching_issues(self, column_name, jira_issues):
        # type: (str, List[JiraIssue]) -> None
        """
        Adds issues matching this report filters criteria to the specified column
        """
        matching_issues = [x for x in jira_issues if self.matches(x)]
        self.issues[column_name].extend(matching_issues)
        for jira_issue in matching_issues:
            self.known_issues.add(jira_issue.issue_key)

    def issue_count(self, issue_type):
        # type: (str) -> int
        return len(self.issues[issue_type])

    def print_all_counts(self, name):
        # type: (str) -> str
        result = '{:<30}'.format(name)
        for column in self.columns:
            result += '{:<20}'.format(len(self.issues[column]))
        return result

    def get_issues(self, issue_type):
        # type: (str) -> List[JiraIssue]
        return self.issues[issue_type]

    def contains_issue(self, jira_issue):
        # type: (JiraIssue) -> bool
        """
        Used after report population to determine if an issue should be displayed by a MemberIssuesByStatus
        """
        return jira_issue.issue_key in self.known_issues

    @staticmethod
    def get_since():
        return get_input('Since what date? (-2m or -1y or -5w or -2d, etc)')

    @property
    def needs_duration(self):
        # type: () -> bool
        """
        Determines whether to prompt for and store self.since on this report for matching purposes.
        """
        return False

    def _matches_time(self, jira_issue):
        # type: (JiraIssue) -> bool
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

    def print_all_keys(self):
        print('Printing all keys for report: {}. Total count: {}'.format(self.header, len(self.issues)))
        for issue_key in self.issues:
            print('   Key: {}'.format(issue_key))


class ReportMomentum(ReportFilter):

    """
    Closed non-test, reviewed, and closed test tickets in that order. Time bound report.
    """
    header = 'Closed tickets'

    def __init__(self):
        ReportFilter.__init__(self)
        self.columns = ['Closed non-test', 'Reviewed', 'Closed Test']
        self.issues = {'Closed non-test': [], 'Reviewed': [], 'Closed Test': []}

    def process_issues(self, member_issues):
        # type: (MemberIssuesByStatus) -> None
        assert member_issues is not None, 'process_issues call on a null MemberIssuesByStatus object.'

        self._add_matching_issues('Closed non-test', [x for x in member_issues.closed if not x.is_test])
        self._add_matching_issues('Closed Test', [x for x in member_issues.closed if x.is_test])
        self._add_matching_issues('Reviewed', member_issues.reviewed)

    def matches(self, jira_issue):
        # type (JiraIssue) -> bool
        """
        We only care about whether or not this ticket was resolved in our timespan
        """
        return self._matches_time(jira_issue)

    @property
    def needs_duration(self):
        return True


class ReportCurrentLoad(ReportFilter):

    """
    bug, test, feature, review, PA review
    """
    header = 'Current work load'

    def __init__(self):
        ReportFilter.__init__(self)
        self.columns = ['bug', 'test', 'feature', 'review', 'PA review']
        self.issues = {'bug': [], 'test': [], 'feature': [], 'review': [], 'PA review': []}

    def process_issues(self, member_issues):
        # type: (MemberIssuesByStatus) -> None
        self._add_matching_issues('bug', [x for x in member_issues.assigned if 'Bug' == x.issuetype])
        self._add_matching_issues('test', [x for x in member_issues.assigned if x.is_test])
        self._add_matching_issues('feature', [x for x in member_issues.assigned if x.is_feature])
        self._add_matching_issues('review', [x for x in member_issues.reviewer if 'Patch Available' != x.status])
        self._add_matching_issues('PA review', [x for x in member_issues.reviewer if 'Patch Available' == x.status])

    def matches(self, jira_issue):
        # type (JiraIssue) -> bool
        # Want unresolved issues only for open report. Don't need to time bound
        return jira_issue.is_open


class ReportTestLoad(ReportFilter):

    """
    assigned, closed
    """
    header = 'Test Load'

    def __init__(self):
        ReportFilter.__init__(self)
        self.columns = ['assigned', 'closed']
        self.issues = {'assigned': [], 'closed': []}

    def process_issues(self, member_issues):
        # type: (MemberIssuesByStatus) -> None
        self._add_matching_issues('assigned', member_issues.assigned)
        self._add_matching_issues('closed', member_issues.closed)

    def matches(self, jira_issue):
        # type (JiraIssue) -> bool
        # Open issues or filtered by recency only, test issues only. Test is denoted by a label at this point
        if not jira_issue.is_test:
            return False
        return jira_issue.is_open or self._matches_time(jira_issue)

    @property
    def needs_duration(self):
        return True


class ReportReviewLoad(ReportFilter):

    """
    reviewer actively not PA, PA review, closed
    """
    header = 'Review Load'

    def __init__(self):
        ReportFilter.__init__(self)
        self.columns = ['reviewer', 'PA reviewer', 'reviewed']
        self.issues = {'reviewer': [], 'PA reviewer': [], 'reviewed': []}

    def process_issues(self, member_issues):
        # type: (MemberIssuesByStatus) -> None
        self._add_matching_issues('reviewer', [x for x in member_issues.reviewer if x.status != 'Patch Available'])
        self._add_matching_issues('PA reviewer', [x for x in member_issues.reviewer if x.status == 'Patch Available'])
        self._add_matching_issues('reviewed', member_issues.reviewed)

    def matches(self, jira_issue):
        # type: (JiraIssue) -> bool
        # Unresolved or within recency time frame
        return self._matches_time(jira_issue)

    @property
    def needs_duration(self):
        return True
