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
import xbmcgui
import xbmcplugin
import xbmcvfs
import urllib.request, urllib.parse, urllib.error
import urllib.request, urllib.error, urllib.parse
import glob
import os
import time
import re
import json
from datetime import datetime, tzinfo, timedelta
from xml.dom import minidom
from xml.sax.saxutils import escape
from html import unescape

from globalvars import *
from . import listing
from . import datasource

# Massengeschmack API v1: offiziell max. 10 Anfragen pro 30 Sekunden
_API_RATE_WINDOW = 30.0
_API_RATE_MAX = 8
_api_request_times = []
_readApi_cache = {}


# enable non-GET HTTP requests using urllib2
class PostRequest(urllib.request.Request):
    def get_method(self):
        return 'POST'


class HeadRequest(urllib.request.Request):
    def get_method(self):
        return 'HEAD'


# helper functions
def _isApiUri(uri):
    return HTTP_BASE_API_URI in uri


def _waitForApiQuota():
    """Hält die API-Anfragen unter dem Server-Limit."""
    global _api_request_times
    while True:
        now = time.time()
        _api_request_times = [stamp for stamp in _api_request_times if now - stamp < _API_RATE_WINDOW]
        if len(_api_request_times) < _API_RATE_MAX:
            _api_request_times.append(now)
            return
        delay = _API_RATE_WINDOW - (now - _api_request_times[0]) + 0.2
        if delay <= 0:
            _api_request_times = []
            continue
        xbmc.sleep(min(int(delay * 1000), 35000))


def _retryAfterFromError(error):
    try:
        raw = error.read()
        if isinstance(raw, bytes):
            raw = raw.decode('utf-8', 'replace')
        payload = json.loads(raw)
        return int(payload.get('retryAfter', 30))
    except (TypeError, ValueError, json.JSONDecodeError, OSError, AttributeError):
        return 30


def _httpOpenOnce(uri, requestMethod='GET'):
    requestMethod = requestMethod.upper()
    if 'POST' == requestMethod:
        request = PostRequest(uri)
    elif 'HEAD' == requestMethod:
        request = HeadRequest(uri)
    else:
        request = urllib.request.Request(uri)

    request.add_header('User-Agent', HTTP_USER_AGENT)

    handle = None
    response = {
        'code'   : 200,
        'reason' : ''
    }

    try:
        handle = urllib.request.urlopen(request, None, HTTP_TIMEOUT)
    except urllib.error.HTTPError as e:
        response['code'] = e.code
        response['reason'] = e.reason
        if e.code == 429:
            response['retry_after'] = _retryAfterFromError(e)
    except urllib.error.URLError as e:
        response['code'] = -1
        response['reason'] = e.reason

    return handle, response


def openHTTPConnection(uri, requestMethod='GET'):
    """
    Open an HTTP(S) connection and return the connection handle as well as a response info dict.
    The response dict has the following structure:

    {
        'code'          : HTTP response code,
        'reason'        : error description if code is not 200
    }

    If a network error occurs, code is -1 and reason contains an error description.
    In that case, None is returned instead of the handle. No exception will be thrown.

    @type uri: str
    @param uri: the request URI
    @type requestMethod: str
    @param requestMethod: the HTTP request method (either GET, POST or HEAD)
    @rtype urllib2.Request, dict
    @return: request handle and response info dict
    """
    if not _isApiUri(uri):
        return _httpOpenOnce(uri, requestMethod)

    _waitForApiQuota()
    handle, response = _httpOpenOnce(uri, requestMethod)
    if response.get('code') != 429:
        return handle, response

    wait_s = int(response.get('retry_after', 30))
    if handle:
        handle.close()
    xbmc.log('Massengeschmack: API-Limit, warte %ds' % wait_s, xbmc.LOGINFO)
    xbmc.sleep(min(wait_s + 1, 45) * 1000)
    _waitForApiQuota()
    return _httpOpenOnce(uri, requestMethod)


def handleHttpStatus(response):
    """
    Handle given HTTP status.
    If status is != 200, an appropriate error message will be shown and the script will be terminated
    afterwards. In case of 200, nothing happens

    @param response: response info dict as returned by L{openHTTPConnection}
    """
    if 200 == response['code']:
        return

    dialog = xbmcgui.Dialog()
    if -1 == response['code']:
        dialog.ok(ADDON.getLocalizedString(30902), ADDON.getLocalizedString(30903) +
                  '[CR]Error: {0}'.format(response['reason']))
    elif 401 == response['code']:
        dialog.ok(ADDON.getLocalizedString(30102), ADDON.getLocalizedString(30103))
        ADDON.openSettings()
    elif 429 == response['code']:
        dialog.ok(ADDON.getLocalizedString(30902), ADDON.getLocalizedString(30106))
        exit(1)
    elif 500 == response['code']:
        dialog.ok(ADDON.getLocalizedString(30902), ADDON.getLocalizedString(30106))
    else:
        dialog.ok(ADDON.getLocalizedString(30902), ADDON.getLocalizedString(30904) +
                  '[CR]Error: {0} {1}'.format(response['code'], response['reason']))
    exit(1)


