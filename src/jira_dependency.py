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
from typing import List, Optional, Set, TYPE_CHECKING

from src.utils import print_separator

if TYPE_CHECKING:
    from src.jira_manager import JiraManager


class JiraDependency:
    """
    Used to represent an in-memory linkage to another JiraIssue, built from serialized string format on-disk
    """

    # Track dependencies we run across in tickets that are unknown in order to later prompt to add them to conf
    unknown_dependencies = set()  # type: Set[str]

    dep_map = {
        'Automated By:inward': 'automates',
        'Automated By:outward': 'automated by',
        'Blocked:inward': 'blocks',
        'Blocked:outward': 'blocked by',
        'Blocker:inward': 'blocks',
        'Blocker:outward': 'blocked by',
        'Bonfire Testing:inward': '',
        'Bonfire Testing:outward': '',
        'Cloners:inward': '',
        'Cloners:outward': '',
        'Container:inward': 'contained by',
        'Container:outward': 'contains',
        'Dependency:inward': 'depended on by',
        'Dependency:outward': 'depends on',
        'Dependent:inward': 'depends on',
        'Dependent:outward': 'depended on by',
        'Duplicate:inward': 'duplicates',
        'Duplicate:outward': 'duplicated by',
        'Includes:inward': 'included by',
        'Includes:outward': 'includes',
        'Incorporates:inward': 'incorporated by',
        'Incorporates:outward': 'incorporates',
        'Parent/Child:inward': 'child of',
        'Parent/Child:outward': 'parent of',
        'Reference:inward': 'referenced by',
        'Reference:outward': 'references',
        'Regression:inward': 'regression of',
        'Regression:outward': 'regressed by',
        'Related Issue:inward': 'relates to',
        'Related Issue:outward': 'relates to',
        'Required:inward': 'required by',
        'Required:outward': 'requires',
        'Supercedes:inward': 'superceded by',
        'Supercedes:outward': 'supercedes',
        'dependent:inward': 'depended on by',
        'dependent:outward': 'depends on',
        'Problem/Incident:inward': '',
        'Problem/Incident:outward': '',
    }

    def __init__(self, raw_data: str, jira_manager: 'JiraManager') -> None:
        """
        Expects input in format: 'issue_id:relationship_type:direction'. We expect we will come across links to issues that are not cached
        locally on the host, so make certain you catch ConfigErrors from this constructor. Throws AssertionError on invalid input
        data.
        :param raw_data: string in format 'issuekey:relationship_type:direction'
        :param jira_manager: We take the JiraManager object on construction in order to translate a string issuekey into a ref
        """
        fields = JiraDependency.validate_input_data(raw_data)
        target_issue_key = fields[0]
        target_jira_issue = jira_manager.get_jira_issue(target_issue_key)

        # If we did not find the JiraIssue cached offline, we both create a dummy that we can use to at least print the
        # issuekey during DisplayFilter printing, and we also increment the count of unknown issues for this project.
        if target_jira_issue is None:
            project = target_issue_key.split('-')[0]
            if project not in jira_manager.missing_project_counts:
                jira_manager.missing_project_counts[project] = 1
            else:
                jira_manager.missing_project_counts[project] += 1
            target_jira_issue = jira_manager.create_non_cached_issue(target_issue_key)

        self.target = target_jira_issue
        self.type = fields[1]
        self.direction = fields[2]

    def is_known(self) -> bool:
        """
        Defined as: whether or not we have a translation entry in our JiraDependency.dep_map structure, even if it's to null it.
        Used primarily to build list of unknown dependencies to later prompt user for their addition.
        """
        return self.pretty_type() is not None

    def pretty_type(self) -> Optional[str]:
        """
        Translates the combination of the type of dependency and direction into something human readable. In the event we don't know
        about a specific dependency type being pretty, we return nothing but add that to our unknown structure.
        """
        key = '{}:{}'.format(self.type, self.direction)
        if key not in JiraDependency.dep_map:
            JiraDependency.unknown_dependencies.add(key)
            return None
        return JiraDependency.dep_map[key]

    @property
    def target_issue_key(self) -> str:
        try:
            assert self.target is not None, 'Attempted to access target_issue_key in JiraDependency but target is None'
            assert self.target.issue_key is not None, 'Have target with no issue_key. What we know of target: {}'.format(self.target)
        except AttributeError:
            print('Attempted to access a contained JiraIssue as target in JiraDependency missing an issue_key. What we know of target: {}'.format(self.target))
            exit(-1)
        return self.target.issue_key

    @staticmethod
    def print_unknown_dependency_types() -> None:
        print_separator(30)
        print('Unknown JiraDependency types discovered:')
        print_separator(30)
        for unknown_type in sorted(JiraDependency.unknown_dependencies):
            print('{}'.format(unknown_type))

    @staticmethod
    def validate_input_data(raw_data: str) -> List[str]:
        """
        Throws assertion error on input data being incorrect
        """
        assert ':' in raw_data, 'Got bad input to JiraDependency.validate_input_data: [{}]. Expected colon delimited, got something else'.format(raw_data)
        fields = raw_data.split(':')
        assert len(fields) == 3, 'Got bad input to JiraDependency.validate_input_data: [{}]. Expected 3 fields, got {}'.format(raw_data, len(fields))
        return fields

    @staticmethod
    def get_issue_key_from_dep_str(raw_data: str) -> str:
        fields = JiraDependency.validate_input_data(raw_data)
        return fields[0]

    def __str__(self) -> str:
        return 'IssueKey: {}. Type: {}. Direction: {}'.format(self.target_issue_key, self.type, self.direction)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, JiraDependency):
            return self.target.issue_key == other.target.issue_key and self.type == other.type and self.direction == other.direction
        return False

    def __hash__(self) -> int:
        return hash((self.target_issue_key, self.type, self.direction))
