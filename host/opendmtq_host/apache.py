"""Apache's configuration, written at every start from the settings and the repository's own."""

import os
import sys

from opendmtq_cli import env
from .paths import APP, LOGS, RUN, WINDOWS
from .settings import admin_port, listen_port
from .folders import make_folders, slashes

# Apache's modules the site uses (site.conf), by the name each is loaded as and its file.
MODULES = [
    ("authz_core_module", "mod_authz_core.so"), ("authz_host_module", "mod_authz_host.so"),
    ("mime_module", "mod_mime.so"), ("log_config_module", "mod_log_config.so"), ("setenvif_module", "mod_setenvif.so"),
    ("env_module", "mod_env.so"), ("alias_module", "mod_alias.so"), ("dir_module", "mod_dir.so"),
    ("rewrite_module", "mod_rewrite.so"), ("headers_module", "mod_headers.so"), ("expires_module", "mod_expires.so"),
    ("filter_module", "mod_filter.so"), ("deflate_module", "mod_deflate.so"), ("proxy_module", "mod_proxy.so"),
    ("proxy_http_module", "mod_proxy_http.so"),
]

# On Linux and macOS: one process per connection (PHP's module is not thread-safe there), and the user switch module.
POSIX_MODULES = [("mpm_prefork_module", "mod_mpm_prefork.so"), ("unixd_module", "mod_unixd.so")]


