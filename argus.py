#!/usr/bin/env python
# -*- mode: Python -*-
#
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
import optparse
import signal
import sys

from getpass import getpass

from src import utils
from src.jira_manager import JiraManager
from src.main_menu import MainMenu
from src.team_manager import TeamManager
from src.utils import DESCRIPTION, Config, init_tab_completer

init_tab_completer()

parser = optparse.OptionParser(description=DESCRIPTION, usage='Usage: %prog [options] [host [port]]', version='argus .3')
parser.add_option('-p', '--password', help='provide local password on command-line rather than being prompted')
parser.add_option('-d', '--dashboard', help='name of dashboard to auto-execute into')
parser.add_option('-j', '--jenkins_report', help='TODO:#106 execute and print a jenkins report, exiting upon completion', default=False, action='store_true')
parser.add_option('-n', '--jenkins_project_name', help='Name of consistent root of project names in Jenkins')
parser.add_option('-b', '--jenkins_branch', help='TODO:#107 Used with -j, specify branch to run reports against')
parser.add_option('-t', '--jenkins_type', help='TODO:#108 Used with -j, specify type of test [u]nit test, or [d]test to report against')
parser.add_option('-c', '--triage_csv', help='Specifies local file containing [link, key, summary, assignee, reviewer, status, prio, repro, scope, component] triage file to update against live JIRA data')
parser.add_option('-o', '--triage_out', help='Output file name for updated triage data. If not provided, prints to stdout.')
parser.add_option('-u', '--unit_test', help='Unit testing mode, does not connect servers, saves config changes to test/ folder', action='store_true', dest='unit_test')
parser.add_option('-v', '--verbose', help='Log verbose debug output to console and argus.log', action='store_true', dest='verbose')
parser.add_option('-x', '--experiment', help='Run with extra / experiment menu option for debug work', action='store_true', dest='experiment')
parser.add_option('-w', '--web_server', help='Run in WebServer mode', action='store_true', dest='web_server')
parser.add_option('-i', '--interactive', help='Default mode: run interactive console menu', action='store_true', dest='interactive')
parser.add_option('-s', '--skip', help='Skip JiraConnection/JiraProject cached updates on startup.', action='store_true', dest='skip_update')
parser.add_option('-l', '--limit', help='Limit the number of JiraIssues queried from any given project (for debug purposes).')

optvalues = optparse.Values()
(options, arguments) = parser.parse_args(sys.argv[1:], values=optvalues)
option_dict = vars(options)

if hasattr(options, 'verbose'):
    utils.debug = True
    utils.argus_log = open('argus.log', 'w')

Config.init_argus()

# determine if this is a first run, prompt differently pending that
if hasattr(options, 'password'):
    Config.MenuPass = options.password
else:
    while Config.MenuPass == '':
        Config.MenuPass = getpass('Enter Argus Password (local JIRA credentials will be encrypted with this):')

if hasattr(options, 'limit'):
    Config.JiraLimit = int(options.limit)

if hasattr(options, 'experiment'):
    Config.Experiment = True

if hasattr(options, 'skip_update'):
    Config.SkipUpdate = True

# Init logic / containers to pass to menu or to web server
team_manager = TeamManager.from_file()
jira_manager = JiraManager(team_manager)

# TODO: Flip between web server mode and interactive
if hasattr(options, 'web_server'):
    print('Web server not implemented yet.')
else:
    menu = MainMenu(jira_manager, team_manager, option_dict)
    signal.signal(signal.SIGINT, menu.signal_handler)
    menu.display()
