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

import base64
import configparser
import os
import re
import readline
import sys
import tempfile
import threading
import time
from configparser import RawConfigParser
from glob import glob
from subprocess import Popen
from typing import Any, Callable, List, Optional, TextIO, Tuple
from urllib import request

DESCRIPTION = 'argus, command-line JIRA multi-tool'
BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
TEST_DIR = os.path.join(BASE_DIR, 'tests')
CUSTOM_PARAMS_PATH = 'conf/custom_params.cfg'

conf_dir = 'conf'
jenkins_conf_dir = os.path.join(conf_dir, 'jenkins')
jenkins_connections_dir = os.path.join(jenkins_conf_dir, 'connections')
jenkins_views_dir = os.path.join(jenkins_conf_dir, 'views')
jenkins_reports_dir = os.path.join(jenkins_conf_dir, 'reports')

jira_conf_dir = os.path.join(conf_dir, 'jira')
jira_connection_dir = os.path.join(jira_conf_dir, 'connections')
jira_project_dir = os.path.join(jira_conf_dir, 'projects')
jira_view_dir = os.path.join(jira_conf_dir, 'views')

jenkins_conf_file = os.path.join(jenkins_conf_dir, 'jenkins.cfg')
jira_conf_file = os.path.join(jira_conf_dir, 'jira.cfg')
argus_conf_file = os.path.join(conf_dir, 'argus.cfg')

data_dir = 'data'
jira_data_dir = os.path.join(data_dir, 'jira')
jenkins_data_dir = os.path.join(data_dir, 'jenkins')

# List containing all of the directories that should be created upon startup
DIR_LIST = [conf_dir, jenkins_conf_dir, jenkins_connections_dir, jenkins_views_dir,
            jenkins_reports_dir, data_dir, jira_data_dir, jenkins_data_dir,
            jira_conf_dir, jira_connection_dir, jira_project_dir, jira_view_dir
            ]

thick_separator = '=' * 50
thin_separator = '-' * 50

build_options_str = 'BuildOptions'
builds_to_check_str = 'builds_to_check'
recent_str = 'recent_builds_to_check'

debug = False
argus_log = None  # type: Optional[TextIO]
unit_test = False

show_dependencies = False
show_only_open_dependencies = True


def save_argus_config(config_parser: RawConfigParser, file_name: str) -> None:
    """
    Redirects saving of config file to test folder if running a unit test
    """
    if unit_test:
        file_name = os.path.join(TEST_DIR, file_name)
    with open(file_name, 'w') as config_file:
        config_parser.write(config_file)


def build_config_name(file_name: str) -> str:
    if unit_test:
        return os.path.join('tests', file_name)
    return file_name


def clear() -> None:
    if is_win():
        os.system('cls')
    else:
        os.system('clear')


def encode_password() -> str:
    return Config.MenuPass


def browser() -> str:
    return Config.Browser


def open_url_in_browser(url: str) -> None:
    Popen([browser(), url])
    print('Opened {}. Press enter to continue.'.format(url))


def change_browser() -> None:
    new_browser = get_input('Enter command line of browser:', lowered=False)
    Config.Browser = new_browser


def time_format_string() -> str:
    return '%Y/%m/%d %H:%H'


def is_win() -> bool:
    return 'nt' in os.name


def is_mac() -> bool:
    return 'darwin' in sys.platform


def pause() -> None:
    input('Press Enter to continue')


def indent(num: int, value: str) -> None:
    """
    Avoiding textwrap import
    """
    to_print = ''
    for _ in range(num):
        to_print += ' '
    print(to_print + value)


def get_input(prompt: str, lowered: bool = True) -> str:
    response = input('{} '.format(prompt)).strip()
    if lowered:
        response = response.lower()
    return response


def get_config(val, delim=','):
    return val.split(delim)[1].rstrip()


def is_yes(question: str) -> bool:
    while True:
        val = get_input("{} (y/n):".format(question))
        if val.lower() == 'y' or val.lower() == 'yes':
            return True
        elif val.lower() == 'n' or val.lower() == 'no':
            return False
        else:
            print("Invalid input {}. Please try again...".format(val))