def quoted(text):
    """A value in double quotes for Apache's configuration (a backslash or a quote inside is escaped)."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def load_module(name, folder, file):
    """A module, loaded unless this Apache has it built in (Debian's has unixd, others have more)."""
    return f"<IfModule !{name}>\n    LoadModule {name} {quoted(slashes(os.path.join(folder, file)))}\n</IfModule>"


# How much of each log is kept: this many files of this size, written in a circle.
LOG_FILES = 3
LOG_BYTES = 10 * 1024 * 1024


def log_pipe(found, name):
    """A piped log: LOG_FILES files of LOG_BYTES at most, data/state/logs/<name> and <name>.1, .2. On Windows through
    logpipe.py on pythonw.exe: rotatelogs.exe, a console program, opens an empty window of its own there when Apache's
    worker starts it. Elsewhere through rotatelogs."""
    target = slashes(os.path.join(LOGS, name))
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if WINDOWS and os.path.isfile(pythonw):
        script = slashes(os.path.join(os.path.dirname(os.path.abspath(__file__)), "logpipe.py"))
        # Each path in quotes inside the quoted directive: any of them may hold spaces.
        return quoted(f'|"{slashes(pythonw)}" -I "{script}" "{target}" {LOG_FILES} {LOG_BYTES}')
    program = slashes(found["rotatelogs"])
    return quoted(f'|"{program}" -n {LOG_FILES} "{target}" {LOG_BYTES // (1024 * 1024)}M')


def httpd_conf(values, found):
    """The whole of Apache's configuration for this server: the modules, the logs, one door on the public port with
    the site (server/apache/site.conf), and the admin pages behind it."""
    port = listen_port(values)
    bind = values.get("BIND_ADDRESS") or "0.0.0.0"
    host, _ = env.split(values["PUBLIC_HOST"])
    mods = found["modules"]
    lines = [
        "# Written by host/opendmtq_host at every start; changes here are lost.",
        "# The site itself is server/apache/site.conf.",
        f"ServerRoot {quoted(slashes(RUN))}",
        f"PidFile {quoted(slashes(os.path.join(RUN, 'httpd.pid')))}",
        f"Listen {bind}:{port}",
        f"ServerName {host}",
        # Not the Apache, OS or PHP version in headers and error pages.
        "ServerTokens Prod",
        "ServerSignature Off",
    ]
    if not WINDOWS:
        # Its lock files and sockets in the run folder, not in the system's (which needs root).
        lines.append(f"DefaultRuntimeDir {quoted(slashes(RUN))}")
        lines += [load_module(name, mods, f) for name, f in POSIX_MODULES]
        # Some processes ready, as many as a home server needs.
        lines += ["StartServers 4", "MinSpareServers 4", "MaxSpareServers 16", "MaxRequestWorkers 64"]
    else:
        # Windows: one process with threads; PHP's module is the thread-safe build.
        lines += ["ThreadsPerChild 64"]
    lines += [load_module(name, mods, f) for name, f in MODULES]
    lines.append(f"LoadModule php_module {quoted(slashes(found['phpmod']))}")
    if found.get("phpini"):
        # The bundle's php.ini (its extensions: SQLite, mbstring, opcache).
        lines.append(f"PHPIniDir {quoted(slashes(found['phpini']))}")
    tz = values.get("TZ") or ""
    lines += [
        f"TypesConfig {quoted(slashes(found['mime']))}",
        "DirectoryIndex index.php index.html",
        # PHP runs every .php file the site lets through.
        '<FilesMatch "\\.php$">',
        "    SetHandler application/x-httpd-php",
        "</FilesMatch>",
        # PHP as in the image (server/php/opendmtq.ini): warnings never in a reply (the game reads JSON), to the log.
        "php_admin_flag display_errors off",
        "php_admin_flag display_startup_errors off",
        "php_admin_flag log_errors on",
        "php_admin_value output_buffering 4096",
        "php_admin_flag expose_php off",
        # The in-game ranking's day follows the zone in TZ, when set; UTC otherwise.
        f"php_admin_value date.timezone {quoted(tz if tz else 'UTC')}",
        # A kept connection holds a process until this runs out (opendmtq.conf says why it is short).
        "KeepAliveTimeout 2",
        # Nothing outside the folders the site names is ever served.
        "<Directory />",
        "    AllowOverride None",
        "    Require all denied",
        "</Directory>",
        # The logs: the request log the admin pages read, and Apache's and PHP's own messages.
        'LogFormat "%h %l %u %t \\"%r\\" %>s %b \\"%{Referer}i\\" \\"%{User-Agent}i\\"" combined',
        f"ErrorLog {log_pipe(found, 'server.log')}",
        # Health checks and the live view's constant polls stay out of the request log (opendmtq.conf says why).
        'SetEnvIf Request_URI "^/opendmtq/health\\.php$" nolog',
        'SetEnvIf Request_URI "^/(?:live/|opendmtq/live-media\\.php)" nolog',
        "SetEnvIfExpr \"%{REQUEST_URI} == '/opendmtq/live.php' && %{QUERY_STRING} =~ /^list=/\" nolog",
        "SetEnvIfExpr \"%{QUERY_STRING} == 'live=1' && %{REQUEST_URI} =~ m#^/opendmtq/(index\\.php)?$#\" nolog",
        f"CustomLog {log_pipe(found, 'access.log')} combined env=!nolog",
        f"<VirtualHost *:{port}>",
        f"    ServerName http://{values['PUBLIC_HOST']}",
        f"    Include {quoted(slashes(os.path.join(APP, 'server', 'apache', 'site.conf')))}",
        f"    Include {quoted(slashes(os.path.join(RUN, 'admin.conf')))}",
        "</VirtualHost>",
    ]
    return "\n".join(lines) + "\n"


def admin_conf(values):
    """The admin pages on the public port (/opendmtq/admin): passed to the admin service on a local network address,
    refused on an internet one, where this install has no HTTPS to keep the password safe."""
    port = admin_port(values)
    target = f"http://127.0.0.1:{port}"
    if values.get("ADMIN_ON_PUBLIC_PORT", "yes") == "yes" and env.is_lan_only(values["PUBLIC_HOST"]):
        return "\n".join([
            # The visitor's real address for the sign-in throttle; whatever the visitor sent is replaced.
            'RequestHeader set X-Real-IP "expr=%{REMOTE_ADDR}"',
            # Sign-in forms are tiny; uploads (songs, backups) go to their own pages.
            '<LocationMatch "^/(opendmtq/)?admin/login">',
            "    LimitRequestBody 8192",
            "</LocationMatch>",
            f'ProxyPass "/opendmtq/admin" "{target}/opendmtq/admin" timeout=900',
            f'ProxyPassReverse "/opendmtq/admin" "{target}/opendmtq/admin"',
            # Their address until 2026-11, which the admin service sends on to the new one.
            f'ProxyPass "/admin" "{target}/admin"',
            f'ProxyPassReverse "/admin" "{target}/admin"',
        ]) + "\n"
    return "\n".join([
        '<LocationMatch "^/(opendmtq/)?admin(/|$)">',
        "    Require all denied",
        f'    ErrorDocument 403 "The admin pages are on the server PC only: open '
        f'http://localhost:{port}/opendmtq/admin/ there."',
        "</LocationMatch>",
    ]) + "\n"


def php_ini(values, found):
    """The Windows bundle's php.ini: its extensions, and the settings the image has (server/php/opendmtq.ini)."""
    tz = values.get("TZ") or "UTC"
    return "\n".join([
        "; Written by host/opendmtq_host at every start; changes here are lost.",
        f'extension_dir = "{slashes(found["phpext"])}"',
        # The database and the multibyte text functions (Korean names).
        "extension = sqlite3",
        "extension = mbstring",
    ] + ([] if values.get("PHP_OPCACHE", "off") != "on" else [
        # Compiled scripts kept between requests, with PHP_OPCACHE=on in .env. Off by default: its memory shared between
        # Apache's processes is known to fail on some Windows setups, and a home server does not miss it.
        "zend_extension = opcache",
    ]) + [
        # Never a warning in a reply (the game reads JSON): to the log instead.
        "display_errors = Off",
        "display_startup_errors = Off",
        "log_errors = On",
        # The same buffering as the image, so a header still works after a stray warning.
        "output_buffering = 4096",
        f'date.timezone = "{tz}"',
        "expose_php = Off",
        "opcache.enable = 1",
        "opcache.memory_consumption = 64",
        "opcache.max_accelerated_files = 4000",
        # The code does not change while the server runs.
        "opcache.validate_timestamps = 0",
    ]) + "\n"


def write_configs(values, found):
    """Apache's configuration and the admin pages' part of it in the run folder, and on Windows PHP's php.ini."""
    make_folders()
    if WINDOWS and found.get("phpext"):
        with open(os.path.join(RUN, "php.ini"), "w", encoding="utf-8") as f:
            f.write(php_ini(values, found))
    with open(os.path.join(RUN, "admin.conf"), "w", encoding="utf-8") as f:
        f.write(admin_conf(values))
    conf = os.path.join(RUN, "httpd.conf")
    with open(conf, "w", encoding="utf-8") as f:
        f.write(httpd_conf(values, found))
    return conf
