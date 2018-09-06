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

import os
from typing import TYPE_CHECKING, Dict, List, Optional, Set

from src import utils
from src.member_issues_by_status import JiraUserName, MemberIssuesByStatus
from src.utils import pick_value

if TYPE_CHECKING:
    from src.jira_connection import JiraConnection
    from src.jira_issue import JiraIssue


class Team:
    """
    Contains MemberIssuesByStatus. These objects contain all possible names for a given team member and all jira issues
    connected to their work.
    """

    def __init__(self, name: str, jira_connection_name: str) -> None:
        self.name = name

        # Only used for identification during serialization
        self.jira_connection_name = jira_connection_name

        # Dict of [JiraUserName:MemberIssuesByStatus]. We key this by the first JiraConnection username the user is added with, though
        # it should be relatively agnostic.
        self._team_members = {}  # type: Dict[JiraUserName, MemberIssuesByStatus]

    def add_member(self, name: str, jira_connection: 'JiraConnection') -> None:
        new_key = JiraUserName(name, jira_connection.connection_name, self.name)
        self._team_members[new_key] = MemberIssuesByStatus(new_key)

    def add_existing_member(self, member_issues: MemberIssuesByStatus) -> None:
        self._team_members[member_issues.primary_name] = member_issues

    def prompt_to_remove_member(self) -> bool:
        """
        :return: Whether deletion took place or not so parent can save team config on change
        """
        to_remove = pick_value('Remove which member?', self.member_names)
        if to_remove is None:
            return False
        to_del = self.convert_name_to_jira_user_name(to_remove)
        if to_del is None:
            return False
        del self._team_members[to_del]
        return True

    def delete_member(self, user_name: str) -> None:
        to_delete = None
        for jun in self._team_members.keys():
            if jun.user_name == user_name:
                to_delete = jun
        if to_delete is not None:
            del self._team_members[to_delete]

    @property
    def root_name(self) -> str:
        return '{}:{}'.format(self.name, self.jira_connection_name)

    @property
    def member_names(self) -> List[str]:
        return [x.user_name for x in self._team_members.keys()]

    @property
    def members(self) -> List[MemberIssuesByStatus]:
        return list(self._team_members.values())

    def convert_name_to_jira_user_name(self, name: str) -> Optional[JiraUserName]:
        """
        If we have a unique JiraUserName, we'll translate name to that. Throws on duplicates found, so use with caution.
        """
        found = None
        for jun in self._team_members:
            if jun.user_name == name:
                # TODO: Given it's reasonable for someone to re-use jira usernames across projects, we should support this.
                if found is not None:
                    raise Exception('Found duplicate user name in get_member_by_name: {}'.format(name))
                found = jun
        return found

    def get_member_issues(self, name: str) -> Optional[MemberIssuesByStatus]:
        """
        Raises exception if jira user name is a duplicate across multiple instances
        """
        jun = self.convert_name_to_jira_user_name(name)
        if jun is None:
            return None
        return self._team_members[jun]

    # No save_config nor from_file in Team. Saved in TeamManager
    # No from_file in Team. Constructed in TeamManager

    def get_linked_jira_connections(self) -> Set[str]:
        """
        :return: Set of all jira connections that team members on this team have a relationship with.
        """
        result = set()
        for member in list(self._team_members.values()):
            result.update(member.connection_names)
        return result

    def populate_jira_issues(self, jira_connection: 'JiraConnection', issues: List[List['JiraIssue']]) -> None:
        count_added = 0
        for list_of_issues in issues:
            for jira_issue in list_of_issues:
                for member in list(self._team_members.values()):
                    # Can't short-circuit here since one member may be assignee and another reviewer
                    if member.add_if_owns(jira_connection, jira_issue):
                        count_added += 1
        utils.argus_debug('Team: {}. JiraConnection: {}. Count added: {}'.format(self.name, jira_connection.connection_name, count_added))
        for member in list(self._team_members.values()):
            utils.argus_debug('At end of add_owned_issues for team: {}. Member: {}'.format(self.name, member))

    def clear_jira_issues(self) -> None:
        for member in list(self._team_members.values()):
            member.clear()

    def __str__(self) -> str:
        result = '{}:'.format(self.name)
        for member in sorted([x.primary_user_name for x in list(self._team_members.values())]):
            result += os.linesep + '   {}'.format(member)
        return result