def encode(key: str, to_encode: str) -> str:
    """
    Courtesy of http://stackoverflow.com/questions/2490334/simple-way-to-encode-a-string-according-to-a-password
    Mostly just looking to keep from having an easily readable password stored on the fs
    """
    enc = []
    for i in range(len(to_encode)):
        key_c = key[i % len(key)]
        enc_c = chr((ord(to_encode[i]) + ord(key_c)) % 256)
        enc.append(enc_c)
    # `base64.urlsafe_b64encode` takes a byte string and returns a byte string.
    # Unfortunately, right now `enc` [after the `join`] is a unicode string, and our current function, `encode`,
    # also wants to return a unicode string. No problem, we just have to call `.encode()` on the output of `join`,
    # to get a bytes string to pass into `base64.urlsafe_b64encode`. Then, we call `.decode()` on the output
    # in order to transform it from a bytes string into a unicode string.
    return base64.urlsafe_b64encode(''.join(enc).encode()).decode()


def pick_substring(header: str,
                   options: List[str],
                   allow_exit: bool = True,
                   exit_text: str = 'back to previous menu',
                   ) -> Optional[str]:
    """
    Prompts for regex before passing into regular pick_value
    """
    while True:
        print(header)
        regex = get_input('Provide a regex to search for in the option list, {q} to quit:', False)
        if regex is None or regex.lower() == 'q':
            return None

        filtered_options = []
        for option in options:
            if regex in option:
                filtered_options.append(option)
        if len(filtered_options) == 0:
            print('Found no matches for {}.')
        else:
            break

    return pick_value('Pick from the following matched projects', filtered_options, allow_exit, exit_text)


def pick_value(header: str,
               options: List[str],
               allow_exit: bool = True,
               exit_text: str = 'back to previous menu',
               sort: bool = True,
               silent: bool = False
               ) -> Optional[str]:
    """
    :param header: Message to print before options
    :param options: List of options for user to select from
    :param allow_exit: whether to allow 'q' option and None return
    :param exit_text: behavior to prompt next to 'q' option (retry, quit back, etc)
    :param sort: Leave input options alone or re-order them
    :param silent: Suppress printing of options.
    :return: Selected option, None if 'q' selected
    """
    try:
        sorted_options = sorted(options, key=lambda s: s.lower()) if sort else options
    except AttributeError:
        # int or something that doesn't like s.lower
        sorted_options = sorted(options) if sort else options

    num_options = len(sorted_options)
    option_width = len(str(num_options))
    format_str = '{:>%d} : {}' % option_width

    while True:
        print(header)
        if not silent:
            for option_num, option in enumerate(sorted_options, start=1):
                print(format_str.format(option_num, option))
        if allow_exit:
            print(format_str.format('q', 'quit ({})'.format(exit_text)))
        choice = get_input('>')
        if allow_exit and choice == 'q':
            return None
        try:
            int_choice = int(choice) - 1
            if int_choice < 0 or int_choice >= num_options:
                pause()
                continue
            return sorted_options[int_choice]
        except ValueError:
            print('Received invalid value (likely non-integer). Try again.')
            continue


def display_results(results: List[str], sort: bool = True) -> None:
    sorted_results = sorted(results) if sort else results
    num_results = len(sorted_results)
    result_width = len(str(num_results))
    format_str = '{:>%d} : {}' % result_width
    for i, result in enumerate(sorted_results, start=1):
        print(format_str.format(i, result))


def decode(key: str, enc: str) -> str:
    dec = []
    enc = base64.urlsafe_b64decode(enc).decode()
    for i in range(len(enc)):
        key_c = key[i % len(key)]
        dec_c = chr((256 + ord(enc[i]) - ord(key_c)) % 256)
        dec.append(dec_c)
    return ''.join(dec)


def build_config_file(directory: str, file_name: str) -> str:
    return os.path.join(directory, '{}.cfg'.format(file_name))


