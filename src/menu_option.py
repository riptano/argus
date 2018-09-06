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
from typing import Callable, Optional


class MenuOption:

    """
    Contains a string representing a member and a method delegate to call on invocation
    """

    def __init__(self, hotkey: Optional[str], name: Optional[str], method: Optional[Callable], pause: bool = True) -> None:
        """
        :param hotkey: The key that the user will use to select this option.
        :param name: The name of the option that will be printed to the menu.
        :param method: The method that will be invoked when this option is selected.
        :param pause: Optional argument used to denote whether the pause() method will be invoked
            after the entry_method has finished. This should be set to False when pauses have been
            manually inserted into the entry_method, eliminating the need for a pause at the end
            of the method.
        """
        self.hotkey = hotkey
        self.entry_name = name
        self.entry_method = method  # type: Optional[Callable]
        self.needs_pause = pause

    @staticmethod
    def print_blank_line() -> 'MenuOption':
        return MenuOption(None, None, None)

    @staticmethod
    def return_to_previous_menu(previous_menu_call: Callable) -> 'MenuOption':
        return MenuOption('q', 'Return to previous menu', previous_menu_call, pause=False)

    @staticmethod
    def quit_program() -> 'MenuOption':
        return MenuOption('q', 'Quit', exit)
