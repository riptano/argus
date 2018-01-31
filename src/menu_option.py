class MenuOption:

    """
    Contains a string representing a member and a method delegate to call on invocation
    """

    entry_name = "Unknown"
    entry_method = None

    def __init__(self, hotkey, name, method, pause=True):
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
        self.entry_method = method
        self.needs_pause = pause

    @staticmethod
    def print_blank_line():
        return MenuOption(None, None, None)

    @staticmethod
    def return_to_previous_menu(previous_menu_call):
        return MenuOption('q', 'Return to previous menu', previous_menu_call, pause=False)

    @staticmethod
    def quit_program():
        return MenuOption('q', 'Quit', exit)