def build_jenkins_data_file(connection_name: str) -> str:
    return os.path.join(jenkins_data_dir, '{}.dat'.format(connection_name))


class DependencyType:
    ALL = 1
    DEPENDENT_ONLY = 2
    NONE = 3


class Config:
    JENKINS_URL = 'unknown'
    JENKINS_BRANCHES = []  # type: List[str]
    JENKINS_PROJECT = []  # type: List[str]

    if is_win():
        Browser = 'chrome'
    elif is_mac():
        Browser = 'open'
    else:
        Browser = 'google-chrome'
    MenuPass = ''

    @classmethod
    def init_argus(cls) -> None:
        cls._init_directories()
        cls._init_jenkins_config()
        cls._init_custom_config()

    @staticmethod
    def _init_directories() -> None:
        directories = DIR_LIST
        if unit_test:
            directories = [os.path.join(TEST_DIR, d) for d in directories]
        for directory in directories:
            if not os.path.exists(directory):
                os.mkdir(directory)

    @staticmethod
    def _init_jenkins_config() -> None:
        """Initializes a Jenkins config file if it does not already exist."""
        conf_path = jenkins_conf_file
        if unit_test:
            conf_path = os.path.join(TEST_DIR, jenkins_conf_file)
        if not os.path.exists(conf_path):
            open(conf_path, 'w').close()

        config_parser = configparser.RawConfigParser()
        config_parser.read(conf_path)

        if not config_parser.has_section(build_options_str):
            config_parser.add_section(build_options_str)
        if not config_parser.has_option(build_options_str, builds_to_check_str):
            config_parser.set(build_options_str, builds_to_check_str, str(30))
        if not config_parser.has_option(build_options_str, recent_str):
            config_parser.set(build_options_str, recent_str, str(3))

        with open(conf_path, 'w') as config_file:
            config_parser.write(config_file)

    @staticmethod
    def _init_custom_config() -> None:
        custom_params_path = CUSTOM_PARAMS_PATH
        if unit_test:
            custom_params_path = os.path.join(TEST_DIR, CUSTOM_PARAMS_PATH)
        if not os.path.exists(custom_params_path):
            print('WARNING! Cannot find conf/custom_params.cfg. Will not have default project nor jenkins config data.')
            Config.JENKINS_URL = 'https://test.jenkins.com'
            Config.JENKINS_BRANCHES = ['branch_1.0', 'branch_2.0', 'branch_3.0']
            Config.JENKINS_PROJECT = ['project_1', 'project_2', 'project_3']
        else:
            config_parser = configparser.RawConfigParser()
            config_parser.read(custom_params_path)
            Config.JENKINS_URL = config_parser.get('JENKINS', 'url').rstrip('/')
            Config.JENKINS_BRANCHES = config_parser.get('JENKINS', 'branches').split(',')
            Config.JENKINS_PROJECT = list(config_parser.get('JENKINS', 'project_name'))


def get_build_options() -> Tuple[int, int]:
    config_parser = configparser.RawConfigParser()
    if unit_test:
        config_parser.read(os.path.join(TEST_DIR, jenkins_conf_file))
    else:
        config_parser.read(jenkins_conf_file)
    builds_to_check = config_parser.getint(build_options_str, builds_to_check_str)
    recent_builds_to_check = config_parser.getint(build_options_str, recent_str)
    return builds_to_check, recent_builds_to_check


class ConfigError(ValueError):
    pass


def tempdir() -> str:
    return tempfile.gettempdir()


def json_dir(branch: str, build_type: str) -> str:
    return os.path.join(tempdir(), 'argus', branch, build_type)


def branch_dir(branch: str) -> str:
    return os.path.join(tempdir(), 'argus', branch)


def argus_temp_dir() -> str:
    return os.path.join(tempdir(), 'argus')


def is_empty(value: Optional[str]) -> bool:
    if value is None or value == '' or value.lower() == 'q':
        return True
    return False


def print_separator(count: int, char: str = '-') -> None:
    print(char * count + os.linesep)


