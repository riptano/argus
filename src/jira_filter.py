from typing import TYPE_CHECKING


from src.utils import argus_debug, get_input, pick_value

if TYPE_CHECKING:
    from configparser import RawConfigParser
    from src.jira_connection import JiraConnection
    from src.jira_manager import JiraManager
    from src.jira_issue import JiraIssue
    from typing import List


class JiraFilter:

    """
    Contains one or many attributes to filter a jira query on.
    Different data requested by the filter is housed here.
    JiraFilters are unique on a per JiraConnection basis, as the alternative would have us querying multiple JiraConnections
    for matching JiraProject caches to find custom field translation. So long as the relationships remain:
        1 -> Many JiraDashboard to JiraView
        1 -> Many JiraConnection to JiraView/JiraDashboard
        1 -> Many JiraView to JiraFilter
    we can only have a single JiraConnection associated with any given view.
    """

    def __init__(self, field, jira_connection, query_type='AND', includes=None, excludes=None):
        # type: (str, JiraConnection, str, List[str], List[str]) -> None
        self._field = field
        self._jira_connection = jira_connection

        self._query_type = query_type

        # Stored in easy plain-text, not custom-field name. Translated to custom field on a per-project basis.
        self._includes = [] if includes is None else includes
        self._excludes = [] if excludes is None else excludes

    def include(self, value):
        # type: (str) -> None
        # Special case. Use 'None' field as Unresolved in JIRA
        # NOTE: Upon addition of a 2nd mapping such as this, consider refactoring to a local Dict[str:str] of mappings
        if self._field == 'resolution' and value.lower() == 'unresolved':
            self._includes.append('None')
        else:
            self._includes.append(value)

    def exclude(self, value):
        # type: (str) -> None
        #   Special case. Use 'None' field as Unresolved in JIRA
        if self._field == 'resolution' and value == 'unresolved':
            self._excludes.append('None')
        else:
            self._excludes.append(value)

    def remove_filter(self):
        print('Removing from JiraFilter: {}'.format(self))
        action = get_input('Remove [i]nclude, [e]xclude, or [q]uit')
        if action == 'i':
            to_remove = pick_value('Remove which include?', self._includes)
            if to_remove is None:
                return
            self._includes.remove(to_remove)
        elif action == 'e':
            to_remove = pick_value('Remove which exclude?', self._excludes)
            if to_remove is None:
                return
            self._excludes.remove(to_remove)

    def is_empty(self):
        return len(self._includes) + len(self._excludes) == 0

    def set_or(self):
        self._query_type = 'OR'

    def set_and(self):
        self._query_type = 'AND'

    def query_type(self):
        return self._query_type

    def _translate_field(self, jira_issue):
        # type: (JiraIssue) -> str
        """
        For this issue, parse out the JiraProject it belongs to and translate our local field's readable text to
        whatever cf* is on the project side
        """
        jira_project = self._jira_connection.maybe_get_cached_jira_project(jira_issue.project_name)
        if jira_project is None:
            return 'None'
        argus_debug('JiraFilter: Attempting to translate {} for jira_issue: {}'.format(
            self._field, jira_issue.issue_key))
        return jira_project.translate_custom_field(self._field)

    def _internal_matching_operation(self, jira_issue, to_match):
        # type: (JiraIssue, List[str]) -> bool
        matches_one = False
        matches_all = True

        translated = self._translate_field(jira_issue)
        in_issue = translated in jira_issue
        value = 'Not found'
        if in_issue:
            value = jira_issue[translated]
        argus_debug('Checking for translated field {} in issue: {}. Found: {}. Value: {}. Filter: {}'.format(
            translated, jira_issue.issue_key, in_issue, value, self))

        if translated in jira_issue:
            argus_debug('Checking for {} in {}'.format(translated, jira_issue.issue_key))
            for match in to_match:
                argus_debug('Checking against match: {}'.format(match))
                if match in jira_issue[translated]:
                    argus_debug('   FOUND MATCH')
                    matches_one = True
                else:
                    matches_all = False

        if self.query_type() == 'OR':
            return matches_one

        return matches_one and matches_all

    def includes_jira_issue(self, jira_issue):
        # type: (JiraIssue) -> bool
        return self._internal_matching_operation(jira_issue, self._includes)

    def excludes_jira_issue(self, jira_issue):
        # type: (JiraIssue) -> bool
        return self._internal_matching_operation(jira_issue, self._excludes)

    def extract_value(self, jira_issue):
        # type: (JiraIssue) -> str
        translated = self._translate_field(jira_issue)
        if translated not in jira_issue:
            return 'N/A'
        return jira_issue[translated]

    @property
    def field_name(self):
        # type: () -> str
        return self._field

    def set_field_name(self, value):
        # type: (str) -> None
        self._field = value

    @classmethod
    def from_file(cls, jira_manager, filter_field, config_parser):
        # type: (JiraManager, str, RawConfigParser) -> JiraFilter
        jira_connection_name = config_parser.get(filter_field, 'jira_connection')
        jira_connection = jira_manager.get_jira_connection(jira_connection_name)
        result = JiraFilter(filter_field, jira_connection)

        and_or = config_parser.get(filter_field, 'query_type')
        if str(and_or) == 'AND':
            result.set_and()
        else:
            result.set_or()

        if config_parser.has_option(filter_field, 'inclusions'):
            includes = config_parser.get(filter_field, 'inclusions').split(',')
            for i in includes:
                result.include(i)
        if config_parser.has_option(filter_field, 'exclusions'):
            excludes = config_parser.get(filter_field, 'exclusions').split(',')
            for e in excludes:
                result.exclude(e)

        return result

    def save_config(self, config_parser):
        # type: (RawConfigParser) -> None
        config_parser.add_section(self._field)
        config_parser.set(self._field, 'name', self._field)
        config_parser.set(self._field, 'jira_connection', self._jira_connection.connection_name)
        config_parser.set(self._field, 'query_type', self._query_type)
        if len(self._includes) > 0:
            config_parser.set(self._field, 'inclusions', ','.join(self._includes))
        if len(self._excludes) > 0:
            config_parser.set(self._field, 'exclusions', ','.join(self._excludes))

    def __str__(self):
        return 'name: {} type: {} _includes: {} _excludes: {}'.format(self._field, self._query_type, ','.join(self._includes), ','.join(self._excludes))
