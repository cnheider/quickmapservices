from __future__ import absolute_import
from urllib2 import URLError
from os import path

from PyQt4 import uic
from PyQt4.QtGui import *
from PyQt4.QtCore import QThread, pyqtSignal, Qt, QTimer, QMutex, QSize, QByteArray

from qgis.gui import QgsFilterLineEdit

from .data_source_serializer import DataSourceSerializer
from .qgis_map_helpers import add_layer_to_map
from .qms_external_api_python.client import Client
from .qgis_settings import QGISSettings
import sys


FORM_CLASS, _ = uic.loadUiType(path.join(
    path.dirname(__file__), 'qms_service_toolbox.ui'))


class QmsServiceToolbox(QDockWidget, FORM_CLASS):
    def __init__(self, iface):
        QDockWidget.__init__(self, iface.mainWindow())
        self.setupUi(self)

        self.iface = iface
        self.search_threads = None  # []

        if hasattr(self.txtSearch, 'setPlaceholderText'):
            self.txtSearch.setPlaceholderText(self.tr("Search string..."))

        self.delay_timer = QTimer(self)
        self.delay_timer.setSingleShot(True)
        self.delay_timer.setInterval(250)

        self.delay_timer.timeout.connect(self.start_search)
        self.txtSearch.textChanged.connect(self.delay_timer.start)

        self.lstSearchResult.itemDoubleClicked.connect(self.result_selected)

        self.one_process_work = QMutex()

    def start_search(self):
        search_text = unicode(self.txtSearch.text())
        if not search_text:
            self.lstSearchResult.clear()
            return

        # if 1 == 1 and self.search_threads:
        #     # print 'Kill ', self.search_threads
        #     self.search_threads.terminate()
        #     self.search_threads.wait()
        if self.search_threads:
            self.search_threads.data_downloaded.disconnect()
            self.search_threads.data_download_finished.disconnect()
            self.search_threads.stop()
            self.search_threads.wait()
            self.lstSearchResult.clear()

        self.show_progress()
        searcher = SearchThread(search_text, self.one_process_work, self.iface.mainWindow())
        searcher.data_downloaded.connect(self.show_result)
        searcher.error_occurred.connect(self.show_error)
        searcher.data_download_finished.connect(self.stop_progress)
        self.search_threads = searcher
        searcher.start()

    def show_progress(self):
        self.lstSearchResult.clear()
        self.lstSearchResult.insertItem(0, self.tr('Searching...'))
    def stop_progress(self):
        self.lstSearchResult.takeItem(0)

    def show_result(self, geoservice, image_ba):
        # self.lstSearchResult.clear()
        if geoservice:
            custom_widget = QmsSearchResultItemWidget(geoservice, image_ba)
            new_item = QListWidgetItem(self.lstSearchResult)
            new_item.setSizeHint(custom_widget.sizeHint())
            # new_item.setText(
            #     unicode(geoservice['name']) + ' [%s]' % geoservice['type'].upper()
            # )
            # new_item.setData(Qt.UserRole, geoservice)

            # todo: remake with cache icons
            self.lstSearchResult.addItem(new_item)
            self.lstSearchResult.setItemWidget(
                new_item,
                custom_widget
            )

        else:
            new_item = QListWidgetItem()
            new_item.setText(self.tr('No results!'))
            new_item.setData(Qt.UserRole, None)
            self.lstSearchResult.addItem(new_item)

        self.lstSearchResult.update()

    def show_error(self, error_text):
        # print error_text
        self.lstSearchResult.clear()
        self.lstSearchResult.addItem(error_text)

    def result_selected(self, current=None, previous=None):
        if current:
            try:
                QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
                geoservice = current.data(Qt.UserRole)
                client = Client()
                client.set_proxy(*QGISSettings.get_qgis_proxy())
                geoservice_info = client.get_geoservice_info(geoservice)
                ds = DataSourceSerializer.read_from_json(geoservice_info)
                add_layer_to_map(ds)
            except Exception as ex:
                print ex.message
                pass
            finally:
                QApplication.restoreOverrideCursor()


