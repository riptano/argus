#!/usr/bin/env python
# -*- mode: Python -*-

from src.main_menu import MainMenu
from src.utils import init_tab_completer

init_tab_completer()
menu = MainMenu()
menu.display()
