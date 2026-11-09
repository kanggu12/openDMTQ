# The Windows build machine of the PC client: the Wine image of the player's tests (arm32/wine.Dockerfile, WineHQ's Wine
# at a fixed version) with a Windows Python that has Tk, PyInstaller and the launcher's two libraries. The Python is
# python-build-standalone's Windows build (an archive, no installer to run under Wine). Built by
# client/packaging/windows/build.sh, which passes the archive in and checks its hash first.
FROM opendmtq-arm32-wine
ENV WINEPREFIX=/wine WINEDEBUG=-all WINEDLLOVERRIDES="mscoree,mshtml="
COPY pbs.tar.gz /tmp/pbs.tar.gz
# The Windows Python lives at C:\python inside the Wine prefix.
RUN wineboot -i >/dev/null 2>&1; wineserver -w; \
    mkdir -p /wine/drive_c && tar -xzf /tmp/pbs.tar.gz -C /wine/drive_c && rm /tmp/pbs.tar.gz
# Exact versions, so every build bundles the same code.
RUN wine 'C:\python\python.exe' -m pip install --no-warn-script-location --disable-pip-version-check \
        pyinstaller==6.16.0 pillow==11.3.0 velopack==1.2.161 >/tmp/pip.log 2>&1 \
    || (cat /tmp/pip.log; exit 1); wineserver -w