class QmsSearchResultItemWidget(QWidget):
    def __init__(self, geoservice, image_ba, parent=None):
        QWidget.__init__(self, parent)

        self.layout = QHBoxLayout(self)
        # self.layout.addSpacing(0)
        self.layout.setContentsMargins(5, 10, 5, 10)
        self.setLayout(self.layout)

        self.service_icon = QLabel(self)
        self.service_icon.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.service_icon.resize(24, 24)

        qimg = QImage.fromData(image_ba)
        pixmap = QPixmap.fromImage(qimg)
        self.service_icon.setPixmap(pixmap)
        self.layout.addWidget(self.service_icon)

        self.service_desc = QLabel(self)
        self.service_desc.setTextFormat(Qt.RichText)
        self.service_desc.setOpenExternalLinks(True)
        self.service_desc.setWordWrap(True)

        # geoservice_info = client.get_geoservice_info(geoservice)
        # ds = DataSourceSerializer.read_from_json(geoservice_info)
        # print "ds.icon: ", ds.icon
        # print "ds.icon_path: ", ds.icon_path

        self.service_desc.setText(
            "<strong> {} </strong><div style=\"margin-top: 3px\">{}, <a href=\"{}\">  details <a/> <div/>".format(
            # "{}<div style=\"margin-top: 3px\"> <em> {} </em>, <a href=\"{}\">  details <a/> <div/>".format(
                geoservice.get('name', ""),
                geoservice.get('type', "").upper(),
                Client().geoservice_info_url(geoservice.get('id', ""))
            )
        )
        self.layout.addWidget(self.service_desc)

        self.addButton = QToolButton()
        self.addButton.setText("Add")
        self.addButton.clicked.connect(self.addToMap)
        self.layout.addWidget(self.addButton)

        # self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.geoservice = geoservice

    def addToMap(self):
        try:
            QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
            client = Client()
            client.set_proxy(*QGISSettings.get_qgis_proxy())
            geoservice_info = client.get_geoservice_info(self.geoservice)
            ds = DataSourceSerializer.read_from_json(geoservice_info)
            add_layer_to_map(ds)
        except Exception as ex:
            print ex.message
            pass
        finally:
            QApplication.restoreOverrideCursor()

    def mouseDoubleClickEvent(self, event):
        self.addToMap()

class SearchThread(QThread):

    data_download_finished = pyqtSignal()
    data_downloaded = pyqtSignal(object, QByteArray)
    error_occurred = pyqtSignal(object)

    def __init__(self, search_text, mutex, parent=None):
        QThread.__init__(self, parent)
        self.search_text = search_text
        self.searcher = Client()
        self.searcher.set_proxy(*QGISSettings.get_qgis_proxy())
        self.mutex = mutex

        self.img_cach = {}

        self.need_stop = False

    def run(self):
        results = []

        # search
        try:
            self.mutex.lock()
            results = self.searcher.search_geoservices(self.search_text)

            for result in results:
                if self.need_stop:
                    break

                ba = QByteArray()

                icon_id = result.get("icon")
                
                if not self.img_cach.has_key(icon_id):
                    if icon_id:
                        ba = QByteArray(self.searcher.get_icon_content(icon_id, 24, 24))
                    else:
                        ba = QByteArray(self.searcher.get_default_icon(24, 24))

                    self.img_cach[icon_id] = ba

                else:
                    ba = self.img_cach[icon_id]

                self.data_downloaded.emit(result, ba)
        except URLError:
                        error_text = (self.tr("Network error!\n{0}")).format(unicode(sys.exc_info()[1]))
                        # error_text = 'net'
                        self.error_occurred.emit(error_text)
        except Exception:
                        error_text = (self.tr("Error of processing!\n{0}: {1}")).format(unicode(sys.exc_info()[0].__name__), unicode(sys.exc_info()[1]))
                        # error_text = 'common'
                        self.error_occurred.emit(error_text)

        self.data_download_finished.emit()
        self.mutex.unlock()

    def stop(self):
        self.need_stop = True
