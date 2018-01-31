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

"""
Contains all tests for JenkinsConnections
Currently the attribute jenkins_obj is mocked to None, to prevent an API call
"""

from tests.argus_test import Tester
from unittest.mock import patch
from src.jenkins_view import JenkinsView
from src.jenkins_connection import JenkinsConnection
from tests.utils import csv_to_list, parser_to_dict
import os
from src.utils import TEST_DIR


class TestJenkinsConnection(Tester):
    """
    Tests the different features of a JenkinsConnection
    """
    @patch.object(JenkinsConnection, 'create_jenkins_obj', return_value=None)
    def test_save_conf(self, create_jenkins_obj):
        """
        Tests whether JenkinsConnection can save a basic connection with a few jobs/views
        Checks that files were created and are readable
        """
        connection_name = 'test-connection'
        connection_url = 'http://test.jenkins.com/'
        test_view_names = ['test-view-{}'.format(v) for v in range(5)]

        test_data = {}
        test_job_count = 0

        for test_view_name in test_view_names:
            test_job_names = ['test-job-{}'.format(i) for i in range(test_job_count, test_job_count + 3)]
            test_data[test_view_name] = test_job_names
            test_job_count += 3

        connection_conf_path = os.path.join(TEST_DIR, 'conf/jenkins/connections/{}.cfg'.format(connection_name))

        test_jenkins_connection = JenkinsConnection(connection_name, connection_url)
        for key in test_data.keys():
            test_jenkins_connection.jenkins_views[key] = JenkinsView(key, test_data[key])

        test_jenkins_connection.save_connection_config()

        connection_conf = parser_to_dict(connection_conf_path)
        view_names = csv_to_list(connection_conf['JenkinsConnection']['views'])

        self.assertEqual(connection_conf['JenkinsConnection']['url'], connection_url)
        self.assertListEqual(view_names, test_view_names)

        for view_name in view_names:
            view_conf_path = os.path.join(TEST_DIR, 'conf/jenkins/views/{}.cfg'.format(view_name))
            self.assertTrue(os.path.exists(view_conf_path))
            view_conf = parser_to_dict(view_conf_path)
            view_names = csv_to_list(view_conf['JenkinsView']['job_names'])
            self.assertListEqual(view_names, sorted(test_data[view_name]))