def installHTTPLoginData(username, password):
    """
    Register the HTTP login data for accessing feeds later on.

    @type username: str
    @type password: str
    """
    passwordManager = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    passwordManager.add_password(None, HTTP_BASE_URI, username, password)
    authHandler = urllib.request.HTTPBasicAuthHandler(passwordManager)
    opener      = urllib.request.build_opener(authHandler)
    urllib.request.install_opener(opener)


def probeLogin(showDialog=False):
    """
    Test if the given login credentials are correct and return response info dict.

    Login data need to be installed beforehand using installHTTPLoginData().

    @type showDialog: bool
    @param showDialog: whether to show a progress dialog while testing
    @return: HTTP status info dict as returned by L{openHTTPConnection}
    """
    probe_stamp = os.path.join(xbmcvfs.translatePath(ADDON.getAddonInfo('profile')), 'last-probe.txt')
    try:
        if os.path.isfile(probe_stamp) and time.time() - os.path.getmtime(probe_stamp) < 300:
            if showDialog:
                dialog = xbmcgui.DialogProgress()
                dialog.create(ADDON.getLocalizedString(30104))
                dialog.update(100)
                del dialog
            return {'code': 200, 'reason': ''}
    except OSError:
        pass

    if showDialog:
        dialog = xbmcgui.DialogProgress()
        dialog.create(ADDON.getLocalizedString(30104))
        dialog.update(50)

    handle, info = openHTTPConnection(HTTP_BASE_API_URI + '/?action=getFeed&from=[]&limit=1', requestMethod='HEAD')
    if handle:
        handle.close()

    if 200 == info['code']:
        try:
            profile = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
            if not xbmcvfs.exists(profile):
                xbmcvfs.mkdirs(profile)
            stamp = os.path.join(profile, 'last-probe.txt')
            with open(stamp, 'w', encoding='utf-8') as probe_file:
                probe_file.write(str(int(time.time())))
        except OSError:
            pass

    if showDialog:
        dialog.update(100)
        del dialog

    return info


def getLiveShows(recordings=False):
    """
    Return a list of dictionaries with information about current and upcoming live shows.
    This method does no exception handling, so make sure the login credentials are correct.

    @type recordings: bool
    @param recordings: whether to return recorded past shows instead of current and upcoming
    @return: dictionary list of live streams
    """

    action = '/?action=listLiveShows'
    if recordings:
        action += '&listRecordings'

    handle, info = openHTTPConnection(HTTP_BASE_API_URI + action)
    handleHttpStatus(info)

    liveShows = json.loads(handle.read())
    handle.close()

    return liveShows


def _normalizeImageUrl(url):
    text = str(url or '').strip()
    if not text:
        return ''
    if text.startswith('//'):
        return 'https:' + text
    return text


