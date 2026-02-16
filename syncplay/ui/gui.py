
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from functools import wraps
from platform import python_version

from twisted.internet import task

from syncplay import utils, constants, version, revision, release_number
from syncplay.messages import getMessage
from syncplay.ui.consoleUI import ConsoleUI
from syncplay.utils import resourcespath
from syncplay.utils import isLinux, isWindows, isMacOS
from syncplay.utils import formatTime, sameFilename, sameFilesize, sameFileduration, RoomPasswordProvider, formatSize, isURL
from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtCore import Qt, QSettings, QSize, QPoint, QUrl, QLine, QDateTime, QStandardPaths
lastCheckedForUpdates = None
from syncplay.ui.theme import Colors


class ConsoleInGUI(ConsoleUI):
    def showMessage(self, message, noTimestamp=False, isMotd=False):
        self._syncplayClient.ui.showMessage(message, noTimestamp=True, isMotd=isMotd)

    def showDebugMessage(self, message):
        self._syncplayClient.ui.showDebugMessage(message)

    def showErrorMessage(self, message, criticalerror=False):
        self._syncplayClient.ui.showErrorMessage(message, criticalerror)

    def updateRoomName(self, room=""): #bob
        self._syncplayClient.ui.updateRoomName(room)

    def getUserlist(self):
        self._syncplayClient.showUserList(self)


class UserlistItemDelegate(QtWidgets.QStyledItemDelegate):
    """Card-style delegate for the user list tree view.

    Draws a colored status dot (ready/not-ready), controller crown,
    and file-switch icons with improved spacing.
    """

    # Status dot colours (derived from theme tokens)
    _DOT_READY    = QtGui.QColor(Colors.SUCCESS)       # Green
    _DOT_NOTREADY = QtGui.QColor(Colors.DANGER)        # Red
    _DOT_UNKNOWN  = QtGui.QColor(Colors.TEXT_MUTED)    # Grey (no info / different room)
    _DOT_RADIUS   = 5  # px

    def __init__(self, view=None):
        self.view = view
        QtWidgets.QStyledItemDelegate.__init__(self)

    def sizeHint(self, option, index):
        size = QtWidgets.QStyledItemDelegate.sizeHint(self, option, index)
        isUserRow = index.parent() != index.parent().parent()
        if isUserRow:
            # Taller rows for user cards
            size.setHeight(max(size.height(), 28))
        if index.column() == constants.USERLIST_GUI_USERNAME_COLUMN:
            size.setWidth(size.width() + constants.USERLIST_GUI_USERNAME_OFFSET)
        return size

    def paint(self, itemQPainter, optionQStyleOptionViewItem, indexQModelIndex):
        column = indexQModelIndex.column()
        rect = optionQStyleOptionViewItem.rect
        midY = int((rect.y() + rect.bottomLeft().y()) / 2)
        isUserRow = indexQModelIndex.parent() != indexQModelIndex.parent().parent()

        if column == constants.USERLIST_GUI_USERNAME_COLUMN:
            currentQAbstractItemModel = indexQModelIndex.model()
            itemQModelIndex = currentQAbstractItemModel.index(
                indexQModelIndex.row(), constants.USERLIST_GUI_USERNAME_COLUMN, indexQModelIndex.parent())

            roomController = currentQAbstractItemModel.data(
                itemQModelIndex, Qt.UserRole + constants.USERITEM_CONTROLLER_ROLE)
            userReady = currentQAbstractItemModel.data(
                itemQModelIndex, Qt.UserRole + constants.USERITEM_READY_ROLE)

            if isUserRow:
                # ── Status dot ──────────────────────────────────────────
                itemQPainter.save()
                itemQPainter.setRenderHint(QtGui.QPainter.Antialiasing, True)
                if userReady is True:
                    dotColor = self._DOT_READY
                elif userReady is False:
                    dotColor = self._DOT_NOTREADY
                else:
                    dotColor = self._DOT_UNKNOWN
                itemQPainter.setBrush(dotColor)
                itemQPainter.setPen(Qt.NoPen)
                dotX = rect.x() + 4 + self._DOT_RADIUS
                itemQPainter.drawEllipse(
                    QtCore.QPointF(dotX, midY),
                    self._DOT_RADIUS, self._DOT_RADIUS)
                itemQPainter.restore()

                # ── Controller crown icon ───────────────────────────────
                controlIconQPixmap = QtGui.QPixmap(resourcespath + "user_key.png")
                if roomController and not controlIconQPixmap.isNull():
                    itemQPainter.drawPixmap(
                        rect.x() + 4 + self._DOT_RADIUS * 2 + 4,
                        midY - 8,
                        controlIconQPixmap.scaled(16, 16, Qt.KeepAspectRatio))

                # Shift text past the dot + icon area
                optionQStyleOptionViewItem.rect.setX(
                    rect.x() + constants.USERLIST_GUI_USERNAME_OFFSET)

        if column == constants.USERLIST_GUI_FILENAME_COLUMN:
            currentQAbstractItemModel = indexQModelIndex.model()
            itemQModelIndex = currentQAbstractItemModel.index(
                indexQModelIndex.row(), constants.USERLIST_GUI_FILENAME_COLUMN, indexQModelIndex.parent())
            fileSwitchRole = currentQAbstractItemModel.data(
                itemQModelIndex, Qt.UserRole + constants.FILEITEM_SWITCH_ROLE)

            if fileSwitchRole == constants.FILEITEM_SWITCH_FILE_SWITCH:
                fileSwitchIconQPixmap = QtGui.QPixmap(resourcespath + "film_go.png")
                itemQPainter.drawPixmap(
                    rect.x(), midY - 8,
                    fileSwitchIconQPixmap.scaled(16, 16, Qt.KeepAspectRatio))
                optionQStyleOptionViewItem.rect.setX(rect.x() + 18)

            elif fileSwitchRole == constants.FILEITEM_SWITCH_STREAM_SWITCH:
                streamSwitchIconQPixmap = QtGui.QPixmap(resourcespath + "world_go.png")
                itemQPainter.drawPixmap(
                    rect.x(), midY - 8,
                    streamSwitchIconQPixmap.scaled(16, 16, Qt.KeepAspectRatio))
                optionQStyleOptionViewItem.rect.setX(rect.x() + 18)

        QtWidgets.QStyledItemDelegate.paint(self, itemQPainter, optionQStyleOptionViewItem, indexQModelIndex)


class AboutDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super(AboutDialog, self).__init__(parent)
        if isMacOS():
            self.setWindowTitle("")
            self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.WindowCloseButtonHint | Qt.CustomizeWindowHint)
        else:
            self.setWindowTitle(getMessage("about-dialog-title"))
            if isWindows():
                self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setWindowIcon(QtGui.QPixmap(resourcespath + 'syncplay.png'))
        nameLabel = QtWidgets.QLabel("<center><strong>Syncplay</strong></center>")
        nameLabel.setFont(QtGui.QFont("Helvetica", 18))
        linkLabel = QtWidgets.QLabel()
        linkLabel.setText(("<center><a href=\"https://syncplay.pl\" style=\"{}\">syncplay.pl</a></center>").format(constants.STYLE_DARK_ABOUT_LINK_COLOR))
        linkLabel.setOpenExternalLinks(True)
        versionExtString = version + revision
        versionLabel = QtWidgets.QLabel(
            "<p><center>" + getMessage("about-dialog-release").format(versionExtString, release_number) +
            "<br />Python " + python_version() + " - PySide6 " + QtCore.__version__ +
            " - Qt " + QtCore.qVersion() + "</center></p>")
        licenseLabel = QtWidgets.QLabel(
            "<center><p>Copyright &copy; 2012&ndash;2025 Syncplay</p><p>" +
            getMessage("about-dialog-license-text") + "</p></center>")
        aboutIcon = QtGui.QIcon()
        aboutIcon.addFile(resourcespath + "syncplayAbout.png")
        aboutIconLabel = QtWidgets.QLabel()
        aboutIconLabel.setPixmap(aboutIcon.pixmap(64, 64))
        aboutLayout = QtWidgets.QGridLayout()
        aboutLayout.addWidget(aboutIconLabel, 0, 0, 3, 4, Qt.AlignHCenter)
        aboutLayout.addWidget(nameLabel, 3, 0, 1, 4)
        aboutLayout.addWidget(linkLabel, 4, 0, 1, 4)
        aboutLayout.addWidget(versionLabel, 5, 0, 1, 4)
        aboutLayout.addWidget(licenseLabel, 6, 0, 1, 4)
        licenseButton = QtWidgets.QPushButton(getMessage("about-dialog-license-button"))
        licenseButton.setAutoDefault(False)
        licenseButton.clicked.connect(self.openLicense)
        aboutLayout.addWidget(licenseButton, 7, 0, 1, 2)
        dependenciesButton = QtWidgets.QPushButton(getMessage("about-dialog-dependencies"))
        dependenciesButton.setAutoDefault(False)
        dependenciesButton.clicked.connect(self.openDependencies)
        aboutLayout.addWidget(dependenciesButton, 7, 2, 1, 2)
        aboutLayout.setVerticalSpacing(10)
        aboutLayout.setSizeConstraint(QtWidgets.QLayout.SetFixedSize)
        self.setSizeGripEnabled(False)
        self.setLayout(aboutLayout)

    def openLicense(self):
        if isWindows():
                QtGui.QDesktopServices.openUrl(QUrl("file:///" + resourcespath + "license.rtf"))
        else:
                QtGui.QDesktopServices.openUrl(QUrl("file://" + resourcespath + "license.rtf"))

    def openDependencies(self):
        if isWindows():
            QtGui.QDesktopServices.openUrl(QUrl("file:///" + resourcespath + "third-party-notices.txt"))
        else:
            QtGui.QDesktopServices.openUrl(QUrl("file://" + resourcespath + "third-party-notices.txt"))


class CertificateDialog(QtWidgets.QDialog):
    def __init__(self, tlsData, parent=None):
        super(CertificateDialog, self).__init__(parent)
        if isMacOS():
            self.setWindowTitle("")
            self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.WindowCloseButtonHint | Qt.CustomizeWindowHint)
        else:
            self.setWindowTitle(getMessage("tls-information-title"))
            if isWindows():
                self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setWindowIcon(QtGui.QPixmap(resourcespath + 'syncplay.png'))
        statusLabel = QtWidgets.QLabel(getMessage("tls-dialog-status-label").format(tlsData["subject"]))
        descLabel = QtWidgets.QLabel(getMessage("tls-dialog-desc-label").format(tlsData["subject"]))
        connDataLabel = QtWidgets.QLabel(getMessage("tls-dialog-connection-label").format(tlsData["protocolVersion"], tlsData["cipher"]))
        certDataLabel = QtWidgets.QLabel(getMessage("tls-dialog-certificate-label").format(tlsData["issuer"], tlsData["expires"]))
        if isMacOS():
            statusLabel.setFont(QtGui.QFont("Helvetica", 12))
            descLabel.setFont(QtGui.QFont("Helvetica", 12))
            connDataLabel.setFont(QtGui.QFont("Helvetica", 12))
            certDataLabel.setFont(QtGui.QFont("Helvetica", 12))
        lockIcon = QtGui.QIcon()
        lockIcon.addFile(resourcespath + "lock_green_dialog.png")
        lockIconLabel = QtWidgets.QLabel()
        lockIconLabel.setPixmap(lockIcon.pixmap(64, 64))
        certLayout = QtWidgets.QGridLayout()
        certLayout.addWidget(lockIconLabel, 1, 0, 3, 1, Qt.AlignLeft | Qt.AlignTop)
        certLayout.addWidget(statusLabel, 0, 1, 1, 3)
        certLayout.addWidget(descLabel, 1, 1, 1, 3)
        certLayout.addWidget(connDataLabel, 2, 1, 1, 3)
        certLayout.addWidget(certDataLabel, 3, 1, 1, 3)
        closeButton = QtWidgets.QPushButton("Close")
        closeButton.setFixedWidth(100)
        closeButton.setAutoDefault(False)
        closeButton.clicked.connect(self.closeDialog)
        certLayout.addWidget(closeButton, 4, 3, 1, 1)
        certLayout.setVerticalSpacing(10)
        certLayout.setSizeConstraint(QtWidgets.QLayout.SetFixedSize)
        self.setSizeGripEnabled(False)
        self.setLayout(certLayout)

    def closeDialog(self):
        self.close()


