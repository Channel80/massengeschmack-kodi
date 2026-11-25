# Massengeschmack Kodi Add-on

Video-Plugin `plugin.video.massengeschmack` für Kodi 19+ (Python 3).

Ursprüngliches Add-on von Janek Bevendorff ([phoerious/massengeschmack-xbmc](https://github.com/phoerious/massengeschmack-xbmc)); Weiterentwicklung ab 3.0.0 durch Channel80. Lizenz: GPLv3 (`plugin.video.massengeschmack/LICENSE.txt`).

Kein offizielles Massengeschmack-Produkt. Zugang zu Sendungen erfordert ein Massengeschmack-Abo.

## Build (Windows)

```powershell
.\build-addon-zip.ps1
```

Erzeugt `plugin.video.massengeschmack-<version>.zip` mit Kodi-konformen Pfaden. Optional Kopie auf einen Netzwerk-Share (siehe Skript).

## Ordner

| Pfad | Inhalt |
|------|--------|
| `plugin.video.massengeschmack/` | Add-on-Quellen |
| `build-addon-zip.ps1` | ZIP-Build |