def showCurrentShows():
    """
    Holt den Katalog und legt fehlende Formate lokal ab.
    Der Hinweis danach nennt nur, wie viele neu hinzugekommen sind.
    """
    progress = xbmcgui.DialogProgress()
    progress.create(ADDON.getLocalizedString(30063))
    progress.update(30)
    try:
        main, mainInfo = _readApi('getMainFeed', cache_seconds=120)
        progress.update(70)
        subscriptions, _ignored = _readApi('listSubscriptions', cache_seconds=600)
    finally:
        progress.close()

    if isinstance(main, dict) and main.get('api_error'):
        xbmcgui.Dialog().ok(ADDON.getLocalizedString(30064), str(main.get('api_error')))
        return
    if main is None:
        handleHttpStatus(mainInfo)
        return

    catalog = {}
    episodes = main if isinstance(main, list) else main.get('eps', []) if isinstance(main, dict) else []
    for episode in episodes:
        if not isinstance(episode, dict) or episode.get('pid') is None:
            continue
        pid = int(episode['pid'])
        if pid < 0:
            continue
        stamp = _episodeStamp(episode.get('date'))
        current = catalog.get(pid)
        if current is None or stamp >= current['stamp']:
            catalog[pid] = {
                'pid': pid,
                'name': str(episode.get('pdesc') or episode.get('title') or pid),
                'stamp': stamp,
                'desc': str(episode.get('desc') or ''),
                'thumb': _normalizeImageUrl(episode.get('img') or episode.get('thumbnail') or ''),
            }

    for entry in _subscriptionEntries(subscriptions):
        pid = entry['pid']
        item = catalog.setdefault(pid, {'pid': pid, 'name': '', 'stamp': 0, 'desc': '', 'thumb': ''})
        if entry['name']:
            item['name'] = entry['name']

    if not catalog:
        xbmcgui.Dialog().ok(ADDON.getLocalizedString(30064), ADDON.getLocalizedString(30066))
        return

    known = _knownShowModules()
    before = len(known)
    names = _knownShowNames()
    state = _loadLibraryState()
    seen = dict(state.get('seen') or {})
    added = []
    fresh = sorted(catalog.values(), key=lambda item: (-item['stamp'], item['name'].lower()))
    for item in fresh:
        if item['stamp']:
            seen[str(item['pid'])] = item['stamp']
        if item['pid'] in known or not item['name'] or _showNameKnown(item['name'], names):
            continue
        module = _writeShowFile(item, set(known.values()), order=-(len(added) + 1))
        known[item['pid']] = module
        names.add(_nameKey(item['name']))
        added.append(module)

    _syncUserShowsFromCatalog(catalog)
    state['seen'] = seen
    _saveLibraryState(state)
    if added:
        _boostModules(added)
        prependToSequence(added)

    message = ADDON.getLocalizedString(30082) % (len(catalog), len(added), before)
    rebuildSettings()
    _refreshListing()
    xbmcgui.Dialog().ok(ADDON.getLocalizedString(30064), message)
    if added:
        orderShows()


def orderShows():
    """Reihenfolge in den Einstellungen: markieren, Pfeiltaste, OK zum Einsetzen."""
    if (ADDON.getSetting('content.sort') or '0') != '0':
        return
    items = orderItems()
    if not items:
        return
    dialog = xbmcgui.Dialog()
    held = None
    focus = 0
    done_label = ADDON.getLocalizedString(30079)
    mark_fmt = ADDON.getLocalizedString(30097)
    title = ADDON.getLocalizedString(30074)
    while True:
        labels = []
        for index, item in enumerate(items):
            row = '%d   %s' % (index + 1, item['title'])
            if index == held:
                row = mark_fmt % row
            labels.append(row)
        labels.append(done_label)
        choice = dialog.select(title, labels, preselect=focus)
        if choice < 0 or choice >= len(labels) - 1:
            break
        if held is None:
            held = choice
            focus = choice
            continue
        if choice == held:
            held = None
            focus = choice
            continue
        moved = items.pop(held)
        items.insert(choice, moved)
        state = _loadLibraryState()
        state['sequence'] = [item['module'] for item in items]
        _saveLibraryState(state)
        held = None
        focus = choice
    _refreshListing()


def hideShows():
    """Ausgewählte Formate erscheinen nicht mehr in der Liste."""
    library = _libraryShows()
    library.sort(key=lambda item: item['title'].lower())
    state = _loadLibraryState()
    hidden = set(state.get('hidden') or [])
    labels = [item['title'] for item in library]
    preselect = [index for index, item in enumerate(library) if item['module'] in hidden]
    chosen = xbmcgui.Dialog().multiselect(ADDON.getLocalizedString(30083), labels, preselect=preselect)
    if chosen is None:
        return
    state['hidden'] = [library[index]['module'] for index in chosen]
    _saveLibraryState(state)
    _syncHiddenSettings()
    _refreshListing()


def userShowDir():
    path = os.path.join(_profileDir(), 'shows')
    if not os.path.isdir(path):
        os.makedirs(path)
    return path