class MainWindow(QtWidgets.QMainWindow):
    insertPosition = None
    playlistState = []
    updatingPlaylist = False
    playlistIndex = None
    sslInformation = "N/A"
    sslMode = False


    def setPlaylistInsertPosition(self, newPosition):
        if not self.playlist.isEnabled():
            return
        if MainWindow.insertPosition != newPosition:
            MainWindow.insertPosition = newPosition
            self.playlist.forceUpdate()

    class PlaylistItemDelegate(QtWidgets.QStyledItemDelegate):
        """Draws a brand-colored dot for the currently playing file
        and a colored line at the drag-drop insert position."""

        _NOW_PLAYING_COLOR = QtGui.QColor(Colors.BRAND)
        _INSERT_LINE_COLOR = QtGui.QColor(Colors.BRAND)
        _DOT_RADIUS = 4

        def paint(self, itemQPainter, optionQStyleOptionViewItem, indexQModelIndex):
            itemQPainter.save()
            currentQAbstractItemModel = indexQModelIndex.model()
            currentlyPlayingFile = currentQAbstractItemModel.data(indexQModelIndex, Qt.UserRole + constants.PLAYLISTITEM_CURRENTLYPLAYING_ROLE)
            rect = optionQStyleOptionViewItem.rect
            midY = int((rect.y() + rect.bottomLeft().y()) / 2)

            if currentlyPlayingFile:
                # Draw brand-colored "now playing" dot
                itemQPainter.setRenderHint(QtGui.QPainter.Antialiasing, True)
                itemQPainter.setBrush(self._NOW_PLAYING_COLOR)
                itemQPainter.setPen(Qt.NoPen)
                itemQPainter.drawEllipse(
                    QtCore.QPointF(rect.x() + 4 + self._DOT_RADIUS, midY),
                    self._DOT_RADIUS, self._DOT_RADIUS)
                optionQStyleOptionViewItem.rect.setX(rect.x() + 4 + self._DOT_RADIUS * 2 + 4)

            QtWidgets.QStyledItemDelegate.paint(self, itemQPainter, optionQStyleOptionViewItem, indexQModelIndex)

            # Draw drag-drop insert position line
            lineAbove = False
            lineBelow = False
            if MainWindow.insertPosition == 0 and indexQModelIndex.row() == 0:
                lineAbove = True
            elif MainWindow.insertPosition and indexQModelIndex.row() == MainWindow.insertPosition-1:
                lineBelow = True

            if lineAbove or lineBelow:
                pen = QtGui.QPen(self._INSERT_LINE_COLOR, 2)
                itemQPainter.setPen(pen)
                if lineAbove:
                    line = QLine(rect.topLeft(), rect.topRight())
                else:
                    line = QLine(rect.bottomLeft(), rect.bottomRight())
                itemQPainter.drawLine(line)
            itemQPainter.restore()

    class PlaylistGroupBox(QtWidgets.QGroupBox):

        def dragEnterEvent(self, event):
            data = event.mimeData()
            urls = data.urls()
            window = self.parent().parent().parent().parent().parent()
            if urls and urls[0].scheme() == 'file':
                event.acceptProposedAction()
                window.setPlaylistInsertPosition(window.playlist.count())
            else:
                super(MainWindow.PlaylistGroupBox, self).dragEnterEvent(event)

        def dragLeaveEvent(self, event):
            window = self.parent().parent().parent().parent().parent()
            window.setPlaylistInsertPosition(None)

        def dropEvent(self, event):
            window = self.parent().parent().parent().parent().parent()
            if not window.playlist.isEnabled():
                return
            window.setPlaylistInsertPosition(None)
            if QtGui.QDropEvent.proposedAction(event) == Qt.MoveAction:
                QtGui.QDropEvent.setDropAction(event, Qt.CopyAction)  # Avoids file being deleted
            data = event.mimeData()
            urls = data.urls()

            if urls and urls[0].scheme() == 'file':
                indexRow = window.playlist.count() if window.clearedPlaylistNote else 0

                for url in urls[::-1]:
                    dropfilepath = os.path.abspath(str(url.toLocalFile()))
                    if os.path.isfile(dropfilepath):
                        window.addFileToPlaylist(dropfilepath, indexRow)
                    elif os.path.isdir(dropfilepath):
                        window.addFolderToPlaylist(dropfilepath)
            else:
                super(MainWindow.PlaylistWidget, self).dropEvent(event)

    class PlaylistWidget(QtWidgets.QListWidget):
        selfWindow = None
        playlistIndexFilename = None

        def setPlaylistIndexFilename(self, filename):
            if filename != self.playlistIndexFilename:
                self.playlistIndexFilename = filename
            self.updatePlaylistIndexIcon()

        def updatePlaylistIndexIcon(self):
            for item in range(self.count()):
                itemFilename = self.item(item).text()
                isPlayingFilename = itemFilename == self.playlistIndexFilename
                self.item(item).setData(Qt.UserRole + constants.PLAYLISTITEM_CURRENTLYPLAYING_ROLE, isPlayingFilename)
                fileIsAvailable = self.selfWindow.isFileAvailable(itemFilename)
                fileIsUntrusted = self.selfWindow.isItemUntrusted(itemFilename)
                if fileIsUntrusted:
                    self.item(item).setForeground(QtGui.QBrush(QtGui.QColor(Colors.UNTRUSTED)))
                elif fileIsAvailable:
                    self.item(item).setForeground(QtGui.QBrush(self.selfWindow.palette().color(QtGui.QPalette.Text)))
                else:
                    self.item(item).setForeground(QtGui.QBrush(QtGui.QColor(Colors.DIFFERENT_FILE)))
            self.selfWindow._syncplayClient.setFilenameWatchlist(self.selfWindow.newWatchlist)
            self.forceUpdate()

        def setWindow(self, window):
            self.selfWindow = window

        def dragLeaveEvent(self, event):
            window = self.parent().parent().parent().parent().parent().parent()
            window.setPlaylistInsertPosition(None)

        def forceUpdate(self):
            root = self.rootIndex()
            self.dataChanged(root, root)

        def keyPressEvent(self, event):
            if event.key() == Qt.Key_Delete:
                self.remove_selected_items()
            else:
                super(MainWindow.PlaylistWidget, self).keyPressEvent(event)

        def updatePlaylist(self, newPlaylist):
            for index in range(self.count()):
                self.takeItem(0)
            uniquePlaylist = []
            for item in newPlaylist:
                if item not in uniquePlaylist:
                    uniquePlaylist.append(item)
            self.insertItems(0, uniquePlaylist)
            self.updatePlaylistIndexIcon()

        def remove_selected_items(self):
            for item in self.selectedItems():
                self.takeItem(self.row(item))

        def dragEnterEvent(self, event):
            data = event.mimeData()
            urls = data.urls()
            if urls and urls[0].scheme() == 'file':
                event.acceptProposedAction()
            else:
                super(MainWindow.PlaylistWidget, self).dragEnterEvent(event)

        def dragMoveEvent(self, event):
            data = event.mimeData()
            urls = data.urls()
            if urls and urls[0].scheme() == 'file':
                event.acceptProposedAction()
                indexRow = self.indexAt(event.pos()).row()
                window = self.parent().parent().parent().parent().parent().parent()
                if indexRow == -1 or not window.clearedPlaylistNote:
                    indexRow = window.playlist.count()
                window.setPlaylistInsertPosition(indexRow)
            else:
                super(MainWindow.PlaylistWidget, self).dragMoveEvent(event)

        def dropEvent(self, event):
            window = self.parent().parent().parent().parent().parent().parent()
            if not window.playlist.isEnabled():
                return
            window.setPlaylistInsertPosition(None)
            if QtGui.QDropEvent.proposedAction(event) == Qt.MoveAction:
                QtGui.QDropEvent.setDropAction(event, Qt.CopyAction)  # Avoids file being deleted
            data = event.mimeData()
            urls = data.urls()

            if urls and urls[0].scheme() == 'file':
                indexRow = self.indexAt(event.pos()).row()
                if not window.clearedPlaylistNote:
                    indexRow = 0
                if indexRow == -1:
                    indexRow = window.playlist.count()
                for url in urls[::-1]:
                    dropfilepath = os.path.abspath(str(url.toLocalFile()))
                    if os.path.isfile(dropfilepath):
                        window.addFileToPlaylist(dropfilepath, indexRow)
                    elif os.path.isdir(dropfilepath):
                        window.addFolderToPlaylist(dropfilepath)
            else:
                super(MainWindow.PlaylistWidget, self).dropEvent(event)

    class topSplitter(QtWidgets.QSplitter):
        def createHandle(self):
            return self.topSplitterHandle(self.orientation(), self)

        class topSplitterHandle(QtWidgets.QSplitterHandle):
            def mouseReleaseEvent(self, event):
                QtWidgets.QSplitterHandle.mouseReleaseEvent(self, event)
                self.parent().parent().parent().updateListGeometry()

            def mouseMoveEvent(self, event):
                QtWidgets.QSplitterHandle.mouseMoveEvent(self, event)
                self.parent().parent().parent().updateListGeometry()

    def needsClient(f):  # @NoSelf
        @wraps(f)
        def wrapper(self, *args, **kwds):
            if not self._syncplayClient:
                self.showDebugMessage("Tried to use client before it was ready!")
                return
            return f(self, *args, **kwds)
        return wrapper

    def fillRoomsCombobox(self):
        previousRoomSelection = self.roomsCombobox.currentText()
        self.roomsCombobox.clear()
        for roomListValue in self.config['roomList']:
            self.roomsCombobox.addItem(roomListValue)
        for room in self.currentRooms:
            if room not in self.config['roomList']:
                self.roomsCombobox.addItem(room)
        self.roomsCombobox.setEditText(previousRoomSelection)

    def addRoomToList(self, newRoom=None):
        if newRoom is None:
            newRoom = self.roomsCombobox.currentText()
        if not newRoom:
            return
        roomList = self.config['roomList']
        if newRoom not in roomList:
            roomList.append(newRoom)
        self.config['roomList'] = roomList
        roomList = sorted(roomList)
        self._syncplayClient.setRoomList(roomList)
        self.relistRoomList(roomList)

    def addClient(self, client):
        self._syncplayClient = client
        if self.console:
            self.console.addClient(client)
        self.config = self._syncplayClient.getConfig()
        self.roomsCombobox.setEditText(self._syncplayClient.getRoom())
        self.fillRoomsCombobox()
        try:
            self.playlistGroup.blockSignals(True)
            self.playlistGroup.setChecked(self.config['sharedPlaylistEnabled'])
            self.playlistGroup.blockSignals(False)
            self._syncplayClient.setMediaDirectories(self.config["mediaSearchDirectories"])
            if not self.config["mediaSearchDirectories"]:
                self._syncplayClient.ui.showErrorMessage(getMessage("no-media-directories-error"))
            self.updateReadyState(self.config['readyAtStart'])
            autoplayInitialState = self.config['autoplayInitialState']
            if autoplayInitialState is not None:
                self.autoplayPushButton.blockSignals(True)
                self.autoplayPushButton.setChecked(autoplayInitialState)
                self.autoplayPushButton.blockSignals(False)
            if self.config['autoplayMinUsers'] > 1:
                self.autoplayThresholdSpinbox.blockSignals(True)
                self.autoplayThresholdSpinbox.setValue(self.config['autoplayMinUsers'])
                self.autoplayThresholdSpinbox.blockSignals(False)
            self.changeAutoplayState()
            self.changeAutoplayThreshold()
            self.updateAutoPlayIcon()
        except:
            self.showErrorMessage("Failed to load some settings.")
        self.automaticUpdateCheck()

    def promptFor(self, prompt=">", message=""):
        # TODO: Prompt user
        return None

    def setFeatures(self, featureList):
        if not featureList["readiness"]:
            self.readyPushButton.setEnabled(False)
        if not featureList["chat"]:
            self.chatFrame.setEnabled(False)
            self.chatInput.setReadOnly(True)
        if not featureList["sharedPlaylists"]:
            self.playlistGroup.setEnabled(False)
        self.chatInput.setMaxLength(constants.MAX_CHAT_MESSAGE_LENGTH)
        #self.roomsCombobox.setMaxLength(constants.MAX_ROOM_NAME_LENGTH)

    def setSSLMode(self, sslMode, sslInformation):
        self.sslMode = sslMode
        self.sslInformation = sslInformation
        self.sslButton.setVisible(sslMode)

    def getSSLInformation(self):
        return self.sslInformation

    def showMessage(self, message, noTimestamp=False, isMotd=False):
        message = str(message)
        username = None
        messageWithUsername = re.match(constants.MESSAGE_WITH_USERNAME_REGEX, message, re.UNICODE)
        if messageWithUsername:
            username = messageWithUsername.group("username")
            message = messageWithUsername.group("message")
        message = message.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
        if username:
            message = constants.STYLE_USER_MESSAGE.format(constants.STYLE_USERNAME, username, message)
        # When showing a MOTD, escape spaces and use a monospace font to preserve the look of ASCII art.
        if isMotd:
            message = message.replace(" ", "&nbsp;")
            message = "<code>{}</code>".format(message)
        message = message.replace("\n", "<br />")
        if noTimestamp:
            self.newMessage("{}<br />".format(message))
        else:
            self.newMessage(time.strftime(constants.UI_TIME_FORMAT, time.localtime()) + message + "<br />")

    @needsClient
    def getFileSwitchState(self, filename):
        if filename:
            if filename == getMessage("nofile-note"):
                return constants.FILEITEM_SWITCH_NO_SWITCH
            if self._syncplayClient.getCurrentFile() and utils.sameFilename(filename, self._syncplayClient.getCurrentFile()['name']):
                return constants.FILEITEM_SWITCH_NO_SWITCH
            if isURL(filename):
                return constants.FILEITEM_SWITCH_STREAM_SWITCH
            elif filename not in self.newWatchlist:
                if self._syncplayClient.findFilepath(filename):
                    return constants.FILEITEM_SWITCH_FILE_SWITCH
                else:
                    self.newWatchlist.extend([filename])
        return constants.FILEITEM_SWITCH_NO_SWITCH

    @needsClient
    def isItemUntrusted(self, filename):
        return isURL(filename) and not self._syncplayClient.isURITrusted(filename)

    @needsClient
    def isFileAvailable(self, filename):
        if filename:
            if filename == getMessage("nofile-note"):
                return None
            if isURL(filename):
                return True
            elif filename not in self.newWatchlist:
                if self._syncplayClient.findFilepath(filename):
                    return True
                else:
                    self.newWatchlist.extend([filename])
        return False

    @needsClient
    def showUserList(self, currentUser, rooms):
        self._usertreebuffer = QtGui.QStandardItemModel()
        self._usertreebuffer.setHorizontalHeaderLabels(
            (
                getMessage("roomuser-heading-label"), getMessage("size-heading-label"),
                getMessage("duration-heading-label"), getMessage("filename-heading-label")
            ))
        usertreeRoot = self._usertreebuffer.invisibleRootItem()
        if (
            self._syncplayClient.getCurrentFile() and
            self._syncplayClient.getCurrentFile() and
            os.path.isfile(self._syncplayClient.getCurrentFile()["path"])
        ):
            self._syncplayClient.setCurrentMediaDirectory(os.path.dirname(self._syncplayClient.getCurrentFile()["path"]))

        self.currentRooms = []
        for room in rooms:
            self.currentRooms.append(room)
            if self.hideEmptyRooms:
                foundEmptyRooms = False
                for user in rooms[room]:
                    if user.username.strip() == "":
                        foundEmptyRooms = True
                if foundEmptyRooms:
                    continue
            self.newWatchlist = []
            roomitem = QtGui.QStandardItem(room)
            font = QtGui.QFont()
            font.setItalic(True)
            if room == currentUser.room:
                font.setWeight(QtGui.QFont.Bold)
            roomitem.setFont(font)
            roomitem.setFlags(roomitem.flags() & ~Qt.ItemIsEditable)
            usertreeRoot.appendRow(roomitem)
            isControlledRoom = RoomPasswordProvider.isControlledRoom(room)

            if isControlledRoom:
                if room == currentUser.room and currentUser.isController():
                    roomitem.setIcon(QtGui.QPixmap(resourcespath + 'lock_open.png'))
                else:
                    roomitem.setIcon(QtGui.QPixmap(resourcespath + 'lock.png'))
            else:
                roomitem.setIcon(QtGui.QPixmap(resourcespath + 'chevrons_right.png'))

            for user in rooms[room]:
                if user.username.strip() == "":
                    continue
                useritem = QtGui.QStandardItem(user.username)
                isController = user.isController()
                sameRoom = room == currentUser.room
                if sameRoom:
                    isReadyWithFile = user.isReadyWithFile()
                else:
                    isReadyWithFile = None
                useritem.setData(isController, Qt.UserRole + constants.USERITEM_CONTROLLER_ROLE)
                useritem.setData(isReadyWithFile, Qt.UserRole + constants.USERITEM_READY_ROLE)
                if user.file:
                    filesizeitem = QtGui.QStandardItem(formatSize(user.file['size']))
                    filedurationitem = QtGui.QStandardItem("({})".format(formatTime(user.file['duration'])))
                    filename = user.file['name']
                    if isURL(filename):
                        filename = urllib.parse.unquote(filename)
                    filenameitem = QtGui.QStandardItem(filename)
                    fileSwitchState = self.getFileSwitchState(user.file['name']) if room == currentUser.room else None
                    if fileSwitchState != constants.FILEITEM_SWITCH_NO_SWITCH:
                        filenameTooltip = getMessage("switch-to-file-tooltip").format(filename)
                    else:
                        filenameTooltip = filename
                    filenameitem.setToolTip(filenameTooltip)
                    filenameitem.setData(fileSwitchState, Qt.UserRole + constants.FILEITEM_SWITCH_ROLE)
                    if currentUser.file:
                        sameName = sameFilename(user.file['name'], currentUser.file['name'])
                        sameSize = sameFilesize(user.file['size'], currentUser.file['size'])
                        sameDuration = sameFileduration(user.file['duration'], currentUser.file['duration'])
                        underlinefont = QtGui.QFont()
                        underlinefont.setUnderline(True)
                        differentItemColor = Colors.DIFFERENT_FILE
                        if sameRoom:
                            if not sameName:
                                filenameitem.setForeground(QtGui.QBrush(QtGui.QColor(differentItemColor)))
                                filenameitem.setFont(underlinefont)
                            if not sameSize:
                                if formatSize(user.file['size']) == formatSize(currentUser.file['size']):
                                    filesizeitem = QtGui.QStandardItem(formatSize(user.file['size'], precise=True))
                                filesizeitem.setFont(underlinefont)
                                filesizeitem.setForeground(QtGui.QBrush(QtGui.QColor(differentItemColor)))
                            if not sameDuration:
                                filedurationitem.setForeground(QtGui.QBrush(QtGui.QColor(differentItemColor)))
                                filedurationitem.setFont(underlinefont)
                else:
                    filenameitem = QtGui.QStandardItem(getMessage("nofile-note"))
                    filedurationitem = QtGui.QStandardItem("")
                    filesizeitem = QtGui.QStandardItem("")
                    if room == currentUser.room:
                        filenameitem.setForeground(QtGui.QBrush(QtGui.QColor(Colors.NO_FILE)))
                font = QtGui.QFont()
                if currentUser.username == user.username:
                    font.setWeight(QtGui.QFont.Bold)
                    self.updateReadyState(currentUser.isReadyWithFile())
                if isControlledRoom and not isController:
                    useritem.setForeground(QtGui.QBrush(QtGui.QColor(Colors.NOT_CONTROLLER)))
                useritem.setFont(font)
                useritem.setFlags(useritem.flags() & ~Qt.ItemIsEditable)
                filenameitem.setFlags(filenameitem.flags() & ~Qt.ItemIsEditable)
                filesizeitem.setFlags(filesizeitem.flags() & ~Qt.ItemIsEditable)
                filedurationitem.setFlags(filedurationitem.flags() & ~Qt.ItemIsEditable)
                roomitem.appendRow((useritem, filesizeitem, filedurationitem, filenameitem))
        self.listTreeModel = self._usertreebuffer
        self.listTreeView.setModel(self.listTreeModel)
        self.listTreeView.setItemDelegate(UserlistItemDelegate(view=self.listTreeView))
        self.listTreeView.setItemsExpandable(False)
        self.listTreeView.setRootIsDecorated(False)
        self.listTreeView.expandAll()
        self.updateListGeometry()
        self._syncplayClient.setFilenameWatchlist(self.newWatchlist)
        self.fillRoomsCombobox()

    @needsClient
    def undoPlaylistChange(self):
        self._syncplayClient.undoPlaylistChange()

    @needsClient
    def shuffleRemainingPlaylist(self):
        self._syncplayClient.shuffleRemainingPlaylist()

    @needsClient
    def shuffleEntirePlaylist(self):
        self._syncplayClient.shuffleEntirePlaylist()

    @needsClient
    def openPlaylistMenu(self, position):
        indexes = self.playlist.selectedIndexes()
        if len(indexes) > 0:
            item = self.playlist.selectedIndexes()[0]
        else:
            item = None
        menu = QtWidgets.QMenu()

        if item:
            firstFile = item.sibling(item.row(), 0).data()
            pathFound = self._syncplayClient.findFilepath(firstFile) if not isURL(firstFile) else None
            if self._syncplayClient.getCurrentFile() is None or firstFile != self._syncplayClient.getCurrentFile()["name"]:
                if isURL(firstFile):
                    menu.addAction(QtGui.QPixmap(resourcespath + "world_go.png"), getMessage("openstreamurl-menu-label"), lambda: self.openFile(firstFile, resetPosition=True, fromUser=True))
                elif pathFound:
                        menu.addAction(QtGui.QPixmap(resourcespath + "film_go.png"), getMessage("openmedia-menu-label"), lambda: self.openFile(pathFound, resetPosition=True, fromUser=True))
            if pathFound:
                menu.addAction(QtGui.QPixmap(resourcespath + "folder_film.png"),
                               getMessage('open-containing-folder'),
                               lambda: utils.open_system_file_browser(pathFound))
            if self._syncplayClient.isUntrustedTrustableURI(firstFile):
                domain = utils.getDomainFromURL(firstFile)
                if domain:
                    menu.addAction(QtGui.QPixmap(resourcespath + "shield_add.png"), getMessage("addtrusteddomain-menu-label").format(domain), lambda: self.addTrustedDomain(domain))
            menu.addAction(QtGui.QPixmap(resourcespath + "delete.png"), getMessage("removefromplaylist-menu-label"), lambda: self.deleteSelectedPlaylistItems())
            menu.addSeparator()
        menu.addAction(QtGui.QPixmap(resourcespath + "arrow_switch.png"), getMessage("shuffleremainingplaylist-menu-label"), lambda: self.shuffleRemainingPlaylist())
        menu.addAction(QtGui.QPixmap(resourcespath + "arrow_switch.png"), getMessage("shuffleentireplaylist-menu-label"), lambda: self.shuffleEntirePlaylist())
        menu.addAction(QtGui.QPixmap(resourcespath + "arrow_undo.png"), getMessage("undoplaylist-menu-label"), lambda: self.undoPlaylistChange())
        menu.addAction(QtGui.QPixmap(resourcespath + "film_edit.png"), getMessage("editplaylist-menu-label"), lambda: self.openEditPlaylistDialog())
        menu.addAction(QtGui.QPixmap(resourcespath + "film_add.png"), getMessage("addfilestoplaylist-menu-label"), lambda: self.OpenAddFilesToPlaylistDialog())
        menu.addAction(QtGui.QPixmap(resourcespath + "world_add.png"), getMessage("addurlstoplaylist-menu-label"), lambda: self.OpenAddURIsToPlaylistDialog())
        menu.addSeparator()
        menu.addAction(getMessage("loadplaylistfromfile-menu-label"),lambda: self.OpenLoadPlaylistFromFileDialog()) # TODO: Add icon
        menu.addAction("Load and shuffle playlist from file",lambda: self.OpenLoadPlaylistFromFileDialog(shuffle=True))  # TODO: Add icon and messages_en
        menu.addAction(getMessage("saveplaylisttofile-menu-label"),lambda: self.OpenSavePlaylistToFileDialog()) # TODO: Add icon
        menu.addSeparator()
        menu.addAction(QtGui.QPixmap(resourcespath + "film_folder_edit.png"), getMessage("setmediadirectories-menu-label"), lambda: self.openSetMediaDirectoriesDialog())
        menu.addAction(QtGui.QPixmap(resourcespath + "shield_edit.png"), getMessage("settrusteddomains-menu-label"), lambda: self.openSetTrustedDomainsDialog())
        menu.exec_(self.playlist.viewport().mapToGlobal(position))

    def openRoomMenu(self, position):
        # TODO: Deselect items after right click
        indexes = self.listTreeView.selectedIndexes()
        if len(indexes) > 0:
            item = self.listTreeView.selectedIndexes()[0]
        else:
            return

        menu = QtWidgets.QMenu()
        username = item.sibling(item.row(), 0).data()

        if len(username) < 15:
            shortUsername = username
        else:
            shortUsername = "{}...".format(username[0:12])

        if username == self._syncplayClient.getCurrentUsername():
            addUsersFileToPlaylistLabelText = getMessage("addyourfiletoplaylist-menu-label")
            addUsersStreamToPlaylistLabelText = getMessage("addyourstreamstoplaylist-menu-label")
        else:
            addUsersFileToPlaylistLabelText = getMessage("addotherusersfiletoplaylist-menu-label").format(shortUsername)
            addUsersStreamToPlaylistLabelText = getMessage("addotherusersstreamstoplaylist-menu-label").format(shortUsername)

        filename = item.sibling(item.row(), 3).data()
        while item.parent().row() != -1:
            item = item.parent()
        roomToJoin = item.sibling(item.row(), 0).data()
        if roomToJoin != self._syncplayClient.getRoom():
            menu.addAction(getMessage("joinroom-menu-label").format(roomToJoin), lambda: self.joinRoom(roomToJoin))
        elif username and filename and filename != getMessage("nofile-note"):
            if self.config['sharedPlaylistEnabled'] and not self.isItemInPlaylist(filename):
                if isURL(filename):
                    menu.addAction(QtGui.QPixmap(resourcespath + "world_add.png"), addUsersStreamToPlaylistLabelText, lambda: self.addStreamToPlaylist(filename))
                else:
                    menu.addAction(QtGui.QPixmap(resourcespath + "film_add.png"), addUsersFileToPlaylistLabelText, lambda: self.addStreamToPlaylist(filename))

            if self._syncplayClient.getCurrentFile() is None or filename != self._syncplayClient.getCurrentFile()["name"]:
                if isURL(filename):
                    menu.addAction(QtGui.QPixmap(resourcespath + "world_go.png"), getMessage("openusersstream-menu-label").format(shortUsername), lambda: self.openFile(filename, resetPosition=False, fromUser=True))
                else:
                    pathFound = self._syncplayClient.findFilepath(filename)
                    if pathFound:
                        menu.addAction(QtGui.QPixmap(resourcespath + "film_go.png"), getMessage("openusersfile-menu-label").format(shortUsername), lambda: self.openFile(pathFound, resetPosition=False, fromUser=True))
            if self._syncplayClient.isUntrustedTrustableURI(filename):
                domain = utils.getDomainFromURL(filename)
                if domain:
                    menu.addAction(QtGui.QPixmap(resourcespath + "shield_add.png"), getMessage("addtrusteddomain-menu-label").format(domain), lambda: self.addTrustedDomain(domain))

            if not isURL(filename) and filename != getMessage("nofile-note"):
                path = self._syncplayClient.findFilepath(filename)
                if path:
                    menu.addAction(QtGui.QPixmap(resourcespath + "folder_film.png"), getMessage('open-containing-folder'), lambda: utils.open_system_file_browser(path))

        if roomToJoin == self._syncplayClient.getRoom() and self._syncplayClient.canCurrentUserControl() and self._syncplayClient.isReadinessSupported(requiresOtherUsers=False) and self._syncplayClient.getServerFeatures()["setOthersReadiness"]:
            if self._syncplayClient.isUserReady(username):
                addSetUserAsReadyText = getMessage("setasnotready-menu-label").format(shortUsername)
                menu.addAction(QtGui.QPixmap(resourcespath + "cross.png"), addSetUserAsReadyText, lambda: self._syncplayClient.setOthersReadiness(username, False))
            else:
                addSetUserAsNotReadyText = getMessage("setasready-menu-label").format(shortUsername)
                menu.addAction(QtGui.QPixmap(resourcespath + "tick.png"), addSetUserAsNotReadyText, lambda: self._syncplayClient.setOthersReadiness(username, True))
        menu.exec_(self.listTreeView.viewport().mapToGlobal(position))

    def updateListGeometry(self):
        try:
            roomtocheck = 0
            while self.listTreeModel.item(roomtocheck):
                self.listTreeView.setFirstColumnSpanned(roomtocheck, self.listTreeView.rootIndex(), True)
                roomtocheck += 1
            self.listTreeView.header().setStretchLastSection(False)
            self.listTreeView.header().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
            self.listTreeView.header().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
            self.listTreeView.header().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
            self.listTreeView.header().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
            NarrowTabsWidth = self.listTreeView.header().sectionSize(0)+self.listTreeView.header().sectionSize(1)+self.listTreeView.header().sectionSize(2)
            if self.listTreeView.header().width() < (NarrowTabsWidth+self.listTreeView.header().sectionSize(3)):
                self.listTreeView.header().resizeSection(3, self.listTreeView.header().width()-NarrowTabsWidth)
            else:
                self.listTreeView.header().setSectionResizeMode(3, QtWidgets.QHeaderView.Stretch)
            self.listTreeView.expandAll()
        except:
            pass

    def updateReadyState(self, newState):
        oldState = self.readyPushButton.isChecked()
        if newState != oldState and newState is not None:
            self.readyPushButton.blockSignals(True)
            self.readyPushButton.setChecked(newState)
            self.readyPushButton.blockSignals(False)
        self.updateReadyIcon()

    @needsClient
    def playlistItemClicked(self, item):
        # TODO: Integrate into client.py code
        filename = item.data()
        if self._isTryingToChangeToCurrentFile(filename):
            return
        if isURL(filename):
            self._syncplayClient.openFile(filename, resetPosition=True)
        else:
            pathFound = self._syncplayClient.findFilepath(filename, highPriority=True)
            if pathFound:
                self._syncplayClient.openFile(pathFound, resetPosition=True)
            else:
                self._syncplayClient.ui.showErrorMessage(getMessage("cannot-find-file-for-playlist-switch-error").format(filename))

    def _isTryingToChangeToCurrentFile(self, filename):
        if self._syncplayClient.getCurrentFile() and filename == self._syncplayClient.getCurrentFile()["name"]:
            self.showDebugMessage("File change request ignored (Syncplay should not be asked to change to current filename)")
            return True
        else:
            return False

    def roomClicked(self, item):
        username = item.sibling(item.row(), 0).data()
        filename = item.sibling(item.row(), 3).data()
        while item.parent().row() != -1:
            item = item.parent()
        roomToJoin = item.sibling(item.row(), 0).data()
        if roomToJoin != self._syncplayClient.getRoom():
            self.joinRoom(item.sibling(item.row(), 0).data())
        elif username and filename and username != self._syncplayClient.getCurrentUsername():
            if self._isTryingToChangeToCurrentFile(filename):
                return
            if isURL(filename):
                self._syncplayClient.openFile(filename)
            else:
                pathFound = self._syncplayClient.findFilepath(filename, highPriority=True)
                if pathFound:
                    self._syncplayClient.openFile(pathFound)
                else:
                    self._syncplayClient.updateFileSwitchInfo()
                    self.showErrorMessage(getMessage("switch-file-not-found-error").format(filename))

    @needsClient
    def userListChange(self):
        self._syncplayClient.showUserList()

    def fileSwitchFoundFiles(self):
        self._syncplayClient.showUserList()
        self.playlist.updatePlaylistIndexIcon()

    def updateRoomName(self, room=""):
        self.roomsCombobox.setEditText(room)
        try:
            if self.config['autosaveJoinsToList']:
                self.addRoomToList(room)
        except:
            pass

    def showDebugMessage(self, message):
        print(message)

    def showErrorMessage(self, message, criticalerror=False):
        message = str(message)
        if criticalerror:
            QtWidgets.QMessageBox.critical(self, "Syncplay", message)
        message = message.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
        message = message.replace("&lt;a href=&quot;https://syncplay.pl/trouble&quot;&gt;", '<a href="https://syncplay.pl/trouble">').replace("&lt;/a&gt;", "</a>")
        message = message.replace("&lt;a href=&quot;https://mpv.io/&quot;&gt;", '<a href="https://mpv.io/">').replace("&lt;/a&gt;", "</a>")
        message = message.replace("&lt;a href=&quot;https://github.com/stax76/mpv.net/&quot;&gt;", '<a href="https://github.com/stax76/mpv.net/">').replace("&lt;/a&gt;", "</a>")
        message = message.replace("\n", "<br />")
        message = "<span style=\"{}\">".format(constants.STYLE_DARK_ERRORNOTIFICATION) + message + "</span>"
        self.newMessage(time.strftime(constants.UI_TIME_FORMAT, time.localtime()) + message + "<br />")

    @needsClient
    def joinRoom(self, room=None):
        if room is None:
            room = self.roomsCombobox.currentText()
        if room == "":
            if self._syncplayClient.getCurrentFile():
                room = self._syncplayClient.getCurrentFile()["name"]
            else:
                room = self._syncplayClient.getDefaultRoom()
        self.roomsCombobox.setEditText(room)
        if room != self._syncplayClient.getRoom():
            self._syncplayClient.setRoom(room, resetAutoplay=True)
            self._syncplayClient.sendRoom()
            if self.config['autosaveJoinsToList']:
                self.addRoomToList(room)

    def seekPositionDialog(self):
        seekTime, ok = QtWidgets.QInputDialog.getText(
            self, getMessage("seektime-menu-label"),
            getMessage("seektime-msgbox-label"), QtWidgets.QLineEdit.Normal,
            "0:00")
        if ok and seekTime != '':
            self.seekPosition(seekTime)

    def seekFromButton(self):
        self.seekPosition(self.seekInput.text())

    @needsClient
    def seekPosition(self, seekTime):
        s = re.match(constants.UI_SEEK_REGEX, seekTime)
        if s:
            sign = self._extractSign(s.group('sign'))
            t = utils.parseTime(s.group('time'))
            if t is None:
                return
            if sign:
                t = self._syncplayClient.getGlobalPosition() + sign * t
            self._syncplayClient.setPosition(t)
        else:
            self.showErrorMessage(getMessage("invalid-seek-value"))

    @needsClient
    def undoSeek(self):
        tmp_pos = self._syncplayClient.getPlayerPosition()
        self._syncplayClient.setPosition(self._syncplayClient.getPlayerPositionBeforeLastSeek())
        self._syncplayClient.setPlayerPositionBeforeLastSeek(tmp_pos)

    @needsClient
    def togglePause(self):
        self._syncplayClient.setPaused(not self._syncplayClient.getPlayerPaused())

    @needsClient
    def play(self):
        self._syncplayClient.setPaused(False)

    @needsClient
    def pause(self):
        self._syncplayClient.setPaused(True)

    @needsClient
    def reconnectToServer(self):
        """
        Trigger a manual reconnection using the client's built-in retry mechanism.
        This is simpler and more reliable than doing a complete restart.
        """
        try:
            if self._syncplayClient:
                self._syncplayClient.manualReconnect()
            else:
                self.showErrorMessage(getMessage("connection-failed-notification"))
        except Exception as e:
            self.showErrorMessage(getMessage("reconnect-failed-error").format(str(e)))

    def exitSyncplay(self):
        self._syncplayClient.stop()

    def closeEvent(self, event):
        self.exitSyncplay()
        self.saveSettings()

    def loadMediaBrowseSettings(self):
        settings = QSettings("Syncplay", "MediaBrowseDialog")
        settings.beginGroup("MediaBrowseDialog")
        self.mediadirectory = settings.value("mediadir", "")
        settings.endGroup()

    def saveMediaBrowseSettings(self):
        settings = QSettings("Syncplay", "MediaBrowseDialog")
        settings.beginGroup("MediaBrowseDialog")
        settings.setValue("mediadir", self.mediadirectory)
        settings.endGroup()

    def getInitialMediaDirectory(self, includeUserSpecifiedDirectories=True):
        if self.config["mediaSearchDirectories"] and os.path.isdir(self.config["mediaSearchDirectories"][0]) and includeUserSpecifiedDirectories:
            defaultdirectory = self.config["mediaSearchDirectories"][0]
        elif includeUserSpecifiedDirectories and os.path.isdir(self.mediadirectory):
            defaultdirectory = self.mediadirectory
        elif os.path.isdir(QStandardPaths.standardLocations(QStandardPaths.MoviesLocation)[0]):
            defaultdirectory = QStandardPaths.standardLocations(QStandardPaths.MoviesLocation)[0]
        elif os.path.isdir(QStandardPaths.standardLocations(QStandardPaths.HomeLocation)[0]):
            defaultdirectory = QStandardPaths.standardLocations(QStandardPaths.HomeLocation)[0]
        else:
            defaultdirectory = ""
        return defaultdirectory

    @needsClient
    def browseMediapath(self):
        if self._syncplayClient.hasCustomOpenDialog():
            self._syncplayClient.openCustomOpenDialog()
            return

        self.loadMediaBrowseSettings()
        options = QtWidgets.QFileDialog.Options()
        self.mediadirectory = ""
        currentdirectory = os.path.dirname(self._syncplayClient.getCurrentFile()["path"]) if self._syncplayClient.getCurrentFile() else None
        if currentdirectory and os.path.isdir(currentdirectory):
            defaultdirectory = currentdirectory
        else:
            defaultdirectory = self.getInitialMediaDirectory()
        browserfilter = "All files (*)"
        fileName, filtr = QtWidgets.QFileDialog.getOpenFileName(
            self, getMessage("browseformedia-label"), defaultdirectory,
            browserfilter, "", options)
        if fileName:
            if isWindows():
                fileName = fileName.replace("/", "\\")
            self.mediadirectory = os.path.dirname(fileName)
            self._syncplayClient.setCurrentMediaDirectory(self.mediadirectory)
            self.saveMediaBrowseSettings()
            self._syncplayClient.openFile(fileName, resetPosition=False, fromUser=True)

    @needsClient
    def OpenAddFilesToPlaylistDialog(self):
        if self._syncplayClient.hasCustomOpenDialog():
            self._syncplayClient.openCustomOpenDialog()
            return

        self.loadMediaBrowseSettings()
        options = QtWidgets.QFileDialog.Options()
        self.mediadirectory = ""
        currentdirectory = os.path.dirname(self._syncplayClient.getCurrentFile()["path"]) if self._syncplayClient.getCurrentFile() else None
        if currentdirectory and os.path.isdir(currentdirectory):
            defaultdirectory = currentdirectory
        else:
            defaultdirectory = self.getInitialMediaDirectory()
        browserfilter = "All files (*)"
        fileNames, filtr = QtWidgets.QFileDialog.getOpenFileNames(
            self, getMessage("browseformedia-label"), defaultdirectory,
            browserfilter, "", options)
        self.updatingPlaylist = True
        if fileNames:
            for fileName in fileNames:
                if isWindows():
                    fileName = fileName.replace("/", "\\")
                self.mediadirectory = os.path.dirname(fileName)
                self._syncplayClient.setCurrentMediaDirectory(self.mediadirectory)
                self.saveMediaBrowseSettings()
                self.addFileToPlaylist(fileName)
        self.updatingPlaylist = False
        self.playlist.updatePlaylist(self.getPlaylistState())

    @needsClient
    def OpenLoadPlaylistFromFileDialog(self, shuffle=False):
        self.loadMediaBrowseSettings()
        options = QtWidgets.QFileDialog.Options()
        self.mediadirectory = ""
        currentdirectory = os.path.dirname(self._syncplayClient.getCurrentFile()["path"]) if self._syncplayClient.getCurrentFile() else None
        if currentdirectory and os.path.isdir(currentdirectory):
            defaultdirectory = currentdirectory
        else:
            defaultdirectory = self.getInitialMediaDirectory()
        browserfilter = "Playlists (*.txt *.m3u8)"
        filepath, filtr = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load playlist from file", defaultdirectory,
            browserfilter, "", options) # TODO: Note Shuffle and move to messages_en
        if os.path.isfile(filepath):
            self._syncplayClient.loadPlaylistFromFile(filepath, shuffle=shuffle)
            self.playlist.updatePlaylist(self.getPlaylistState())

    @needsClient
    def OpenSavePlaylistToFileDialog(self):
        self.loadMediaBrowseSettings()
        options = QtWidgets.QFileDialog.Options()
        self.mediadirectory = ""
        currentdirectory = os.path.dirname(self._syncplayClient.getCurrentFile()["path"]) if self._syncplayClient.getCurrentFile() else None
        if currentdirectory and os.path.isdir(currentdirectory):
            defaultdirectory = currentdirectory
        else:
            defaultdirectory = self.getInitialMediaDirectory()
        browserfilter = "Playlist (*.txt)"
        filepath, filtr = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save playlist to file", defaultdirectory,
            browserfilter, "", options) # TODO: Move to messages_en
        if filepath:
            self._syncplayClient.savePlaylistToFile(filepath)

    @needsClient
    def OpenAddURIsToPlaylistDialog(self):
        URIsDialog = QtWidgets.QDialog()
        URIsDialog.setWindowTitle(getMessage("adduris-msgbox-label"))
        URIsLayout = QtWidgets.QGridLayout()
        URIsLabel = QtWidgets.QLabel(getMessage("adduris-msgbox-label"))
        URIsLayout.addWidget(URIsLabel, 0, 0, 1, 1)
        URIsTextbox = QtWidgets.QPlainTextEdit()
        URIsTextbox.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        URIsLayout.addWidget(URIsTextbox, 1, 0, 1, 1)
        URIsButtonBox = QtWidgets.QDialogButtonBox()
        URIsButtonBox.setOrientation(Qt.Horizontal)
        URIsButtonBox.setStandardButtons(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        URIsButtonBox.accepted.connect(URIsDialog.accept)
        URIsButtonBox.rejected.connect(URIsDialog.reject)
        URIsLayout.addWidget(URIsButtonBox, 2, 0, 1, 1)
        URIsDialog.setLayout(URIsLayout)
        URIsDialog.setModal(True)
        URIsDialog.setWindowFlags(URIsDialog.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        URIsDialog.show()
        result = URIsDialog.exec_()
        if result == QtWidgets.QDialog.Accepted:
            URIsToAdd = utils.convertMultilineStringToList(URIsTextbox.toPlainText())
            self.updatingPlaylist = True
            for URI in URIsToAdd:
                URI = URI.rstrip()
                URI = urllib.parse.unquote(URI)
                if URI != "":
                    self.addStreamToPlaylist(URI)
            self.updatingPlaylist = False

    def openEditRoomsDialog(self):
        RoomsDialog = QtWidgets.QDialog()
        RoomsLayout = QtWidgets.QGridLayout()
        RoomsTextbox = QtWidgets.QPlainTextEdit()
        RoomsDialog.setWindowTitle(getMessage("roomlist-msgbox-label"))
        RoomsPlaylistLabel = QtWidgets.QLabel(getMessage("roomlist-msgbox-label"))
        RoomsTextbox.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        RoomsTextbox.setPlainText(utils.getListAsMultilineString(self.config['roomList']))
        RoomsLayout.addWidget(RoomsPlaylistLabel, 0, 0, 1, 1)
        RoomsLayout.addWidget(RoomsTextbox, 1, 0, 1, 1)
        RoomsButtonBox = QtWidgets.QDialogButtonBox()
        RoomsButtonBox.setOrientation(Qt.Horizontal)
        RoomsButtonBox.setStandardButtons(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        RoomsButtonBox.accepted.connect(RoomsDialog.accept)
        RoomsButtonBox.rejected.connect(RoomsDialog.reject)
        RoomsLayout.addWidget(RoomsButtonBox, 2, 0, 1, 1)
        RoomsDialog.setLayout(RoomsLayout)
        RoomsDialog.setModal(True)
        RoomsDialog.setWindowFlags(RoomsDialog.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        RoomsDialog.show()
        result = RoomsDialog.exec_()
        if result == QtWidgets.QDialog.Accepted:
            newRooms = utils.convertMultilineStringToList(RoomsTextbox.toPlainText())
            newRooms = sorted(newRooms)
            self.relistRoomList(newRooms)
            self._syncplayClient.setRoomList(newRooms)

    def relistRoomList(self, newRooms):
        filteredNewRooms = [room for room in newRooms if room and not room.isspace()]
        self.config['roomList'] = filteredNewRooms
        self.fillRoomsCombobox()

    @needsClient
    def openEditPlaylistDialog(self):
        oldPlaylist = utils.getListAsMultilineString(self.getPlaylistState())
        editPlaylistDialog = QtWidgets.QDialog()
        editPlaylistDialog.setWindowTitle(getMessage("editplaylist-msgbox-label"))
        editPlaylistLayout = QtWidgets.QGridLayout()
        editPlaylistLabel = QtWidgets.QLabel(getMessage("editplaylist-msgbox-label"))
        editPlaylistLayout.addWidget(editPlaylistLabel, 0, 0, 1, 1)
        editPlaylistTextbox = QtWidgets.QPlainTextEdit(oldPlaylist)
        editPlaylistTextbox.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        editPlaylistLayout.addWidget(editPlaylistTextbox, 1, 0, 1, 1)
        editPlaylistButtonBox = QtWidgets.QDialogButtonBox()
        editPlaylistButtonBox.setOrientation(Qt.Horizontal)
        editPlaylistButtonBox.setStandardButtons(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        editPlaylistButtonBox.accepted.connect(editPlaylistDialog.accept)
        editPlaylistButtonBox.rejected.connect(editPlaylistDialog.reject)
        editPlaylistLayout.addWidget(editPlaylistButtonBox, 2, 0, 1, 1)
        editPlaylistDialog.setLayout(editPlaylistLayout)
        editPlaylistDialog.setModal(True)
        editPlaylistDialog.setMinimumWidth(600)
        editPlaylistDialog.setMinimumHeight(500)
        editPlaylistDialog.setWindowFlags(editPlaylistDialog.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        editPlaylistDialog.show()
        result = editPlaylistDialog.exec_()
        if result == QtWidgets.QDialog.Accepted:
            newPlaylist = utils.convertMultilineStringToList(editPlaylistTextbox.toPlainText())
            if newPlaylist != self.playlistState and self._syncplayClient and not self.updatingPlaylist:
                self.setPlaylist(newPlaylist)
                self._syncplayClient.changePlaylist(newPlaylist)
                self._syncplayClient.updateFileSwitchInfo()

    @needsClient
    def openSetMediaDirectoriesDialog(self):
        MediaDirectoriesDialog = QtWidgets.QDialog()
        MediaDirectoriesDialog.setWindowTitle(getMessage("syncplay-mediasearchdirectories-title"))  # TODO: Move to messages_*.py
        MediaDirectoriesLayout = QtWidgets.QGridLayout()
        MediaDirectoriesLabel = QtWidgets.QLabel(getMessage("syncplay-mediasearchdirectories-label"))
        MediaDirectoriesLayout.addWidget(MediaDirectoriesLabel, 0, 0, 1, 2)
        MediaDirectoriesTextbox = QtWidgets.QPlainTextEdit()
        MediaDirectoriesTextbox.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        MediaDirectoriesTextbox.setPlainText(utils.getListAsMultilineString(self.config["mediaSearchDirectories"]))
        MediaDirectoriesLayout.addWidget(MediaDirectoriesTextbox, 1, 0, 1, 1)
        MediaDirectoriesButtonBox = QtWidgets.QDialogButtonBox()
        MediaDirectoriesButtonBox.setOrientation(Qt.Horizontal)
        MediaDirectoriesButtonBox.setStandardButtons(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        MediaDirectoriesButtonBox.accepted.connect(MediaDirectoriesDialog.accept)
        MediaDirectoriesButtonBox.rejected.connect(MediaDirectoriesDialog.reject)
        MediaDirectoriesLayout.addWidget(MediaDirectoriesButtonBox, 2, 0, 1, 1)
        MediaDirectoriesAddFolderButton = QtWidgets.QPushButton(getMessage("addfolder-label"))
        MediaDirectoriesAddFolderButton.pressed.connect(lambda: self.openAddMediaDirectoryDialog(MediaDirectoriesTextbox, MediaDirectoriesDialog))
        MediaDirectoriesLayout.addWidget(MediaDirectoriesAddFolderButton, 1, 1, 1, 1, Qt.AlignTop)
        MediaDirectoriesDialog.setLayout(MediaDirectoriesLayout)
        MediaDirectoriesDialog.setWindowFlags(MediaDirectoriesDialog.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        MediaDirectoriesDialog.setModal(True)
        MediaDirectoriesDialog.show()
        result = MediaDirectoriesDialog.exec_()
        if result == QtWidgets.QDialog.Accepted:
            newMediaDirectories = utils.convertMultilineStringToList(MediaDirectoriesTextbox.toPlainText())
            self._syncplayClient.changeMediaDirectories(newMediaDirectories)

    @needsClient
    def openSetTrustedDomainsDialog(self):
        TrustedDomainsDialog = QtWidgets.QDialog()
        TrustedDomainsDialog.setWindowTitle(getMessage("syncplay-trusteddomains-title"))
        TrustedDomainsLayout = QtWidgets.QGridLayout()
        TrustedDomainsLabel = QtWidgets.QLabel(getMessage("trusteddomains-msgbox-label"))
        TrustedDomainsLayout.addWidget(TrustedDomainsLabel, 0, 0, 1, 1)
        TrustedDomainsTextbox = QtWidgets.QPlainTextEdit()
        TrustedDomainsTextbox.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        TrustedDomainsTextbox.setPlainText(utils.getListAsMultilineString(self.config["trustedDomains"]))
        TrustedDomainsLayout.addWidget(TrustedDomainsTextbox, 1, 0, 1, 1)
        TrustedDomainsButtonBox = QtWidgets.QDialogButtonBox()
        TrustedDomainsButtonBox.setOrientation(Qt.Horizontal)
        TrustedDomainsButtonBox.setStandardButtons(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        TrustedDomainsButtonBox.accepted.connect(TrustedDomainsDialog.accept)
        TrustedDomainsButtonBox.rejected.connect(TrustedDomainsDialog.reject)
        TrustedDomainsLayout.addWidget(TrustedDomainsButtonBox, 2, 0, 1, 1)
        TrustedDomainsDialog.setLayout(TrustedDomainsLayout)
        TrustedDomainsDialog.setWindowFlags(TrustedDomainsDialog.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        TrustedDomainsDialog.setModal(True)
        TrustedDomainsDialog.show()
        result = TrustedDomainsDialog.exec_()
        if result == QtWidgets.QDialog.Accepted:
            newTrustedDomains = utils.convertMultilineStringToList(TrustedDomainsTextbox.toPlainText())
            self._syncplayClient.setTrustedDomains(newTrustedDomains)

    @needsClient
    def addTrustedDomain(self, newDomain):
        trustedDomains = self.config["trustedDomains"][:]
        if newDomain:
            trustedDomains.append(newDomain)
            self._syncplayClient.setTrustedDomains(trustedDomains)

    @needsClient
    def openAddMediaDirectoryDialog(self, MediaDirectoriesTextbox, MediaDirectoriesDialog):
        options = QtWidgets.QFileDialog.Options(QtWidgets.QFileDialog.ShowDirsOnly)
        folderName = str(QtWidgets.QFileDialog.getExistingDirectory(
            self, None, self.getInitialMediaDirectory(includeUserSpecifiedDirectories=False), options))

        if folderName:
            existingMediaDirs = MediaDirectoriesTextbox.toPlainText()
            if existingMediaDirs == "":
                newMediaDirList = folderName
            else:
                newMediaDirList = existingMediaDirs + "\n" + folderName
            MediaDirectoriesTextbox.setPlainText(newMediaDirList)
        MediaDirectoriesDialog.raise_()
        MediaDirectoriesDialog.activateWindow()

    @needsClient
    def promptForStreamURL(self):
        streamURL, ok = QtWidgets.QInputDialog.getText(
            self, getMessage("promptforstreamurl-msgbox-label"),
            getMessage("promptforstreamurlinfo-msgbox-label"), QtWidgets.QLineEdit.Normal, "")
        if ok and streamURL != '':
            self._syncplayClient.openFile(streamURL, resetPosition=False, fromUser=True)

    @needsClient
    def createControlledRoom(self):
        controlroom, ok = QtWidgets.QInputDialog.getText(
            self, getMessage("createcontrolledroom-msgbox-label"),
            getMessage("controlledroominfo-msgbox-label"), QtWidgets.QLineEdit.Normal,
            utils.stripRoomName(self._syncplayClient.getRoom()))
        if ok and controlroom != '':
            self._syncplayClient.createControlledRoom(controlroom)

    @needsClient
    def identifyAsController(self):
        msgboxtitle = getMessage("identifyascontroller-msgbox-label")
        msgboxtext = getMessage("identifyinfo-msgbox-label")
        controlpassword, ok = QtWidgets.QInputDialog.getText(self, msgboxtitle, msgboxtext, QtWidgets.QLineEdit.Normal, "")
        if ok and controlpassword != '':
            self._syncplayClient.identifyAsController(controlpassword)

    def _extractSign(self, m):
        if m:
            if m == "-":
                return -1
            else:
                return 1
        else:
            return None

    @needsClient
    def setOffset(self):
        oldoffset = str(self._syncplayClient.getUserOffset())
        newoffset, ok = QtWidgets.QInputDialog.getText(
            self, getMessage("setoffset-msgbox-label"),
            getMessage("offsetinfo-msgbox-label"), QtWidgets.QLineEdit.Normal, oldoffset)
        if ok and newoffset != '':
            o = re.match(constants.UI_OFFSET_REGEX, "o " + newoffset)
            if o:
                sign = self._extractSign(o.group('sign'))
                t = utils.parseTime(o.group('time'))
                if t is None:
                    return
                if o.group('sign') == "/":
                    t = self._syncplayClient.getPlayerPosition() - t
                elif sign:
                    t = self._syncplayClient.getUserOffset() + sign * t
                self._syncplayClient.setUserOffset(t)
            else:
                self.showErrorMessage(getMessage("invalid-offset-value"))

    def openUserGuide(self):
        if isLinux():
            self.QtGui.QDesktopServices.openUrl(QUrl("https://syncplay.pl/guide/linux/"))
        elif isWindows():
            self.QtGui.QDesktopServices.openUrl(QUrl("https://syncplay.pl/guide/windows/"))
        else:
            self.QtGui.QDesktopServices.openUrl(QUrl("https://syncplay.pl/guide/"))

    def drop(self):
        self.close()

    def getPlaylistState(self):
        playlistItems = []
        for playlistItem in range(self.playlist.count()):
            playlistItemText = self.playlist.item(playlistItem).text()
            if playlistItemText != getMessage("playlist-instruction-item-message"):
                playlistItems.append(playlistItemText)
        return playlistItems

    def playlistChangeCheck(self):
        if self.updatingPlaylist:
            return
        newPlaylist = self.getPlaylistState()
        if newPlaylist != self.playlistState and self._syncplayClient and not self.updatingPlaylist:
            self.playlistState = newPlaylist
            self._syncplayClient.changePlaylist(newPlaylist)
            self._syncplayClient.updateFileSwitchInfo()

    def executeCommand(self, command):
        self.showMessage("/{}".format(command))
        self.console.executeCommand(command)

    def sendChatMessage(self):
        chatText = self.chatInput.text()
        self.chatInput.setText("")
        if chatText != "":
            if chatText[:1] == "/" and chatText != "/":
                command = chatText[1:]
                if command and command[:1] == "/":
                    chatText = chatText[1:]
                else:
                    self.executeCommand(command)
                    return
            self._syncplayClient.sendChat(chatText)

    def addTopLayout(self, window):
        # ── Zone A (Left): Playlist + User List ─────────────────────────────
        window.zoneAFrame = QtWidgets.QFrame()
        window.zoneAFrame.setObjectName("panelZoneA")
        zoneALayout = QtWidgets.QVBoxLayout()
        zoneALayout.setContentsMargins(4, 4, 0, 4)
        zoneALayout.setSpacing(0)
        window.zoneAFrame.setLayout(zoneALayout)

        # Vertical splitter for Playlist (top) / Users (bottom)
        window.listSplit = QtWidgets.QSplitter(Qt.Vertical, self)
        window.listSplit.setHandleWidth(2)

        # ── Playlist Panel ──────────────────────────────────────────────────
        window.playlistGroup = self.PlaylistGroupBox(getMessage("sharedplaylistenabled-label"))
        window.playlistGroup.setCheckable(True)
        window.playlistGroup.toggled.connect(self.changePlaylistEnabledState)
        window.playlistLayout = QtWidgets.QVBoxLayout()
        window.playlistGroup.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        window.playlistGroup.setAcceptDrops(True)

        # Playlist toolbar (surfaced actions instead of context-menu-only)
        window.playlistToolbar = QtWidgets.QHBoxLayout()
        window.playlistToolbar.setContentsMargins(0, 0, 0, 4)
        window.playlistToolbar.setSpacing(4)

        window.addFileButton = QtWidgets.QPushButton(QtGui.QPixmap(resourcespath + 'film_add.png'), getMessage("addfilestoplaylist-menu-label"))
        window.addFileButton.setProperty("buttonTier", "secondary")
        window.addFileButton.pressed.connect(self.OpenAddFilesToPlaylistDialog)
        window.addFileButton.setToolTip(getMessage("addfilestoplaylist-menu-label"))

        window.addURLButton = QtWidgets.QPushButton(QtGui.QPixmap(resourcespath + 'world_add.png'), getMessage("addurlstoplaylist-menu-label"))
        window.addURLButton.setProperty("buttonTier", "secondary")
        window.addURLButton.pressed.connect(self.OpenAddURIsToPlaylistDialog)
        window.addURLButton.setToolTip(getMessage("addurlstoplaylist-menu-label"))

        window.shuffleButton = QtWidgets.QPushButton(QtGui.QPixmap(resourcespath + 'arrow_switch.png'), "")
        window.shuffleButton.setProperty("buttonTier", "tertiary")
        window.shuffleButton.pressed.connect(self.shuffleRemainingPlaylist)
        window.shuffleButton.setToolTip(getMessage("shuffleremainingplaylist-menu-label"))

        window.undoPlaylistButton = QtWidgets.QPushButton(QtGui.QPixmap(resourcespath + 'arrow_undo.png'), "")
        window.undoPlaylistButton.setProperty("buttonTier", "tertiary")
        window.undoPlaylistButton.pressed.connect(self.undoPlaylistChange)
        window.undoPlaylistButton.setToolTip(getMessage("undoplaylist-menu-label"))

        window.playlistToolbar.addWidget(window.addFileButton)
        window.playlistToolbar.addWidget(window.addURLButton)
        window.playlistToolbar.addStretch()
        window.playlistToolbar.addWidget(window.shuffleButton)
        window.playlistToolbar.addWidget(window.undoPlaylistButton)
        window.playlistLayout.addLayout(window.playlistToolbar)

        window.playlist = self.PlaylistWidget()
        window.playlist.setWindow(window)
        window.playlist.setItemDelegate(self.PlaylistItemDelegate())
        window.playlist.setDragEnabled(True)
        window.playlist.setAcceptDrops(True)
        window.playlist.setDropIndicatorShown(True)
        window.playlist.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        window.playlist.setDefaultDropAction(Qt.MoveAction)
        window.playlist.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        window.playlist.doubleClicked.connect(self.playlistItemClicked)
        window.playlist.setContextMenuPolicy(Qt.CustomContextMenu)
        window.playlist.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        window.playlist.customContextMenuRequested.connect(self.openPlaylistMenu)
        self.playlistUpdateTimer = task.LoopingCall(self.playlistChangeCheck)
        self.playlistUpdateTimer.start(0.1, True)
        noteFont = QtGui.QFont()
        noteFont.setItalic(True)
        playlistItem = QtWidgets.QListWidgetItem(getMessage("playlist-instruction-item-message"))
        playlistItem.setFont(noteFont)
        window.playlist.addItem(playlistItem)
        window.playlistLayout.addWidget(window.playlist)
        window.playlistGroup.setLayout(window.playlistLayout)
        window.listSplit.addWidget(window.playlistGroup)

        # ── User List Panel ─────────────────────────────────────────────────
        window.userlistFrame = QtWidgets.QFrame()
        window.userlistFrame.setLineWidth(0)
        window.userlistFrame.setMidLineWidth(0)
        window.userlistFrame.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        window.userlistLayout = QtWidgets.QVBoxLayout()
        window.userlistLayout.setContentsMargins(0, 0, 0, 0)
        window.userlistLayout.setSpacing(4)
        window.userlistFrame.setLayout(window.userlistLayout)

        # User list header row
        window.userlistHeaderLayout = QtWidgets.QHBoxLayout()
        window.listlabel = QtWidgets.QLabel(getMessage("userlist-heading-label"))
        window.listlabel.setObjectName("sectionLabel")
        window.sslButton = QtWidgets.QPushButton(QtGui.QPixmap(resourcespath + 'lock_green.png').scaled(16, 16), "")
        window.sslButton.setProperty("buttonTier", "tertiary")
        window.sslButton.setVisible(False)
        window.sslButton.setFixedSize(24, 24)
        window.sslButton.pressed.connect(self.openSSLDetails)
        window.sslButton.setToolTip(getMessage("sslconnection-tooltip"))
        window.userlistHeaderLayout.addWidget(window.listlabel, 1)
        window.userlistHeaderLayout.addWidget(window.sslButton, 0, Qt.AlignRight)
        window.userlistLayout.addLayout(window.userlistHeaderLayout)

        window.listTreeModel = QtGui.QStandardItemModel()
        window.listTreeView = QtWidgets.QTreeView()
        window.listTreeView.setModel(window.listTreeModel)
        window.listTreeView.setIndentation(21)
        window.listTreeView.doubleClicked.connect(self.roomClicked)
        window.listTreeView.setContextMenuPolicy(Qt.CustomContextMenu)
        window.listTreeView.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        window.listTreeView.customContextMenuRequested.connect(self.openRoomMenu)
        window.userlistLayout.addWidget(window.listTreeView)

        window.listSplit.addWidget(window.userlistFrame)
        window.listSplit.setStretchFactor(0, 3)  # Playlist gets more space
        window.listSplit.setStretchFactor(1, 2)  # Users get less space

        zoneALayout.addWidget(window.listSplit)

        # ── Zone B (Right): Notifications + Chat ────────────────────────────
        window.zoneBFrame = QtWidgets.QFrame()
        window.zoneBFrame.setObjectName("panelZoneB")
        zoneBLayout = QtWidgets.QVBoxLayout()
        zoneBLayout.setContentsMargins(0, 4, 4, 4)
        zoneBLayout.setSpacing(4)
        window.zoneBFrame.setLayout(zoneBLayout)

        window.outputlabel = QtWidgets.QLabel(getMessage("notifications-heading-label"))
        window.outputlabel.setObjectName("sectionLabel")
        zoneBLayout.addWidget(window.outputlabel)

        window.outputbox = QtWidgets.QTextBrowser()
        window.outputbox.document().setDefaultStyleSheet(constants.STYLE_DARK_LINKS_COLOR)
        window.outputbox.setReadOnly(True)
        window.outputbox.setTextInteractionFlags(window.outputbox.textInteractionFlags() | Qt.TextSelectableByKeyboard)
        window.outputbox.setOpenExternalLinks(True)
        window.outputbox.unsetCursor()
        window.outputbox.moveCursor(QtGui.QTextCursor.End)
        window.outputbox.insertHtml(constants.STYLE_CONTACT_INFO.format(getMessage("contact-label")))
        window.outputbox.moveCursor(QtGui.QTextCursor.End)
        window.outputbox.setCursorWidth(0)
        zoneBLayout.addWidget(window.outputbox)

        # Playback frame (hidden by default, toggled from menu)
        self.addPlaybackLayout(window)
        zoneBLayout.addWidget(window.playbackFrame)

        # Chat input row
        window.chatLayout = QtWidgets.QHBoxLayout()
        window.chatLayout.setContentsMargins(0, 0, 0, 0)
        window.chatLayout.setSpacing(4)
        window.chatInput = QtWidgets.QLineEdit()
        window.chatInput.setMaxLength(constants.MAX_CHAT_MESSAGE_LENGTH)
        window.chatInput.setPlaceholderText(getMessage("sendmessage-label"))
        window.chatInput.returnPressed.connect(self.sendChatMessage)
        window.chatButton = QtWidgets.QPushButton(QtGui.QPixmap(resourcespath + 'email_go.png'), "")
        window.chatButton.setProperty("buttonTier", "tertiary")
        window.chatButton.setFixedSize(32, 32)
        window.chatButton.pressed.connect(self.sendChatMessage)
        window.chatButton.setToolTip(getMessage("sendmessage-tooltip"))
        window.chatLayout.addWidget(window.chatInput)
        window.chatLayout.addWidget(window.chatButton)
        window.chatFrame = QtWidgets.QFrame()
        window.chatFrame.setLayout(window.chatLayout)
        window.chatFrame.setContentsMargins(0, 0, 0, 0)
        window.chatFrame.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        zoneBLayout.addWidget(window.chatFrame)

        # ── Assemble Zones A + B via horizontal splitter ────────────────────
        window.topSplit = self.topSplitter(Qt.Horizontal, self)
        window.topSplit.addWidget(window.zoneAFrame)
        window.topSplit.addWidget(window.zoneBFrame)
        window.topSplit.setHandleWidth(2)
        window.topSplit.setStretchFactor(0, 7)   # Zone A: ~65%
        window.topSplit.setStretchFactor(1, 4)   # Zone B: ~35%
        window.topSplit.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        window.mainLayout.addWidget(window.topSplit)

        # Keep references that other methods expect
        window.outputFrame = window.zoneBFrame
        window.listFrame = window.zoneAFrame
        window.listLayout = zoneALayout

    def addBottomLayout(self, window):
        # ── Zone C: Control Deck (fixed-height footer) ──────────────────────
        window.controlDeck = QtWidgets.QFrame()
        window.controlDeck.setObjectName("controlDeck")
        window.controlDeck.setFixedHeight(48)
        deckLayout = QtWidgets.QHBoxLayout()
        deckLayout.setContentsMargins(10, 4, 10, 4)
        deckLayout.setSpacing(8)
        window.controlDeck.setLayout(deckLayout)

        # ── Room selector ───────────────────────────────────────────────────
        window.roomsCombobox = QtWidgets.QComboBox(self)
        window.roomsCombobox.setEditable(True)
        window.roomsCombobox.setMinimumWidth(160)
        caseSensitiveCompleter = QtWidgets.QCompleter(self)
        caseSensitiveCompleter.setCaseSensitivity(Qt.CaseSensitive)
        window.roomsCombobox.setCompleter(caseSensitiveCompleter)

        window.roomButton = QtWidgets.QPushButton(
            QtGui.QPixmap(resourcespath + 'door_in.png'),
            getMessage("joinroom-label"))
        window.roomButton.setProperty("buttonTier", "secondary")
        window.roomButton.pressed.connect(self.joinRoom)
        window.roomButton.setToolTip(getMessage("joinroom-tooltip"))

        deckLayout.addWidget(window.roomsCombobox)
        deckLayout.addWidget(window.roomButton)

        # Vertical separator
        sep1 = QtWidgets.QFrame()
        sep1.setFrameShape(QtWidgets.QFrame.VLine)
        sep1.setFrameShadow(QtWidgets.QFrame.Sunken)
        deckLayout.addWidget(sep1)

        # ── Ready button (Tier 1 Primary) ───────────────────────────────────
        window.readyPushButton = QtWidgets.QPushButton()
        window.readyPushButton.setObjectName("readyButton")
        window.readyPushButton.setProperty("buttonTier", "primary")
        readyFont = QtGui.QFont()
        readyFont.setWeight(QtGui.QFont.Bold)
        window.readyPushButton.setText(getMessage("ready-guipushbuttonlabel"))
        window.readyPushButton.setCheckable(True)
        window.readyPushButton.setAutoExclusive(False)
        window.readyPushButton.toggled.connect(self.changeReadyState)
        window.readyPushButton.setFont(readyFont)
        window.readyPushButton.setToolTip(getMessage("ready-tooltip"))
        window.readyPushButton.setMinimumWidth(120)
        deckLayout.addWidget(window.readyPushButton)

        # Vertical separator
        sep2 = QtWidgets.QFrame()
        sep2.setFrameShape(QtWidgets.QFrame.VLine)
        sep2.setFrameShadow(QtWidgets.QFrame.Sunken)
        deckLayout.addWidget(sep2)

        # ── Autoplay controls ───────────────────────────────────────────────
        window.autoplayFrame = QtWidgets.QFrame()
        window.autoplayFrame.setVisible(False)
        window.autoplayLayout = QtWidgets.QHBoxLayout()
        window.autoplayLayout.setContentsMargins(0, 0, 0, 0)
        window.autoplayLayout.setSpacing(6)
        window.autoplayFrame.setLayout(window.autoplayLayout)

        window.autoplayPushButton = QtWidgets.QPushButton()
        window.autoplayPushButton.setObjectName("autoplayButton")
        window.autoplayPushButton.setProperty("buttonTier", "secondary")
        autoPlayFont = QtGui.QFont()
        autoPlayFont.setWeight(QtGui.QFont.Bold)
        window.autoplayPushButton.setText(getMessage("autoplay-guipushbuttonlabel"))
        window.autoplayPushButton.setCheckable(True)
        window.autoplayPushButton.setAutoExclusive(False)
        window.autoplayPushButton.toggled.connect(self.changeAutoplayState)
        window.autoplayPushButton.setFont(autoPlayFont)
        window.autoplayPushButton.setToolTip(getMessage("autoplay-tooltip"))

        window.autoplayLabel = QtWidgets.QLabel(getMessage("autoplay-minimum-label"))
        window.autoplayLabel.setToolTip(getMessage("autoplay-tooltip"))

        window.autoplayThresholdSpinbox = QtWidgets.QSpinBox()
        window.autoplayThresholdSpinbox.setMinimum(2)
        window.autoplayThresholdSpinbox.setMaximum(99)
        window.autoplayThresholdSpinbox.setToolTip(getMessage("autoplay-tooltip"))
        window.autoplayThresholdSpinbox.valueChanged.connect(self.changeAutoplayThreshold)

        window.autoplayLayout.addWidget(window.autoplayPushButton)
        window.autoplayLayout.addWidget(window.autoplayLabel)
        window.autoplayLayout.addWidget(window.autoplayThresholdSpinbox)

        deckLayout.addWidget(window.autoplayFrame)

        deckLayout.addStretch()  # Push remaining items to the right

        # Keep reference for addWidget
        window.bottomFrame = window.controlDeck
        window.bottomLayout = deckLayout

        # Legacy references needed by other methods
        window.roomLayout = deckLayout
        window.roomFrame = window.controlDeck

        window.mainLayout.addWidget(window.controlDeck)

    def addPlaybackLayout(self, window):
        window.playbackFrame = QtWidgets.QFrame()
        window.playbackFrame.setVisible(False)
        window.playbackFrame.setContentsMargins(0, 0, 0, 0)
        window.playbackLayout = QtWidgets.QHBoxLayout()
        window.playbackLayout.setAlignment(Qt.AlignLeft)
        window.playbackLayout.setContentsMargins(0, 0, 0, 0)
        window.playbackLayout.setSpacing(4)
        window.playbackFrame.setLayout(window.playbackLayout)

        window.seekInput = QtWidgets.QLineEdit()
        window.seekInput.returnPressed.connect(self.seekFromButton)
        window.seekInput.setText("0:00")
        window.seekInput.setFixedWidth(60)

        window.seekButton = QtWidgets.QPushButton(QtGui.QPixmap(resourcespath + 'clock_go.png'), "")
        window.seekButton.setProperty("buttonTier", "tertiary")
        window.seekButton.setToolTip(getMessage("seektime-menu-label"))
        window.seekButton.pressed.connect(self.seekFromButton)

        window.unseekButton = QtWidgets.QPushButton(QtGui.QPixmap(resourcespath + 'arrow_undo.png'), "")
        window.unseekButton.setProperty("buttonTier", "tertiary")
        window.unseekButton.setToolTip(getMessage("undoseek-menu-label"))
        window.unseekButton.pressed.connect(self.undoSeek)

        window.playButton = QtWidgets.QPushButton(QtGui.QPixmap(resourcespath + 'control_play_blue.png'), "")
        window.playButton.setProperty("buttonTier", "tertiary")
        window.playButton.setToolTip(getMessage("play-menu-label"))
        window.playButton.pressed.connect(self.play)

        window.pauseButton = QtWidgets.QPushButton(QtGui.QPixmap(resourcespath + 'control_pause_blue.png'), "")
        window.pauseButton.setProperty("buttonTier", "tertiary")
        window.pauseButton.setToolTip(getMessage("pause-menu-label"))
        window.pauseButton.pressed.connect(self.pause)

        window.playbackLayout.addWidget(window.seekInput)
        window.playbackLayout.addWidget(window.seekButton)
        window.playbackLayout.addWidget(window.unseekButton)
        window.playbackLayout.addWidget(window.playButton)
        window.playbackLayout.addWidget(window.pauseButton)
        window.playbackFrame.setMaximumHeight(window.playbackFrame.sizeHint().height())
        window.miscLayout = QtWidgets.QHBoxLayout()  # Keep reference for compatibility

    def loadMenubar(self, window, passedBar):
        if passedBar is not None:
            window.menuBar = passedBar['bar']
            window.editMenu = passedBar['editMenu']
        else:
            window.menuBar = QtWidgets.QMenuBar()
            window.editMenu = None

    def populateMenubar(self, window):
        # File menu

        window.fileMenu = QtWidgets.QMenu(getMessage("file-menu-label"), self)
        window.openAction = window.fileMenu.addAction(QtGui.QPixmap(resourcespath + 'folder_explore.png'),
                                                      getMessage("openmedia-menu-label"))
        window.openAction.triggered.connect(self.browseMediapath)
        window.openAction = window.fileMenu.addAction(QtGui.QPixmap(resourcespath + 'world_explore.png'),
                                                      getMessage("openstreamurl-menu-label"))
        window.openAction.triggered.connect(self.promptForStreamURL)
        window.openAction = window.fileMenu.addAction(QtGui.QPixmap(resourcespath + 'film_folder_edit.png'),
                                                      getMessage("setmediadirectories-menu-label"))
        window.openAction.triggered.connect(self.openSetMediaDirectoriesDialog)

        window.reconnectAction = window.fileMenu.addAction(getMessage("reconnect-menu-label"))
        window.reconnectAction.triggered.connect(self.reconnectToServer)

        window.exitAction = window.fileMenu.addAction(getMessage("exit-menu-label"))
        if isMacOS():
            window.exitAction.setMenuRole(QtWidgets.QAction.QuitRole)
        else:
            window.exitAction.setIcon(QtGui.QPixmap(resourcespath + 'cross.png'))
        window.exitAction.triggered.connect(self.exitSyncplay)

        if(window.editMenu is not None):
            window.menuBar.insertMenu(window.editMenu.menuAction(), window.fileMenu)
        else:
            window.menuBar.addMenu(window.fileMenu)

        # Playback menu

        window.playbackMenu = QtWidgets.QMenu(getMessage("playback-menu-label"), self)
        window.playAction = window.playbackMenu.addAction(
            QtGui.QPixmap(resourcespath + 'control_play_blue.png'),
            getMessage("play-menu-label"))
        window.playAction.triggered.connect(self.play)
        window.pauseAction = window.playbackMenu.addAction(
            QtGui.QPixmap(resourcespath + 'control_pause_blue.png'),
            getMessage("pause-menu-label"))
        window.pauseAction.triggered.connect(self.pause)
        window.seekAction = window.playbackMenu.addAction(
            QtGui.QPixmap(resourcespath + 'clock_go.png'),
            getMessage("seektime-menu-label"))
        window.seekAction.triggered.connect(self.seekPositionDialog)
        window.unseekAction = window.playbackMenu.addAction(
            QtGui.QPixmap(resourcespath + 'arrow_undo.png'),
            getMessage("undoseek-menu-label"))
        window.unseekAction.triggered.connect(self.undoSeek)

        window.menuBar.addMenu(window.playbackMenu)

        # Advanced menu

        window.advancedMenu = QtWidgets.QMenu(getMessage("advanced-menu-label"), self)
        window.setoffsetAction = window.advancedMenu.addAction(
            QtGui.QPixmap(resourcespath + 'timeline_marker.png'),
            getMessage("setoffset-menu-label"))
        window.setoffsetAction.triggered.connect(self.setOffset)
        window.setTrustedDomainsAction = window.advancedMenu.addAction(
            QtGui.QPixmap(resourcespath + 'shield_edit.png'),
            getMessage("settrusteddomains-menu-label"))
        window.setTrustedDomainsAction.triggered.connect(self.openSetTrustedDomainsDialog)
        window.createcontrolledroomAction = window.advancedMenu.addAction(
            QtGui.QPixmap(resourcespath + 'page_white_key.png'), getMessage("createcontrolledroom-menu-label"))
        window.createcontrolledroomAction.triggered.connect(self.createControlledRoom)
        window.identifyascontroller = window.advancedMenu.addAction(QtGui.QPixmap(resourcespath + 'key_go.png'),
                                                                    getMessage("identifyascontroller-menu-label"))
        window.identifyascontroller.triggered.connect(self.identifyAsController)

        window.menuBar.addMenu(window.advancedMenu)

        # Window menu

        window.windowMenu = QtWidgets.QMenu(getMessage("window-menu-label"), self)

        window.editroomsAction = window.windowMenu.addAction(QtGui.QPixmap(resourcespath + 'door_open_edit.png'), getMessage("roomlist-msgbox-label"))
        window.editroomsAction.triggered.connect(self.openEditRoomsDialog)
        window.menuBar.addMenu(window.windowMenu)

        window.playbackAction = window.windowMenu.addAction(getMessage("playbackbuttons-menu-label"))
        window.playbackAction.setCheckable(True)
        window.playbackAction.triggered.connect(self.updatePlaybackFrameVisibility)

        window.autoplayAction = window.windowMenu.addAction(getMessage("autoplay-menu-label"))
        window.autoplayAction.setCheckable(True)
        window.autoplayAction.triggered.connect(self.updateAutoplayVisibility)

        window.hideEmptyRoomsAction = window.windowMenu.addAction(getMessage("hideemptyrooms-menu-label"))
        window.hideEmptyRoomsAction.setCheckable(True)
        window.hideEmptyRoomsAction.triggered.connect(self.updateEmptyRoomVisiblity)

        # Help menu

        window.helpMenu = QtWidgets.QMenu(getMessage("help-menu-label"), self)

        window.userguideAction = window.helpMenu.addAction(
            QtGui.QPixmap(resourcespath + 'help.png'),
            getMessage("userguide-menu-label"))
        window.userguideAction.triggered.connect(self.openUserGuide)
        window.updateAction = window.helpMenu.addAction(
            QtGui.QPixmap(resourcespath + 'application_get.png'),
            getMessage("update-menu-label"))
        window.updateAction.triggered.connect(self.userCheckForUpdates)

        if not isMacOS():
            window.helpMenu.addSeparator()
            window.about = window.helpMenu.addAction(
                QtGui.QPixmap(resourcespath + 'syncplay.png'),
                getMessage("about-menu-label"))
        else:
            window.about = window.helpMenu.addAction("&About")
            window.about.setMenuRole(QtWidgets.QAction.AboutRole)
        window.about.triggered.connect(self.openAbout)

        window.menuBar.addMenu(window.helpMenu)
        window.mainLayout.setMenuBar(window.menuBar)

    @needsClient
    def openSSLDetails(self):
        sslDetailsBox = CertificateDialog(self.getSSLInformation())
        sslDetailsBox.exec_()
        self.sslButton.setDown(False)

    def openAbout(self):
        aboutMsgBox = AboutDialog()
        aboutMsgBox.exec_()

    def addMainFrame(self, window):
        window.mainFrame = QtWidgets.QFrame()
        window.mainFrame.setLineWidth(0)
        window.mainFrame.setMidLineWidth(0)
        window.mainFrame.setContentsMargins(0, 0, 0, 0)
        window.mainFrame.setLayout(window.mainLayout)

        window.setCentralWidget(window.mainFrame)

    def newMessage(self, message):
        self.outputbox.moveCursor(QtGui.QTextCursor.End)
        self.outputbox.insertHtml(message)
        self.outputbox.moveCursor(QtGui.QTextCursor.End)

    def resetList(self):
        self.listbox.setText("")

    def newListItem(self, item):
        self.listbox.moveCursor(QtGui.QTextCursor.End)
        self.listbox.insertHtml(item)
        self.listbox.moveCursor(QtGui.QTextCursor.End)

    def updatePlaybackFrameVisibility(self):
        self.playbackFrame.setVisible(self.playbackAction.isChecked())

    def updateAutoplayVisibility(self):
        self.autoplayFrame.setVisible(self.autoplayAction.isChecked())

    def updateEmptyRoomVisiblity(self):
        self.hideEmptyRooms = self.hideEmptyRoomsAction.isChecked()
        if self._syncplayClient:
            self._syncplayClient.getUserList()

    def changeReadyState(self):
        self.updateReadyIcon()
        if self._syncplayClient:
            self._syncplayClient.changeReadyState(self.readyPushButton.isChecked())
        else:
            self.showDebugMessage("Tried to change ready state too soon.")

    def changePlaylistEnabledState(self):
        self._syncplayClient.changePlaylistEnabledState(self.playlistGroup.isChecked())

    @needsClient
    def changeAutoplayThreshold(self, source=None):
        self._syncplayClient.changeAutoPlayThrehsold(self.autoplayThresholdSpinbox.value())

    def updateAutoPlayState(self, newState):
        oldState = self.autoplayPushButton.isChecked()
        if newState != oldState and newState is not None:
            self.autoplayPushButton.blockSignals(True)
            self.autoplayPushButton.setChecked(newState)
            self.autoplayPushButton.blockSignals(False)
        self.updateAutoPlayIcon()

    @needsClient
    def changeAutoplayState(self, source=None):
        self.updateAutoPlayIcon()
        if self._syncplayClient:
            self._syncplayClient.changeAutoplayState(self.autoplayPushButton.isChecked())
        else:
            self.showDebugMessage("Tried to set AutoplayState too soon")

    def updateReadyIcon(self):
        ready = self.readyPushButton.isChecked()
        if ready:
            self.readyPushButton.setIcon(QtGui.QPixmap(resourcespath + 'tick_checkbox.png'))
        else:
            self.readyPushButton.setIcon(QtGui.QPixmap(resourcespath + 'empty_checkbox.png'))

    def updateAutoPlayIcon(self):
        ready = self.autoplayPushButton.isChecked()
        if ready:
            self.autoplayPushButton.setIcon(QtGui.QPixmap(resourcespath + 'tick_checkbox.png'))
        else:
            self.autoplayPushButton.setIcon(QtGui.QPixmap(resourcespath + 'empty_checkbox.png'))

    def automaticUpdateCheck(self):
        currentDateTimeValue = QDateTime.currentDateTime()
        if not self.config['checkForUpdatesAutomatically']:
            return
        try:
            if self.config['lastCheckedForUpdates']:
                configLastChecked = datetime.strptime(self.config["lastCheckedForUpdates"], "%Y-%m-%d %H:%M:%S.%f")
                if self.lastCheckedForUpdates is None or configLastChecked > self.lastCheckedForUpdates.toPython():
                    self.lastCheckedForUpdates = QDateTime.fromString(self.config["lastCheckedForUpdates"], 'yyyy-MM-dd HH-mm-ss')
            if self.lastCheckedForUpdates is None:
                self.checkForUpdates()
            else:
                timeDelta = currentDateTimeValue.toPython() - self.lastCheckedForUpdates.toPython()
                if timeDelta.total_seconds() > constants.AUTOMATIC_UPDATE_CHECK_FREQUENCY:
                    self.checkForUpdates()
        except Exception as e:
            self.showDebugMessage("Automatic check for updates failed. An update check was manually trigggered. Reason: {}".format(str(e)))
            self.checkForUpdates()

    def userCheckForUpdates(self):
        self.checkForUpdates(userInitiated=True)

    @needsClient
    def checkForUpdates(self, userInitiated=False):
        self.lastCheckedForUpdates = QDateTime.currentDateTime()
        updateStatus, updateMessage, updateURL, self.publicServerList = self._syncplayClient.checkForUpdate(userInitiated)

        if updateMessage is None:
            if updateStatus == "uptodate":
                updateMessage = getMessage("syncplay-uptodate-notification")
            elif updateStatus == "updateavailale":
                updateMessage = getMessage("syncplay-updateavailable-notification")
            else:
                import syncplay
                updateMessage = getMessage("update-check-failed-notification").format(syncplay.version)
                if userInitiated == True:
                    updateURL = constants.SYNCPLAY_DOWNLOAD_URL
        if updateURL is not None:
            reply = QtWidgets.QMessageBox.question(
                self, "Syncplay",
                updateMessage, QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
            if reply == QtWidgets.QMessageBox.Yes:
                self.QtGui.QDesktopServices.openUrl(QUrl(updateURL))
        elif userInitiated:
            QtWidgets.QMessageBox.information(self, "Syncplay", updateMessage)
        else:
            self.showMessage(updateMessage)

    def dragEnterEvent(self, event):
        data = event.mimeData()
        urls = data.urls()
        if urls and urls[0].scheme() == 'file':
            event.acceptProposedAction()

    def dropEvent(self, event):
        rewindFile = False
        if QtGui.QDropEvent.proposedAction(event) == Qt.MoveAction:
            QtGui.QDropEvent.setDropAction(event, Qt.CopyAction)  # Avoids file being deleted
            rewindFile = True
        data = event.mimeData()
        urls = data.urls()
        if urls and urls[0].scheme() == 'file':
            url = event.mimeData().urls()[0]
            dropfilepath = os.path.abspath(str(url.toLocalFile()))
            if rewindFile == False:
                self._syncplayClient.openFile(dropfilepath, resetPosition=False, fromUser=True)
            else:
                self._syncplayClient.setPosition(0)
                self._syncplayClient.openFile(dropfilepath, resetPosition=True, fromUser=True)
                self._syncplayClient.setPosition(0)

    def setPlaylist(self, newPlaylist, newIndexFilename=None):
        if self.updatingPlaylist:
            self.ui.showDebugMessage("Trying to set playlist while it is already being updated")
        if newPlaylist == self.playlistState:
            if newIndexFilename:
                self.playlist.setPlaylistIndexFilename(newIndexFilename)
            self.updatingPlaylist = False
            return
        self.updatingPlaylist = True
        if newPlaylist and len(newPlaylist) > 0:
            self.clearedPlaylistNote = True
        self.playlistState = newPlaylist
        self.playlist.updatePlaylist(newPlaylist)
        if newIndexFilename:
            self.playlist.setPlaylistIndexFilename(newIndexFilename)
        self.updatingPlaylist = False
        self._syncplayClient.updateFileSwitchInfo()

    def setPlaylistIndexFilename(self, filename):
        self.playlist.setPlaylistIndexFilename(filename)

    def addFileToPlaylist(self, filePath, index=-1):
        if not isURL(filePath):
            self.removePlaylistNote()
            filename = os.path.basename(filePath)
            if self.noPlaylistDuplicates(filename):
                if self.playlist == -1 or index == -1:
                    self.playlist.addItem(filename)
                else:
                    self.playlist.insertItem(index, filename)
                self._syncplayClient.notifyUserIfFileNotInMediaDirectory(filename, filePath)
        else:
            self.removePlaylistNote()
            if self.noPlaylistDuplicates(filePath):
                if self.playlist == -1 or index == -1:
                    self.playlist.addItem(filePath)
                else:
                    self.playlist.insertItem(index, filePath)

    def openFile(self, filePath, resetPosition=False, fromUser=False):
        self._syncplayClient.openFile(filePath, resetPosition, fromUser=fromUser)

    def noPlaylistDuplicates(self, filename):
        if self.isItemInPlaylist(filename):
            self.showErrorMessage(getMessage("cannot-add-duplicate-error").format(filename))
            return False
        else:
            return True

    def isItemInPlaylist(self, filename):
        for playlistindex in range(self.playlist.count()):
            if self.playlist.item(playlistindex).text() == filename:
                return True
        return False

    def addStreamToPlaylist(self, streamURI):
        self.removePlaylistNote()
        if self.noPlaylistDuplicates(streamURI):
            self.playlist.addItem(streamURI)

    def removePlaylistNote(self):
        if not self.clearedPlaylistNote:
            for index in range(self.playlist.count()):
                self.playlist.takeItem(0)
            self.clearedPlaylistNote = True

    def addFolderToPlaylist(self, folderPath):
        self.showErrorMessage("You tried to add the folder '{}' to the playlist. Syncplay only currently supports adding files to the playlist.".format(folderPath))  # TODO: Implement "add folder to playlist"

    def deleteSelectedPlaylistItems(self):
        self.playlist.remove_selected_items()

    def saveSettings(self):
        settings = QSettings("Syncplay", "MainWindow")
        settings.beginGroup("MainWindow")
        settings.setValue("size", self.size())
        settings.setValue("pos", self.pos())
        settings.setValue("showPlaybackButtons", self.playbackAction.isChecked())
        settings.setValue("showAutoPlayButton", self.autoplayAction.isChecked())
        settings.setValue("hideEmptyRooms", self.hideEmptyRoomsAction.isChecked())
        settings.setValue("autoplayChecked", self.autoplayPushButton.isChecked())
        settings.setValue("autoplayMinUsers", self.autoplayThresholdSpinbox.value())
        settings.endGroup()
        settings = QSettings("Syncplay", "Interface")
        settings.beginGroup("Update")
        settings.setValue("lastCheckedQt", self.lastCheckedForUpdates)
        settings.endGroup()
        settings.beginGroup("PublicServerList")
        if self.publicServerList:
            settings.setValue("publicServers", self.publicServerList)
        settings.endGroup()

    def loadSettings(self):
        settings = QSettings("Syncplay", "MainWindow")
        settings.beginGroup("MainWindow")
        self.resize(settings.value("size", QSize(700, 500)))
        movePos = settings.value("pos", QPoint(200, 200))
        windowGeometry = QtWidgets.QApplication.primaryScreen().geometry()
        posIsOnScreen = windowGeometry.contains(QtCore.QRect(movePos.x(), movePos.y(), 1, 1))
        if not posIsOnScreen:
            movePos = QPoint(200,200)
        self.move(movePos)
        if settings.value("showPlaybackButtons", "false") == "true":
            self.playbackAction.setChecked(True)
            self.updatePlaybackFrameVisibility()
        if settings.value("showAutoPlayButton", "false") == "true":
            self.autoplayAction.setChecked(True)
            self.updateAutoplayVisibility()
        if settings.value("hideEmptyRooms", "false") == "true":
            self.hideEmptyRooms = True
            self.hideEmptyRoomsAction.setChecked(True)
        if settings.value("autoplayChecked", "false") == "true":
            self.updateAutoPlayState(True)
            self.autoplayPushButton.setChecked(True)
        self.autoplayThresholdSpinbox.blockSignals(True)
        self.autoplayThresholdSpinbox.setValue(int(settings.value("autoplayMinUsers", 2)))
        self.autoplayThresholdSpinbox.blockSignals(False)
        settings.endGroup()
        settings = QSettings("Syncplay", "Interface")
        settings.beginGroup("Update")
        self.lastCheckedForUpdates = settings.value("lastCheckedQt", None)
        settings.endGroup()
        settings.beginGroup("PublicServerList")
        self.publicServerList = settings.value("publicServers", None)

    def __init__(self, passedBar=None):
        super(MainWindow, self).__init__()
        self.console = ConsoleInGUI()
        self.console.setDaemon(True)
        self.newWatchlist = []
        self.publicServerList = []
        self.lastCheckedForUpdates = None
        self._syncplayClient = None
        self.folderSearchEnabled = True
        self.hideEmptyRooms = False
        self.currentRooms = []
        self.QtGui = QtGui
        if isMacOS():
            self.setWindowFlags(self.windowFlags())
        else:
            try:
                self.setWindowFlags(self.windowFlags() & Qt.AA_DontUseNativeMenuBar)
            except TypeError:
                self.setWindowFlags(self.windowFlags())

        self.setWindowTitle("Syncplay v" + version + revision)
        self.mainLayout = QtWidgets.QVBoxLayout()
        self.mainLayout.setContentsMargins(0, 0, 0, 0)
        self.mainLayout.setSpacing(0)

        self.addTopLayout(self)     # Zones A + B
        self.addBottomLayout(self)  # Zone C (Control Deck)
        self.loadMenubar(self, passedBar)
        self.populateMenubar(self)
        self.addMainFrame(self)
        self.loadSettings()
        self.setWindowIcon(QtGui.QPixmap(resourcespath + "syncplay.png"))
        self.setWindowFlags(self.windowFlags() & Qt.WindowCloseButtonHint & Qt.WindowMinimizeButtonHint & ~Qt.WindowContextHelpButtonHint)
        self.show()
        self.setAcceptDrops(True)
        self.clearedPlaylistNote = False
        self.uiMode = constants.GRAPHICAL_UI_MODE
