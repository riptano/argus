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
from configparser import RawConfigParser
from typing import TYPE_CHECKING

from src.utils import build_config_file, jenkins_views_dir, save_argus_config

if TYPE_CHECKING:
    from src.jenkins_connection import JenkinsConnection


class JenkinsView:

    def __init__(self, name, job_names=None):
        self.name = name

        if job_names is None:
            self.job_names = []
        else:
            self.job_names = job_names

    def save_view_config(self) -> None:
        config_parser = RawConfigParser()
        config_parser.add_section(SECTION_TITLE)
        config_parser.set(SECTION_TITLE, 'job_names', ','.join(self.job_names))

        save_argus_config(config_parser, build_config_file(jenkins_views_dir, self.name))

    @staticmethod
    def load_view_config(jenkins_connection: 'JenkinsConnection', view_name: str) -> None:
        config_file = build_config_file(jenkins_views_dir, view_name)
        if os.path.isfile(config_file):
            config_parser = RawConfigParser()
            config_parser.read(config_file)
            if config_parser.has_option(SECTION_TITLE, 'job_names'):
                job_names = config_parser.get(SECTION_TITLE, 'job_names').split(',')
                jenkins_view = JenkinsView(view_name, job_names)
            else:
                jenkins_view = JenkinsView(view_name)
            jenkins_connection.jenkins_views[jenkins_view.name] = jenkins_view
        else:
            print('No config file for {}.'.format(view_name))

    def add_job_to_view(self, job_name: str) -> None:
        self.job_names.append(job_name)

    def remove_job_from_view(self, job_name: str) -> None:
        self.job_names.remove(job_name)

    def __repr__(self) -> str:
        return 'JenkinsView(view_name={}, \n\tjob_names={})'.format(self.name, self.job_names)


SECTION_TITLE = JenkinsView.__name__