def showStamps():
    seen = _loadLibraryState().get('seen') or {}
    stamps = {}
    for key, value in seen.items():
        try:
            stamps[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return stamps


def showPriorities():
    _migratePriorities()
    state = _loadLibraryState()
    stored = {} if state.get('priorityMigrated') else _cleanPriorities(state.get('priority'))
    boost = _cleanPriorities(state.get('boost'))
    result = {}
    for item in _libraryShows():
        number = _settingNumber(item['module'])
        if item['module'] in boost and number != boost[item['module']]:
            number = boost[item['module']]
        elif number <= 0:
            number = stored.get(item['module'], 0)
        if number > 0:
            result[item['module']] = number
    return result


def showSequence():
    return list(_loadLibraryState().get('sequence') or [])


def rankedVisibleShows():
    _pinUserShowsOnce()
    _applyBoost()
    hidden = hiddenModules()
    priorities = showPriorities()
    shows = [item for item in _libraryShows() if item['module'] not in hidden]
    shows.sort(key=lambda item: showRankKey(
        item['module'], item['active'], item['order'], item['title'], priorities))
    return shows


def prependToSequence(modules):
    modules = [module for module in modules if module]
    if not modules:
        return
    state = _loadLibraryState()
    if state.get('sequence'):
        base = list(state['sequence'])
    else:
        base = [item['module'] for item in rankedVisibleShows()]
        state = _loadLibraryState()
    skip = set(modules)
    state['sequence'] = list(modules) + [module for module in base if module not in skip]
    _saveLibraryState(state)


def orderItems():
    hidden = hiddenModules()
    shows = [item for item in _libraryShows() if item['module'] not in hidden]
    by_module = {item['module']: item for item in shows}
    sequence = showSequence()
    if not sequence:
        items = rankedVisibleShows()
        state = _loadLibraryState()
        state['sequence'] = [item['module'] for item in items]
        _saveLibraryState(state)
        return items
    items = [by_module[module] for module in sequence if module in by_module]
    known = {item['module'] for item in items}
    missing = [item for item in shows if item['module'] not in known]
    stamps = showStamps()
    missing.sort(key=lambda item: (-stamps.get(str(item['pid']), 0), item['title'].lower()))
    if missing:
        items = missing + items
        state = _loadLibraryState()
        state['sequence'] = [item['module'] for item in items]
        _saveLibraryState(state)
    return items


def rebuildSettings():
    """Entfernt die alten Zahlen-Drehregler aus den Einstellungen."""
    xml = _SETTINGS_HEAD
    path = os.path.join(ADDON_BASE_PATH, 'resources', 'settings.xml')
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            current = handle.read()
    except OSError:
        current = ''
    if current == xml:
        return
    try:
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(xml)
    except OSError as error:
        xbmc.log('Massengeschmack: Einstellungen nicht geschrieben (%s)' % error, xbmc.LOGWARNING)


def showRankKey(module, active, storedOrder, title, priorities):
    """Höhere Sortierzahl steht weiter oben. Gleiche Zahlen folgen der gespeicherten Liste."""
    try:
        number = int(priorities.get(module, 0) or 0)
    except (TypeError, ValueError):
        number = 0
    if number < 0:
        number = 0
    return (-number, 0 if active else 1, storedOrder, str(title).lower())


def _sortSettingId(module):
    return 'sort.' + module


def _isUserModule(module):
    user_file = os.path.join(userShowDir(), module + '.json')
    builtin_file = os.path.join(ADDON_BOOTSTRAP_PATH, module + '.json')
    return os.path.isfile(user_file) and not os.path.isfile(builtin_file)


def _boostModules(modules):
    """Neue Formate bekommen die höchsten Zahlen, das neueste ganz oben."""
    if not modules:
        return
    state = _loadLibraryState()
    boost = _cleanPriorities(state.get('boost'))
    shows = _libraryShows()
    number = len(shows)
    for module in modules:
        boost[module] = number
        number -= 1
    state['boost'] = boost
    _saveLibraryState(state)


def _pinUserShowsOnce():
    """Bereits abgefragte Formate einmal nach oben setzen."""
    state = _loadLibraryState()
    if state.get('userShowsPinned'):
        return
    shows = _libraryShows()
    stamps = showStamps()
    user = [item for item in shows if _isUserModule(item['module']) and _settingNumber(item['module']) <= 0]
    user.sort(key=lambda item: (-stamps.get(str(item['pid']), 0), item['title'].lower()))
    state['userShowsPinned'] = True
    _saveLibraryState(state)
    _boostModules([item['module'] for item in user])


def _applyBoost():
    state = _loadLibraryState()
    boost = _cleanPriorities(state.get('boost'))
    if not boost:
        return
    pending = {}
    for module, number in boost.items():
        if _settingNumber(module) == number:
            continue
        ADDON.setSetting(_sortSettingId(module), str(number))
        if _settingNumber(module) != number:
            pending[module] = number
    state['boost'] = pending
    _saveLibraryState(state)


def _hiddenSettingId(module):
    return 'hidden.' + module


def _syncHiddenSettings():
    """Blendet ausgeblendete Formate in der Sendungsreihenfolge sofort aus."""
    hidden = hiddenModules()
    for item in _libraryShows():
        value = 'true' if item['module'] in hidden else 'false'
        if ADDON.getSetting(_hiddenSettingId(item['module'])).lower() != value:
            ADDON.setSetting(_hiddenSettingId(item['module']), value)


def _settingNumber(module):
    raw = ADDON.getSetting(_sortSettingId(module))
    try:
        number = int(raw)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _migratePriorities():
    state = _loadLibraryState()
    if state.get('priorityMigrated'):
        return
    priorities = _cleanPriorities(state.get('priority'))
    if not priorities:
        priorities = _priorityFromOrder(state.get('order') or [])
    for module, number in priorities.items():
        if _settingNumber(module) <= 0 and number > 0:
            ADDON.setSetting(_sortSettingId(module), str(number))
    stored = all(
        number <= 0 or _settingNumber(module) == number
        for module, number in priorities.items()
    )
    if stored:
        state['priorityMigrated'] = True
        state['order'] = []
        state['priority'] = {}
        _saveLibraryState(state)


_SETTINGS_HEAD = '''<?xml version="1.0" encoding="utf-8" standalone="yes"?>
<settings>
    <category label="30001">
        <setting label="30003" type="text" id="account.username" default="" />
        <setting label="30004" type="text" id="account.password" option="hidden" default="" />
        <setting label="30002" type="text" id="account.warning" default="" enable="false" />
    </category>

    <category label="30050">
        <setting label="30051" type="enum" id="content.quality" lvalues="30055|30052|30053" enable="eq(1,false)" default="0" />
        <setting label="30054" type="bool" id="content.audioOnly" default="false" />
        <setting type="sep" />
        <setting id="content.currentShows" label="30063" type="action" action="RunPlugin(plugin://plugin.video.massengeschmack/?cmd=currentShows)" />
        <setting id="content.hideShows" label="30090" type="action" action="RunPlugin(plugin://plugin.video.massengeschmack/?cmd=hideShows)" />
        <setting label="30069" type="enum" id="content.sort" lvalues="30070|30071|30072|30073" default="0" />
        <setting id="content.orderShows" label="30074" type="action" action="SetProperty(MassengeschmackOrder,1,home)" enable="eq(-1,0)" />
    </category>

    <category label="30060">
        <setting label="30062" type="bool" id="advanced.adjustViewModes" default="true" />
        <setting label="30061" type="bool" id="advanced.viewmodeFix" enable="eq(-1,true)" default="false" />
        </category>
</settings>
'''


def _priorityFromOrder(order):
    result = {}
    count = len(order)
    for index, name in enumerate(order):
        if name:
            result[str(name)] = count - index
    return result


def _cleanPriorities(raw):
    result = {}
    if not isinstance(raw, dict):
        return result
    for key, value in raw.items():
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            result[str(key)] = number
    return result


def hiddenModules():
    return set(_loadLibraryState().get('hidden') or [])


def _profileDir():
    path = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
    if not os.path.isdir(path):
        os.makedirs(path)
    return path


def _libraryStatePath():
    return os.path.join(_profileDir(), 'library.json')


def _loadLibraryState():
    path = _libraryStatePath()
    if not os.path.isfile(path):
        return {'hidden': [], 'order': [], 'seen': {}}
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {'hidden': [], 'order': [], 'seen': {}}
    if not isinstance(data, dict):
        return {'hidden': [], 'order': [], 'seen': {}}
    data.setdefault('hidden', [])
    data.setdefault('order', [])
    data.setdefault('seen', {})
    return data


def _saveLibraryState(state):
    path = _libraryStatePath()
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
        handle.write('\n')


def _showFiles():
    files = sorted(glob.glob(os.path.join(ADDON_BOOTSTRAP_PATH, '*.json')))
    shows = userShowDir()
    files.extend(sorted(glob.glob(os.path.join(shows, '*.json'))))
    return files


def _libraryShows():
    found = []
    seen = set()
    for path in _showFiles():
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue
        pid = data.get('id')
        if not isinstance(pid, int) or pid < 0 or pid in seen:
            continue
        seen.add(pid)
        title = data.get('metadata', {}).get('title', '')
        if isinstance(title, int):
            title = ADDON.getLocalizedString(title)
        if not title:
            title = os.path.splitext(os.path.basename(path))[0]
        found.append({
            'module': os.path.splitext(os.path.basename(path))[0],
            'pid': pid,
            'title': str(title),
            'order': data.get('order', pid),
            'active': data.get('active', True)
        })
    return found


_plot_catalog = None


def _plotCatalog():
    """Format-Beschreibungen aus den fest eingebauten datasource-JSONs (nach pid)."""
    global _plot_catalog
    if _plot_catalog is not None:
        return _plot_catalog
    result = {}
    for path in glob.glob(os.path.join(ADDON_BOOTSTRAP_PATH, '*.json')):
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                jd = json.load(handle)
        except (OSError, ValueError):
            continue
        pid = jd.get('id')
        if not isinstance(pid, int) or pid < 0:
            continue
        plot = (jd.get('metadata') or {}).get('plot', '')
        if isinstance(plot, int):
            plot = ADDON.getLocalizedString(plot)
        plot = str(plot or '').strip()
        if plot:
            result[pid] = plot
    _plot_catalog = result
    return _plot_catalog


def formatPlot(pid, title, current_plot=''):
    """
    Liefert eine Format-Beschreibung, keine Folgenzusammenfassung.
    Bekannte Formate: Text aus datasource-JSON; sonst kurzer Standardtext.
    """
    title = str(title or '').strip()
    plot = str(current_plot or '').strip()
    if isinstance(current_plot, int):
        plot = ADDON.getLocalizedString(current_plot)
    builtin = _plotCatalog().get(int(pid) if pid is not None else -1, '')
    if builtin:
        return builtin
    if plot and plot != title and len(plot) <= max(len(title) + 30, 140):
        return plot
    if title:
        return ADDON.getLocalizedString(30110) % title
    return ''


def _knownShowModules():
    return {item['pid']: item['module'] for item in _libraryShows()}


def _syncUserShowsFromCatalog(catalog):
    """
    Aktualisiert Profil-JSONs: Titel und Vorschaubild aus getMainFeed.
    Kein plot aus Folgen- desc: das wäre die letzte Sendung, nicht das Format.
    """
    shows_dir = userShowDir()
    if not os.path.isdir(shows_dir):
        return
    for path in glob.glob(os.path.join(shows_dir, '*.json')):
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue
        pid = data.get('id')
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            continue
        entry = catalog.get(pid)
        if not entry:
            continue
        old_dump = json.dumps(data, ensure_ascii=False, sort_keys=True)
        meta = data.setdefault('metadata', {})
        title = str(meta.get('title') or '')
        name = str(entry.get('name') or title)
        if name and name != title:
            meta['title'] = name
        meta['plot'] = formatPlot(pid, name or title, meta.get('plot', ''))
        data.pop('plot_from_feed', None)
        thumb = _normalizeImageUrl(entry.get('thumb') or '')
        if thumb:
            data['banner_url'] = thumb
        new_dump = json.dumps(data, ensure_ascii=False, sort_keys=True)
        if new_dump == old_dump:
            continue
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=4)
            handle.write('\n')


