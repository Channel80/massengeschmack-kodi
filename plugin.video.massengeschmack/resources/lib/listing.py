# -*- coding: utf-8 -*-
#
# Massengeschmack Kodi add-on
# Copyright (C) 2013-2016 by Janek Bevendorff
# Modifications Copyright (C) 2024-2026 by Dirk Tietke
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import xbmc
import xbmcplugin
import xbmcgui

from globalvars import *


class Listing(object):
    def __init__(self):
        self.__source = None

    def generate(self, source):
        """
        Generate listing from data source.
        Will return False if the given DataSource does not intend to return a non-empty listing generator,
        i.e. when L{resources.lib.datasource.DataSource.hasListItems} returns False

        @type source: resources.lib.datasource.DataSource
        @param source: the data source object
        @rtype: bool
        @return Whether the given DataSource actually intends to return a non-empty listing
        """
        if not source.hasListItems():
            return False

        self.__source = source
        xbmcplugin.setContent(ADDON_HANDLE, source.getContentMode())
        for i in source.getListItems():
            self.__addDir(i)

        return True

    def show(self):
        """
        Show the listing after it has been generated.
        You should check the output of L{generate} before trying to show a listing.
        """
        content = self.__source.getContentMode()
        xbmcplugin.setContent(ADDON_HANDLE, content)
        # Kodi soll die gespeicherte Reihenfolge nicht alphabetisch umsortieren.
        xbmcplugin.addSortMethod(ADDON_HANDLE, xbmcplugin.SORT_METHOD_NONE)
        # Ohne Zwischenspeicher. Eine alte Dateiliste würde sonst immer wieder
        # geladen und die Beschreibung bliebe unsichtbar.
        xbmcplugin.endOfDirectory(ADDON_HANDLE, succeeded=True, updateListing=False, cacheToDisc=False)
        self._applyView()

    def _applyView(self):
        """
        Confluence: 504 ist Medieninformationen.
        Liste links, Bild oben rechts, Beschreibung darunter.
        Die Ansicht gibt es nur, wenn der Inhalt Sendungen oder Folgen ist,
        nicht bei einer gewöhnlichen Dateiliste.
        """
        skin = xbmc.getSkinDir().lower()
        content = self.__source.getContentMode()
        if content not in ('tvshows', 'episodes'):
            return
        if 'confluence' in skin:
            mode = 504
        elif 'estuary' in skin:
            mode = 50
        else:
            if 'false' == ADDON.getSetting('advanced.adjustViewModes'):
                return
            if 'true' == ADDON.getSetting('advanced.viewmodeFix'):
                mode = 510
            else:
                mode = self.__source.getViewMode()
        current = xbmc.getInfoLabel('Container.Viewmode')
        if current == str(mode):
            return
        xbmc.log('Massengeschmack: Inhalt %s, Skin %s, Ansicht %s' % (
            content, skin, mode), xbmc.LOGINFO)
        xbmc.executebuiltin('Container.SetViewMode(%d)' % mode)
        if mode in (50, 504):
            xbmc.sleep(120)
            if xbmc.getInfoLabel('Container.Viewmode') != str(mode):
                xbmc.executebuiltin('Container.SetViewMode(%d)' % mode)

    def __addDir(self, listItem):
        xbmcListItem = xbmcgui.ListItem(listItem.getData('name'))
        info = listItem.getData('streamInfo')
        if not isinstance(info, dict):
            info = {}
        else:
            info = dict(info)

        if self.__source is not None and self.__source.getContentMode() == 'tvshows' and not info.get('mediatype'):
            info['mediatype'] = 'tvshow'

        self._applyVideoInfo(xbmcListItem, info, listItem.getData('name'))

        fanart = listItem.getData('fanart') or ''
        thumb = listItem.getData('thumbnail') or ''
        picture = thumb or fanart

        xbmcListItem.setArt({'thumb' : picture,
                             'icon'  : picture,
                             'poster': picture,
                             'banner': picture,
                             'fanart': fanart or picture})

        xbmcplugin.addDirectoryItem(ADDON_HANDLE, url=listItem.getData('url'), listitem=xbmcListItem,
                                    isFolder=listItem.getData('isFolder'))

    def _applyVideoInfo(self, xbmcListItem, info, name):
        plot = info.get('plot') or ''
        title = info.get('title') or name or ''
        if hasattr(xbmcListItem, 'getVideoInfoTag'):
            tag = xbmcListItem.getVideoInfoTag()
            if title:
                tag.setTitle(str(title))
            if plot:
                tag.setPlot(str(plot))
            if info.get('premiered'):
                tag.setPremiered(str(info['premiered']))
            if info.get('mediatype'):
                tag.setMediaType(str(info['mediatype']))
            duration = info.get('duration')
            if isinstance(duration, int) and duration > 0:
                tag.setDuration(duration)

        safe = {}
        for key, value in info.items():
            if isinstance(value, (str, int)):
                safe[key] = value
        if safe:
            xbmcListItem.setInfo(type='video', infoLabels=safe)


class ListItem:
    def __init__(self, id=0, name='', url='', thumbnail='', fanart='', streamInfo=None, isFolder=True):
        """
        Generate list item from given parameters.

        @type id         : int
        @param id        : numeric ID of the listed show
        @type name       : str
        @param name      : the display name of the list item
        @type  url       : str
        @param url       : the addon URL this item points to (should not be a real Internet URL)
        @type  thumbnail : str
        @param thumbnail : the path/URL to a thumbnail image
        @type  fanart    : str
        @param fanart    : the path/URL to a fanart image
        @type streamInfo : dict
        @param streamInfo: stream information for passing to xbmcgui.ListeItem.addStreamInfo()
        @type  isFolder  : bool
        @param isFolder  : True if this item is a folder
        """
        if streamInfo is None:
            streamInfo = {}

        self.__data = {
            'id'        : id,
            'name'      : name,
            'url'       : url,
            'thumbnail' : thumbnail,
            'fanart'    : fanart,
            'streamInfo': streamInfo,
            'isFolder'  : isFolder
        }

    def setData(self, key, value):
        """
        Set a value for this list item.

        @type key: str
        @param key: the name of the data record
        @type value: int|str|dict
        @param value: the data (either a string, a dict or a bool)
        """
        self.__data[key] = value

    def getData(self, key):
        """
        Get specific data from this list item.

        @type key: str
        @param key: which data to retrieve (name, url, iconImage, metaData)
        @return mixed: the data or '' if nothing has been set or key is invalid
        """
        if key in self.__data:
            return self.__data[key]

        return ''
