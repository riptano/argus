import sys
from subprocess import Popen
from typing import Dict, List, Optional
from typing import TYPE_CHECKING

from src.jira_issue import JiraIssue
from src.utils import browser, ConfigError

if TYPE_CHECKING:
    from src.jira_connection import JiraConnection
    from src.jira_manager import JiraManager


class JiraUtils:
    """
    A collection of some various JIRA querying extensions and automations above and beyond what the basic JIRA library
    offers
    """

    # use a hash of hashes so we can simplify from switch on type to simple dict access
    # all inner maps are outward -> inward, though the relationship differs based on type
    dependencies = {}  # type: Dict[str, Dict[str, str]]

    # Cache of all seen JIRA issues from querying by key
    _cached_jira_issues = {}  # type: Dict[str, JiraIssue]

    @staticmethod
    def get_issues_by_query(jira_connection: 'JiraConnection', jql: str) -> List['JiraIssue']:
        """
        NOTE: Whenever we query jira issues out of a Jira instance, we need to use this method to ensure that the
        project type associated with the query is cached for custom field translation in the future.

        We could return a list of JIRA keys and just query those since we cache them in the JiraUtils object to resolve
        dependency chains, however there's no benefit to that as we already have primary results in ResultSet form
        from the python JIRA object.

        :param: jira_connection: jira connection object used to search_issues
        :param: jql: the JQL to run against the connection and retrieve issues
        :return: list of JIRA Issues matching query
        """
        # TODO MS.15: Completely remove this and do all offline cached
        print('Querying tickets with jql: {}'.format(jql))

        total = sys.maxsize
        retrieved = 0
        results = []
        while retrieved < total:
            queried = jira_connection.search_issues(jql, startAt=retrieved, maxResults=1000)
            total = queried.total
            retrieved += len(queried)
            # DisplayFilter now works solely on offline cached JiraIssue structures, so we convert now for interim
            for issue in queried:
                try:
                    new_jira_issue = JiraIssue(jira_connection, issue)
                    results.append(new_jira_issue)
                except ConfigError as ce:
                    print('Error on JiraIssue creation: {}. Skipping {}.'.format(ce, str(issue)))

        return results

    @staticmethod
    def get_issues_for_project(jira_connection: 'JiraConnection', project_name: str, update_cutoff: Optional[str]=None) -> List['JiraIssue']:
        """
        Queries out all results for a given project on the provided JiraConnection after a specified update time.
        :param update_cutoff: str datetime in valid JIRA timestamp format.
            NOTE: Valid formats: 'yyyy/MM/dd HH:mm', 'yyyy-MM-dd HH:mm', 'yyyy/MM/dd', 'yyyy-MM-dd', or a period format e.g. '-5d', '4w 2d'
            Most frequently expected use-case is a specific yyyy/MM/dd HH:mm to get all tickets since last update
        """
        update_text = '' if update_cutoff is None else ' AND updated > "{}"'.format(update_cutoff)
        jql = 'PROJECT = {}{}'.format(project_name, update_text)
        print('Getting issues for project using JQL: {}'.format(jql))
        print('NOTE: Some small duplicate issue retrieval will likely occur due to lack of granularity in <updated> field.')
        results = []
        total = sys.maxsize
        retrieved = 0
        while retrieved < total:
            queried = jira_connection.search_issues('PROJECT = {}{}'.format(project_name, update_text), startAt=retrieved, maxResults=100)
            total = queried.total
            print('Querying results in 100 issue increments for project {}. (startAt: {}. total: {})'.format(project_name, retrieved, total))
            retrieved += len(queried)
            for issue in queried:
                try:
                    new_issue = JiraIssue(jira_connection, issue)
                    results.append(new_issue)
                except ConfigError as ce:
                    print('Error initializing JiraIssue: {}. Problem issue: {}. Skipping.'.format(ce, str(issue)))
        update_flavor = '' if update_cutoff is None else ' since {}'.format(update_cutoff)
        print('Queried a total of {} JIRA issues for project {}{}'.format(len(results), project_name, update_flavor))
        return results

    @classmethod
    def retrieve_field_value(cls, jira_manager, issue, field):
        # type: (JiraManager, JiraIssue, str) -> str
        if field not in issue:
            return ''
        elif field in issue:
            return issue[field]
        else:
            # need to translate field based on custom fields for cached JiraProjects inside JiraIssue's JiraConnection
            for jira_project in jira_manager.get_jira_connection(issue.jira_connection_name).cached_projects:
                if jira_project.owns_issue(issue):
                    custom_field = jira_project.translate_custom_field(field)
                    if custom_field not in issue:
                        return ''
                    return issue[jira_project.translate_custom_field(field)]
        raise AssertionError('Got a JiraIssue with no owning JiraProject. Issue: {}, JiraConnection name: {}'.format(issue, issue.jira_connection_name))

    @staticmethod
    def sort_jira_issues(jira_issues):
        # type: (List[JiraIssue]) -> List[JiraIssue]
        # 2 stage sort. First by project name, then by issue key
        jira_issues.sort(key=lambda x: (x.issue_key.split('-')[0], int(x.issue_key.split('-')[1])))
        return jira_issues

    @staticmethod
    def sort_custom_jiraissues_by_key(issues: List[JiraIssue]) -> List[JiraIssue]:
        """
        This is a Hot Mess of duplication w/the above method, but if we end up settling on offline cached only
        data parsing (which I think we should), we'll only need 1 and it's not worth thinking about the abstraction
        to allow for parsing a key from different sources
        """
        # dict of project to issues
        results = {}
        for i in issues:
            project = i.issue_key.split('-')[0]
            if project not in results:
                results[project] = []
            results[project].append(i)

        # Now, we simply sort each sub-array based on integer repr. of keys
        for p in results:
            results[p].sort(key=lambda x: int(x.issue_key.split('-')[1]))

        # And flatten
        final = []
        for p, arr in results.items():
            final.append(arr)
        return [item for sublist in final for item in sublist]

    @staticmethod
    def open_issue_in_browser(base_url, issue_key):
        issue_url = '{}/browse/{}'.format(base_url.rstrip('/'), issue_key)
        Popen([browser(), issue_url])
        print('Opened {}. Press enter to continue.'.format(issue_url))

    @classmethod
    def get_cached_jira(cls, key):
        if key not in cls._cached_jira_issues:
            return None
        return cls._cached_jira_issues[key]