def _writeShowFile(item, usedNames, order=None):
    base = _slug(item['name']) or ('show-%d' % item['pid'])
    slug = base
    number = 2
    while slug in usedNames or os.path.exists(os.path.join(userShowDir(), slug + '.json')):
        slug = '%s-%d' % (base, number)
        number += 1
    payload = {
        'id': item['pid'],
        'order': item['pid'] if order is None else order,
        'metadata': {
            'title': item['name'],
            'country': 30202,
            'plot': formatPlot(item['pid'], item['name'], '')
        },
        'qualities': ['best', 'hd', 'mobile', 'audio'],
        'submodules': [{'name': 'all', 'ids': [1]}]
    }
    thumb = _normalizeImageUrl(item.get('thumb') or '')
    if thumb:
        payload['banner_url'] = thumb
    path = os.path.join(userShowDir(), slug + '.json')
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=4)
        handle.write('\n')
    return slug


def _nameKey(name):
    return _slug(name).replace('-', '')


def _knownShowNames():
    names = set()
    for item in _libraryShows():
        names.add(_nameKey(item['title']))
        names.add(_nameKey(item['module'].replace('-', ' ')))
    return names


def _showNameKnown(name, names):
    key = _nameKey(name)
    return bool(key) and key in names


def _slug(name):
    text = name.lower()
    for source, target in (('ä', 'ae'), ('ö', 'oe'), ('ü', 'ue'), ('ß', 'ss')):
        text = text.replace(source, target)
    text = re.sub(r'[^a-z0-9]+', '-', text).strip('-')
    return text


