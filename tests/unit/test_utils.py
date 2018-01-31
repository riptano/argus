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

from tests.argus_test import Tester


class TestUtils(Tester):
    def test_get_connection_name(self):
        """
        Tests that get_connection_name properly parses a .dat filename and returns a connection name.
        """
        from src.utils import get_connection_name

        data_file = os.path.join(self.DATA_DIR, 'connection_name.dat')
        connection_name = get_connection_name(data_file)

        self.assertEqual(connection_name, 'connection_name',
                         "The filename has not been parsed correctly.")
