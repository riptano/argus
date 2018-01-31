from typing import TYPE_CHECKING

from jira import Issue
from jira.client import Project, ResultList

if TYPE_CHECKING:
    from typing import List


class TestWrappedJiraConnectionStub:

    """
    Test class used in place of JiraConnection for unit tests or other offline testing purposes
    """
    name_prefix = 1

    def __init__(self):
        self.prefix = TestWrappedJiraConnectionStub.name_prefix
        TestWrappedJiraConnectionStub.name_prefix += 1

    def projects(self):
        # type: () -> List[Project]
        result = list()
        for x in range(0, 10, 1):
            temp_project = Project(None, None)
            name = '{}_{}'.format(self.name_prefix, x)
            temp_project.name = name
            temp_project.key = name
            result.append(temp_project)
        return result

    @staticmethod
    def search_issues():
        # type: () -> ResultList[Issue]
        result = ResultList()

        for x in range(0, 10, 1):
            temp_issue = Issue(None, None)
            temp_issue.key = 'Test-{}'.format(x)
            temp_issue.updated = '2014-01-01 00:00:01'
            result.append(temp_issue)

        return result