def _subscriptionEntries(data):
    if isinstance(data, dict) and not data.get('api_error'):
        entries = data.get('active_subscriptions') or data.get('subscriptions') or []
    elif isinstance(data, list):
        entries = data
    else:
        entries = []
    result = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        pid = entry.get('pid', entry.get('id'))
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            continue
        if pid < 0:
            continue
        name = entry.get('title') or entry.get('name') or ''
        result.append({'pid': pid, 'name': str(name)})
    return result


def _readApi(action, cache_seconds=0):
    if cache_seconds > 0:
        hit = _readApi_cache.get(action)
        if hit and time.time() - hit[0] < cache_seconds:
            return hit[1], {'code': 200, 'reason': ''}

    handle, info = openHTTPConnection(HTTP_BASE_API_URI + '/?action=' + action)
    if not handle or info.get('code') != 200:
        if handle:
            handle.close()
        return None, info
    raw = handle.read()
    handle.close()
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8')
    try:
        data = json.loads(raw)
    except ValueError:
        return None, info
    if cache_seconds > 0 and data is not None:
        if not (isinstance(data, dict) and data.get('api_error')):
            _readApi_cache[action] = (time.time(), data)
    return data, info


def _refreshListing():
    folder = xbmc.getInfoLabel('Container.FolderPath')
    if 'plugin.video.massengeschmack' in folder and 'module=' not in folder:
        xbmc.executebuiltin('Container.Refresh')