def argus_debug(value: str) -> None:
    if debug:
        print('DEBUG: {}'.format(value))
        if argus_log is None:
            return
        argus_log.write(str(value.encode('utf-8')) + os.linesep)


def load_file(tpl: Tuple[Any, Any, Any]) -> None:
    branch, build_type, build_number = tpl
    file_path = os.path.join(tempdir(), 'argus', branch, build_type, '{}.json'.format(build_number))

    try:
        if not os.path.exists(file_path):
            request.URLopener().retrieve(
                '{}/job/{}-{}-{}/{}/testReport/api/json'.format(Config.JENKINS_URL,
                                                                Config.JENKINS_PROJECT, branch,
                                                                build_type, build_number),
                file_path)
    except IOError as e:
        print('Can not download {}'.format(build_number))
        print(e)


def get_connection_name(filename: str) -> str:
    """
    Get the name of a connection from the name of its data file.

    :param filename: The name of the serialized data file
    :return: The connection name
    """
    path_str = glob(filename)[0]
    filename_str = path_str.split('/')[-1]
    connection_name = filename_str.split('.')[0]

    return connection_name


class MultiTasker:
    def __init__(self, max_threads: int = 5, stagger_time: float = .2, pause_time: int = 1) -> None:
        """
        Runs jobs asynchronously
        :param max_threads: The max # of threads allowed at a time
        :param stagger_time: The explicit time to wait between running threads
        :param pause_time: The amount of time to wait if the max # of threads are running
        """
        self.running_count = 0
        self.max_threads = max_threads
        self.stagger = stagger_time
        self.pause = pause_time
        self.threads = []  # type: List[threading.Thread]

    def wrap_job(self, target: Callable, args: tuple):
        with threading.Lock():
            self.running_count += 1
        target(*args)
        with threading.Lock():
            self.running_count -= 1

    def add_job(self, target: Callable, args: tuple):
        thread = threading.Thread(target=self.wrap_job, args=(target, args))
        self.threads.append(thread)

    def run(self) -> None:
        for thread in self.threads:
            while self.running_count >= self.max_threads:
                time.sleep(self.pause)
            thread.start()
            time.sleep(self.stagger)

        for thread in self.threads:
            thread.join()


def init_tab_completer():
    readline.parse_and_bind("tab: complete")
    clear_tab_complete_vocabulary()
    delims = readline.get_completer_delims().replace('-', '')
    readline.set_completer_delims(delims)


def clear_tab_complete_vocabulary() -> None:
    """
    Resets vocabulary used for tab completion. It's important to either use the cleanup argument in tab_complete,
    or call this function after setting a vocabulary. This will prevent irrelevant options displaying when the user
    presses tab.
    :return:
    """
    # Matching signature expected in set_completer according to mypy
    def completer(arg1: str, arg2: int) -> Optional[str]:
        return None
    readline.set_completer(completer)


def build_regex_pattern(str_to_build: str):
    pattern = r"{}$".format(str_to_build.replace("*", "(.*?)"))
    return re.compile(pattern)


def tab_complete(func: Callable, args: tuple, word_list: List[str], regex: bool = False, cleanup: bool = False) -> Optional[str]:
    """
    Wraps a function that takes user input with a vocabulary to support tab completion
    :param func: The function to run, ie raw_input, input, get_input
    :param args: The arguments to pass to the input function
    :param word_list: Vocabulary to be passed to the readline module for tab completion
    :param regex: When True, bash-like asterisks are supported (ie job-name-*)
    :param cleanup: When True, vocabulary will be reset upon completion (prevents inaccurate tab completions)
    :return: list of selection matches, if only one match a list will still be returned
    """
    def completer(text: str, state: int) -> Optional[str]:
        options = [word for word in word_list if word.startswith(text)]
        return options[state] if state < len(options) else None

    readline.set_completer(completer)
    value = func(args)

    if cleanup:
        clear_tab_complete_vocabulary()

    if regex and '*' in value:
        pattern = build_regex_pattern(value)
        return next(filter(pattern.match, word_list))
    return value
