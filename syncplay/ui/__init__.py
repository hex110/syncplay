from syncplay.utils import isWindowsConsole

if not isWindowsConsole():
    try:
        from syncplay.ui.gui import MainWindow as GraphicalUI
    except (ImportError, AttributeError) as e:
        pass
from syncplay.ui.consoleUI import ConsoleUI


def getUi(graphical=True, passedBar=None):
    if graphical and not isWindowsConsole():
        ui = GraphicalUI(passedBar=passedBar)
    else:
        ui = ConsoleUI()
        ui.setDaemon(True)
        ui.start()
    return ui
