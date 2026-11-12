# OpenDMTQ server: the game server, the players' site and the live view (PHP + SQLite) behind one Apache.
# SQLite3 is built into the image's PHP.
FROM php:8.3-apache

# The stock site is replaced by ours. opcache: every script is compiled once per start.
# deflate/expires/headers: compressed JSON and cache hints for the song files.
# remoteip: the visitor addresses the edge proxy passes on (PROXY protocol). HTTPS ends in the edge.
# status: off. Nothing reads /server-status, and its "Require local" trusts whatever address
# mod_remoteip settles on (a forwarded 127.0.0.1 once opened it on the Helm chart's door).
RUN docker-php-ext-enable opcache \
    && a2enmod deflate expires headers auth_basic authn_file authz_user rewrite proxy proxy_http \
        remoteip \
    && a2dismod -q status \
    && a2dissite 000-default \
    # The site's own logs replace the per-host access log (it would grow in the scratch tree).
    && a2disconf other-vhosts-access-log \
    # Unprivileged ports only: the container never needs root or NET_BIND_SERVICE. The site adds
    # 8081 and 8443.
    && echo "Listen 8080" > /etc/apache2/ports.conf \
    && echo "ServerName opendmtq" > /etc/apache2/conf-enabled/servername.conf \
    # Do not announce the Apache, OS or PHP version in headers and error pages.
    && sed -ri 's/^ServerTokens .*/ServerTokens Prod/; s/^ServerSignature .*/ServerSignature Off/' /etc/apache2/conf-available/security.conf \
    # One writable tree for everything the server creates at runtime, usable by any uid. /data is where the
    # database and the players' files go: compose and Kubernetes mount a volume there, and an image started without
    # one still runs (its data then lives and dies with the container).
    && mkdir -p /var/opendmtq /data && chmod 1777 /var/opendmtq /data

# Apache's pid, lock and log files go to the writable tree, so the root filesystem can be read-only.
ENV APACHE_RUN_DIR=/var/opendmtq/run \
    APACHE_LOCK_DIR=/var/opendmtq/run \
    APACHE_PID_FILE=/var/opendmtq/run/apache2.pid \
    APACHE_LOG_DIR=/var/opendmtq/run
# Where everything is (site.conf and the PHP code read these): the code, the imported content (read only), the
# admin's overlay (read only here), the database's folder, the HTTPS certificates. The built apps are at /srv/apk, the
# code's own default, which the Helm chart moves with OPENDMTQ_APK_OUT (a value set here would win over the chart's).
ENV OPENDMTQ_APP=/opt/opendmtq \
    OPENDMTQ_CONTENT=/srv/content \
    OPENDMTQ_CUSTOM=/srv/custom \
    OPENDMTQ_STATE=/data \
    OPENDMTQ_DB=/data/dmtq.db3 \
    OPENDMTQ_HTTPS=/srv/https

# Error display off (warnings would corrupt JSON replies), output buffering on.
COPY php/opendmtq.ini /usr/local/etc/php/conf.d/opendmtq.ini
# The single site: game hosts merged by path, the portal, and the deny list.
COPY apache/opendmtq.conf /etc/apache2/sites-available/opendmtq.conf
COPY apache/site.conf /etc/apache2/opendmtq/site.conf
RUN a2ensite opendmtq

# The players' site (rankings, songs, the app download, the live view's pages), the game server and the start-up
# script. The game server's public folder is the site's document root: empty, every path has its own door.
COPY portal /opt/opendmtq/portal
COPY game /opt/opendmtq/game
COPY entrypoint.sh /opt/opendmtq/
RUN chmod 0755 /opt/opendmtq/entrypoint.sh && mkdir -p /opt/opendmtq/game/public

# The release this image is (release.yml passes it), for the version the site shows when nothing else names one: a plain
# docker run. The command line and the Helm chart pass their own (OPENDMTQ_VERSION), which wins. Empty for an image built
# here. Last, so that a new number rebuilds no layer above.
ARG OPENDMTQ_VERSION=
ENV OPENDMTQ_VERSION=${OPENDMTQ_VERSION}

# Runs as www-data by default; compose and Kubernetes may pick another uid, which also works.
USER www-data
EXPOSE 8080

# Healthy once the portal answers (it reads the database and the content).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD php -r 'exit(@file_get_contents("http://127.0.0.1:8080/opendmtq/health.php") === false ? 1 : 0);'

ENTRYPOINT ["/opt/opendmtq/entrypoint.sh"]
CMD ["apache2-foreground"]
