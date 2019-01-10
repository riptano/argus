# Argus - why?
Argus provides some key functionality over the existing JIRA web browser or free JIRA clients:

1. Querying multiple JIRA connections and displaying the results together (single eng, multiple OSS projects for example)
2. Displaying dependency chains of tickets in a single dashboard without having to follow links via a browser.
3. More compact visualization of results in a terminal rather than relying on a browser.
4. Caching jira results locally and only pulling a diff of updated on query.
5. (Planned) Mapping a FixVersion to a release date in a local file / remote wget, allowing dependency chain date assignment.

## Using Argus
* As a general purpose JIRA client: <!-- start_user_guide -->
  * Reference conf/custom_params.cfg for default JiraConnection and JiraProject configurations
  * A JiraConnection will be prompted for upon startup if none are found
  * Create a JiraView using the desired connection. During this process, you wil define filters on that jira view (resolution = unresolved, type = 'Bug', etc)
  * Use the JiraView menu to view tickets matching your view(s)

* Dev / Manager straddling 2 JIRAs:
  * [c] - Jira Connection menu, add a 2nd connection beyond the core default
  * [t] - Team menu. Add a linked team member, linking a username on the 2 projects
  * [r] - Templated reports. Add a [s]ingle user multi-jira report
  * [d] - Dashboard, [d] display dashboard, select the one you just created
    - This should display a dashboard of all open tickets in the multiple JIRA connections in a single dashboard

* As a Manager:
  * Create a team using the team [m]anagement menu
  * Run [t]eam reports against your defined teams, drilling to individual tickets as needed

* Combining JiraViews:
  * The [d]ashboard functionality allows you to define dashboards of multiple, connected JiraViews.

Note: Argus uses a local, application-specific password to encode the user and password information for JIRA connections. <!-- end_user_guide -->

## What's left to do?
* Reference github issue tracking: https://github.com/riptano/argus/issues

## Argus Contributor Getting Started
* JiraConnection: A network / account connection to a Jira instance
* JiraProject: Collection of offline cached JiraIssues
* JiraIssue: Local analog of jira.client Issue. Decorated Dict entry w/k:v mappings of JiraIssues
* JiraFilter: Mechanism by which JiraViews are defined. Supports inclusion, exclusion, and, or
* JiraView: A single column filter based and/or JQL-based view of tickets
* JiraDashboard: A combination of 2 or more JiraViews
* JiraManager: Central management logic for all Jira* objects and their relationships.
* utils.py: General menu and config utilities
* jira_utils.py: Querying logic
* MainMenu: As advertised.
* DisplayFilter: Used to select columns for display, filter based on inclusion criteria (string matching) on results already pulled from JIRA, and change sorting order of results
* TeamManager: Contains logic to run team-based reports
* Filtering: there are 2 major ways in which things can be filtered:
  - ReportFilter.filter_items has the most flexibility as it's python logic
  - filters passed into DisplayFilter.display_issues: allows you to specify a column and an inclusion value, used by users when refining an existing search result.
* team_reports.py:
  - Provides flexibility above and beyond the filtering you can do via JQL against arrays of issues in python, categorized by status (assigned, closed, reviewer, reviewed)
  - ReportFilter: basic report filter.
  - NewReport(ReportFilter):
    - define columns and issue-bucket arrays in __init__
    - override filter_items(
    - override 'def filter_items(self, tmt)' with custom logic to pull out specific tickets desired from a team_manager.TeamMemberTickets object
