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

from typing import TYPE_CHECKING, List

from jira import Issue
from jira.client import Project, ResultList


class TestWrappedJiraConnectionStub:

    """
    Test class used in place of JiraConnection for unit tests or other offline testing purposes
    """
    name_prefix = 1

    def __init__(self) -> None:
        self.prefix = TestWrappedJiraConnectionStub.name_prefix
        TestWrappedJiraConnectionStub.name_prefix += 1

    def projects(self) -> List[Project]:
        result = list()
        for x in range(0, 10, 1):
            temp_project = Project(None, None)
            name = '{}_{}'.format(self.name_prefix, x)
            temp_project.name = name
            temp_project.key = name
            result.append(temp_project)
        return result

    @staticmethod
    def search_issues() -> ResultList:
        result = ResultList()

        for x in range(0, 10, 1):
            temp_issue = Issue(None, None)
            temp_issue.key = 'Test-{}'.format(x)
            temp_issue.updated = '2014-01-01 00:00:01'
            result.append(temp_issue)

        return result