def _episodeStamp(value):
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    months = {
        'januar': 1, 'februar': 2, 'märz': 3, 'maerz': 3, 'april': 4,
        'mai': 5, 'juni': 6, 'juli': 7, 'august': 8,
        'september': 9, 'oktober': 10, 'november': 11, 'dezember': 12
    }
    match = re.match(r'(\d{1,2})\.\s*([A-Za-zäöüÄÖÜ]+)\s+(\d{4})', text)
    if match:
        month = months.get(match.group(2).lower())
        if month:
            return int(datetime(int(match.group(3)), month, int(match.group(1))).timestamp())
    for fmt in ('%d.%m.%Y', '%Y-%m-%d'):
        try:
            return int(datetime.strptime(text, fmt).timestamp())
        except ValueError:
            continue
    return 0


def getLiveStreamInfo(id):
    """
    Fetch information about a particular live stream.

    @type id: str
    @param id: the GUID of the live stream, False on error
    """
    handle, info = openHTTPConnection(HTTP_BASE_API_URI + '/?action=getPlaylistUrl&id=' + id)
    handleHttpStatus(info)

    streamInfo = handle.read()
    handle.close()

    streamInfo = json.loads(streamInfo)

    return streamInfo


# feed cache
__fetchedFeeds = {}


def parseRSSFeed(feed, fetch=False):
    """
    Parse an RSS feed and create a list of dicts from the XML data.
    This function is necessary because we can't rely on any third-party
    RSS modules.

    if fetch is true, feed is assumed to be a URI to an RSS feed instead of
    its XML contents.

    The returned list has the following format:
    [
        {
            'title'       : summary1,
            'subtitle'    : subtitle1,
            'pubdate'     : pubdate1,
            'description' : description1,
            'link'        : link1,
            'guid'        : guid1,
            'url'         : url1,
            'duration'    : duration1
        },
        {
            'title'       : summary2,
            'subtitle'    : subtitle2,
            'pubdate'     : pubdate2,
            'description' : description2,
            'link'        : link2,
            'guid'        : guid2,
            'url'         : url2,
            'duration'    : duration2
        },
        ...
    ]

    @type feed: str
    @param feed: the RSS feed as XML string or a URI if fetch is true
    @type fetch: bool
    @param fetch: True if feed is a URI, default is false
    @return a list of dicts with the parsed feed data
    """
    if fetch:
        if feed not in __fetchedFeeds:
            handle, info = openHTTPConnection(feed)
            handleHttpStatus(info)

            __fetchedFeeds[feed] = handle.read()
            handle.close()
        feed = __fetchedFeeds[feed]

    dom = minidom.parseString(feed)

    data = []
    for node in dom.getElementsByTagName('item'):
        # convert duration string to seconds
        duration = 0
        fc = node.getElementsByTagName('itunes:duration')[0].firstChild
        if fc is not None:
            h, m, s  = list(map(int, fc.nodeValue.split(':')))
            duration = timedelta(hours=h, minutes=m, seconds=s).seconds

        description = unescape(node.getElementsByTagName('description')[0].firstChild.nodeValue)

        # episode still sits in the description, before the text
        thumbUrl = ''
        thumbUrlMatch = re.search(r'<img[^>]+src="([^"]+)"', description, re.IGNORECASE)
        if thumbUrlMatch is not None:
            thumbUrl = thumbUrlMatch.group(1)
            if thumbUrl.startswith('//'):
                thumbUrl = 'https:' + thumbUrl
            elif not re.match(r'^https?://', thumbUrl):
                thumbUrl = HTTP_BASE_URI + thumbUrl if thumbUrl.startswith('/') else '/' + thumbUrl

        summary = ''
        summaryNodes = node.getElementsByTagName('itunes:summary')
        if summaryNodes and summaryNodes[0].firstChild is not None:
            summary = unescape(summaryNodes[0].firstChild.nodeValue)

        # itunes:summary is the same text without the picture tag
        if summary.strip():
            description = summary
        else:
            description = re.sub(r'<[^>]*>', '', description)

        description = re.sub(r'\s+', ' ', description).strip()

        subtitle = ''
        subtitleNodes = node.getElementsByTagName('itunes:subtitle')
        if subtitleNodes and subtitleNodes[0].firstChild is not None:
            subtitle = unescape(subtitleNodes[0].firstChild.nodeValue)

        data.append({
            'title'       : unescape(node.getElementsByTagName('title')[0].firstChild.nodeValue),
            'subtitle'    : subtitle,
            'pubdate'     : unescape(node.getElementsByTagName('pubDate')[0].firstChild.nodeValue),
            'description' : description,
            'link'        : unescape(node.getElementsByTagName('link')[0].firstChild.nodeValue),
            'thumbUrl'    : thumbUrl,
            'guid'        : unescape(node.getElementsByTagName('guid')[0].firstChild.nodeValue),
            'url'         : unescape(node.getElementsByTagName('enclosure')[0].getAttribute('url')),
            'duration'    : duration
        })

    return data


