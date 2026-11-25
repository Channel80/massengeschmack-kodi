# -*- coding: utf-8 -*-
#
# Copyright (C) 2024-2026 by Dirk Tietke
# Original add-on Copyright (C) 2013-2016 by Janek Bevendorff

import os

import xbmc
import xbmcgui

import resources.lib as lib


class ShowOrderWindow(xbmcgui.WindowDialog):
    """Dialog über den Einstellungen. Klick greift, Pfeiltasten schieben, Klick legt ab."""

    def __init__(self):
        xbmcgui.WindowDialog.__init__(self)
        self.items = lib.orderItems()
        self.held = None
        self._build()
        self._fill()

    def _build(self):
        addon = lib.ADDON
        self.addControl(xbmcgui.ControlImage(0, 0, 1280, 720, self._image('dim.png')))
        self.addControl(xbmcgui.ControlImage(150, 28, 980, 664, self._image('panel.png')))
        self.addControl(xbmcgui.ControlLabel(
            174, 42, 932, 32,
            addon.getLocalizedString(30074), 'font13', '0xFFFFFFFF'))
        self.addControl(xbmcgui.ControlLabel(
            174, 76, 932, 28,
            addon.getLocalizedString(30094), 'font12', '0xFFDDDDDD'))
        self.list = xbmcgui.ControlList(174, 114, 932, 480, 'font13', '0xFFFFFFFF')
        self.addControl(self.list)
        self.done = xbmcgui.ControlButton(
            500, 610, 280, 48, addon.getLocalizedString(30079),
            'button-focus.png', 'button-nofocus.png')
        self.addControl(self.done)
        self.list.setNavigation(self.list, self.list, self.done, self.done)
        self.done.setNavigation(self.done, self.done, self.list, self.list)

    def _image(self, name):
        return os.path.join(lib.ADDON.getAddonInfo('path'), 'resources', 'media', name)

    def _fill(self):
        xbmc.log('Massengeschmack: Reihenfolge mit %d Sendungen' % len(self.items), xbmc.LOGINFO)
        for index in range(len(self.items)):
            self.list.addItem(self._row_label(index))
        try:
            if self.items:
                self.setFocus(self.list)
                self.list.selectItem(0)
            else:
                self.setFocus(self.done)
        except RuntimeError:
            pass

    def onAction(self, action):
        action_id = action.getId()
        if action_id in (10, 92):
            self.close()
            return
        if self.held is None or action_id not in (3, 4, 5, 6):
            return
        new_pos = self.list.getSelectedPosition()
        if new_pos < 0 or new_pos == self.held or new_pos >= len(self.items):
            return
        moved = self.items.pop(self.held)
        self.items.insert(new_pos, moved)
        self.held = new_pos
        self._paint()
        self._save()

    def onControl(self, control):
        if control == self.done:
            self.close()
            return
        if control != self.list or not self.items:
            return
        pos = self.list.getSelectedPosition()
        if pos < 0:
            return
        self.held = None if self.held is not None else pos
        self._paint()

    def close(self):
        self._save()
        lib._refreshListing()
        xbmcgui.WindowDialog.close(self)

    def _row_label(self, index):
        title = '%d   %s' % (index + 1, self.items[index]['title'])
        if index == self.held:
            return '[COLOR yellow]%s[/COLOR]' % (lib.ADDON.getLocalizedString(30097) % title)
        return title

    def _paint(self):
        for index in range(len(self.items)):
            self.list.getListItem(index).setLabel(self._row_label(index))

    def _save(self):
        state = lib._loadLibraryState()
        state['sequence'] = [item['module'] for item in self.items]
        lib._saveLibraryState(state)
