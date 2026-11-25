# Massengeschmack Kodi Add-on

[`plugin.video.massengeschmack`](plugin.video.massengeschmack/) für **Kodi 19+** (Python 3).

| | |
|--|--|
| **Quelle** | https://github.com/Channel80/massengeschmack-kodi |
| **Version** | siehe `addon.xml` |
| **Lizenz** | GPLv3 — `plugin.video.massengeschmack/LICENSE.txt` |

Ursprüngliches Add-on: Janek Bevendorff ([phoerious/massengeschmack-xbmc](https://github.com/phoerious/massengeschmack-xbmc)). Weiterentwicklung ab 3.0.0: Channel80.

**Hinweis:** Kein offizielles Massengeschmack-Angebot. Zugang erfordert ein gültiges Massengeschmack-Abo.

## Installation

**Empfohlen (LibreELEC / Kodi):**

1. Release-ZIP von [GitHub Releases](https://github.com/Channel80/massengeschmack-kodi/releases) nach `/storage/Download/` kopieren.
2. Kodi: Add-ons → Paket-Symbol → **Aus ZIP installieren** → lokale ZIP wählen.

ZIP **nicht direkt** vom SMB-Netzlaufwerk installieren (`zip://` über SMB ist oft fehleranfällig).

**Alternative:** Ordner `plugin.video.massengeschmack` nach `/storage/.kodi/addons/plugin.video.massengeschmack` kopieren (alte Version vorher entfernen), Kodi neu starten.

Details: `INSTALL-Massengeschmack-3.1.27.txt` (LibreELEC, weiterhin gültig).

## Build (Windows)

```powershell
.\build-addon-zip.ps1
```

Erzeugt `plugin.video.massengeschmack-<version>.zip` mit Kodi-konformen Pfaden (Schrägstriche). Das Skript kopiert die ZIP optional auf den konfigurierten UNC-Share (siehe Skript).

## Offizielles Kodi-Repository

Dieses Repo ist die **Entwicklungsquelle**. Veröffentlichung über das offizielle Kodi-Repo erfolgt per Pull Request an [xbmc/repo-plugins](https://github.com/xbmc/repo-plugins) (ein Commit pro Version, Format `[plugin.video.massengeschmack] <version>`).

Richtlinien: [Submitting Add-ons](https://kodi.wiki/view/Submitting_Add-ons), [Add-on rules](https://kodi.wiki/view/Add-on_rules).

## Projektstruktur

```
plugin.video.massengeschmack/   # Add-on-Quellen (Root für Kodi-Repo-PR)
build-addon-zip.ps1             # ZIP-Build
```