class TZOffset(tzinfo):
    """Represent fixed timezone offset east from UTC."""

    def __init__(self, offset, *args, **kwargs):
        super(TZOffset, self).__init__(*args, **kwargs)
        self.__offset = timedelta(minutes=offset)

    def utcoffset(self, dt):
        return self.__offset

    def dst(self, dt):
        return timedelta(0)


def parseUTCDateString(datestr):
    """
    Parse an RFC 2822 date format to a datetime object.

    @type datestr: str
    @param datestr: the date string
    @return a datetime object
    """
    # work around Python bug
    format = '%a, %d %b %Y %H:%M:%S'
    try:
        date = datetime.strptime(datestr[:-6], format)
    except TypeError:
        date = datetime(*(time.strptime(datestr[:-6], format)[0:6]))

    # add timezone info which isn't possible using %z in Python 2
    offset  = int(datestr[-5:-2]) * 60
    offset += int(datestr[-5:-4] + '1') * int(datestr[-2:])
    offset  = TZOffset(offset)
    date    = date.replace(tzinfo=offset)

    return date


def dictUrlEncode(data):
    """
    Create a URL encoded JSON string from a given dict or list.

    @type data: dict
    @param data: the data structure
    @return URL encoded string
    """
    return urllib.parse.quote(json.dumps(data, separators=(',', ':')))


def getPluginBaseURL():
    """
    Return the base plugin:// URL for this plugin (may be different on different platforms)

    @return the URL string
    """

    return 'plugin://' + ADDON_ID


def assembleListURL(module=None, submodule=None, **kwargs):
    """
    Assemble a plugin:// url with a list command.

    @type module: str
    @param module: the name of the module to list
    @type submodule: str
    @param submodule: the name of the sub module to list (requires module to be set)
    @param kwargs: additional parameters
    @return the URL
    """

    url = getPluginBaseURL() + '/?cmd=list'

    if module is None:
        return url

    url += '&module=' + urllib.parse.quote(module)
    if submodule is not None:
        url += '&submodule=' + urllib.parse.quote(submodule)

    for p in kwargs:
        url += '&' + urllib.parse.quote(p) + '=' + urllib.parse.quote(str(kwargs[p]))

    return url


def assemblePlayURL(url, name='', art=None, streamInfo=None):
    """
    Assemble a plugin:// URL with a play command for a given URL.

    @type url: str
    @param url: the real URL of the media file
    @type name: str
    @param name: a nice human-readable name
    @type art: dict
    @param art: dictionary as expected by xbmcgui.ListItem.setArt()
    @type streamInfo: dict
    @param streamInfo: streamInfo for the media file
    @type streamInfo: dict
    @param: streamInfo: technical info about the stream (such as the duration or resolution)
    """
    if streamInfo is None:
        streamInfo = {}
    if art is None:
        art = {}

    if '#' == url or '' == url:
        return '#'

    return getPluginBaseURL() + '/?cmd=play&url=' + urllib.parse.quote(url) + \
          '&name=' + urllib.parse.quote(name) + \
          '&art=' + dictUrlEncode(art) + \
          '&streaminfo=' + dictUrlEncode(streamInfo)


def playVideoStream(url, name='', art=None, streamInfo=None):
    """
    Create media player and open given stream URL.

    @type url: str
    @param url: the URL of the media file
    @type name: str
    @param name: a nice human-readable name
    @type art: dict
    @param art: dictionary as expected by xbmcgui.ListItem.setArt()
    @type streamInfo: dict
    @param streamInfo: metaData for the media file
    @type streamInfo: dict
    @param: streamInfo: technical info about the stream (such as the duration or resolution)
    """
    listitem = xbmcgui.ListItem(name)
    listitem.setInfo('video', streamInfo)
    if art is not None:
        listitem.setArt(art)

    playlist = xbmc.PlayList(1)
    playlist.clear()
    playlist.add(url, listitem)

    xbmc.Player().play(playlist)
    playlist.clear()

