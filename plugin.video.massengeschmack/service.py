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

import os

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

ADDON = xbmcaddon.Addon()
VERSION = ADDON.getAddonInfo('version')
PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
MARKER = os.path.join(PROFILE, 'cache-bust.txt')


def _read_marker():
    if not xbmcvfs.exists(MARKER):
        return ''
    handle = xbmcvfs.File(MARKER)
    try:
        text = handle.read()
    finally:
        handle.close()
    if not isinstance(text, str):
        text = text.decode('utf-8', 'replace')
    return text.strip()


def _join(base, name):
    if base.endswith('/') or base.endswith('\\'):
        return base + name
    return base + '/' + name


def _bust_directory_cache():
    """
    Kodi speichert langsame Plugin-Listen unter special://temp/archive_cache.
    Diese Kopie enthält noch den alten Inhaltstyp "Dateien". Solange sie liegt,
    startet das Addon nicht neu und Medieninformationen bleiben ausgeblendet.
    """
    cache = xbmcvfs.translatePath('special://temp/archive_cache')
    try:
        _dirs, files = xbmcvfs.listdir(cache)
    except Exception:
        files = []
    removed = 0
    for name in files:
        if name.endswith('.fi'):
            if xbmcvfs.delete(_join(cache, name)):
                removed += 1
    xbmc.log('Massengeschmack: %d zwischengespeicherte Listen entfernt' % removed, xbmc.LOGINFO)

    if not xbmcvfs.exists(PROFILE):
        xbmcvfs.mkdirs(PROFILE)
    handle = xbmcvfs.File(MARKER, 'w')
    try:
        handle.write(VERSION)
    finally:
        handle.close()

    folder = xbmc.getInfoLabel('Container.FolderPath')
    if 'plugin.video.massengeschmack' in folder:
        xbmc.executebuiltin('Container.Refresh')


if _read_marker() != VERSION:
    _bust_directory_cache()

import resources.lib as lib

lib.rebuildSettings()

_monitor = xbmc.Monitor()
_settingsWereOpen = False
_ORDER_PROPERTY = 'MassengeschmackOrder'
while not _monitor.abortRequested():
    if xbmc.getCondVisibility('Window.IsVisible(addonsettings)'):
        if xbmcgui.Window(10000).getProperty(_ORDER_PROPERTY) == '1':
            xbmcgui.Window(10000).setProperty(_ORDER_PROPERTY, '')
            lib.orderShows()
    _open = xbmc.getCondVisibility('Window.IsVisible(addonsettings)')
    if _open:
        _settingsWereOpen = True
    elif _settingsWereOpen:
        _settingsWereOpen = False
        lib.rebuildSettings()
        _folder = xbmc.getInfoLabel('Container.FolderPath')
        if 'plugin.video.massengeschmack' in _folder and 'module=' not in _folder:
            xbmc.executebuiltin('Container.Refresh')
    if _monitor.waitForAbort(0.2):
        break
