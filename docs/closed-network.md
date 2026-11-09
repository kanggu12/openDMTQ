# Without internet

A server and phones on a network with no way out: a lab, an office LAN, a router with nothing behind it. OpenDMTQ needs the
internet only to get its programs onto the server. After that nothing it does asks for the internet: the setup, the app's
build, the server and the game all stay on your network.

| Way of running | On a closed network | What you carry in |
|---|---|---|
| Windows bundle | Works as it is | The zip and your game files |
| Docker Compose | Works | A release's images and source, and your game files. Docker has to be on the computer already |
| Kubernetes | Works | A release's images in your registry, the chart, and your game files |
| Linux host install (Debian, Ubuntu) | Works | The system's packages, three programs (apktool, uber-apk-signer, 7-Zip), the source, the runtime for newer phones, and your game files |
| macOS host install | **Not possible**: Homebrew has no way to install from files carried in | Use Docker Compose instead |

Below, `1.2.3` stands for the release you want. Everything is fetched on a computer with internet, carried over on a disk,
and put in place on the closed one. [An update](#updates) is the same trip with the new release.

## Windows

Nothing to prepare. Unpack the zip, double-click `OpenDMTQ.exe`, and go through the setup in the browser, as the
[quick start](../README.md#quick-start) says. The runtime for newer phones is in the zip.

## Docker Compose

On the computer with internet:

```sh
V=1.2.3
docker pull --platform linux/amd64 ghcr.io/kanggu12/opendmtq-server:$V
docker pull --platform linux/amd64 ghcr.io/kanggu12/opendmtq-tools:$V
docker pull --platform linux/amd64 nginxinc/nginx-unprivileged:1.27.5-alpine
docker save ghcr.io/kanggu12/opendmtq-server:$V ghcr.io/kanggu12/opendmtq-tools:$V \
  nginxinc/nginx-unprivileged:1.27.5-alpine | gzip > opendmtq-images.tar.gz
curl -fsSL -o opendmtq-source.tar.gz https://github.com/kanggu12/openDMTQ/archive/refs/tags/v$V.tar.gz
```

That is for a server with an x86-64 processor. For an ARM one, pull the server image and nginx-unprivileged with
`--platform linux/arm64`. The tools image exists for x86-64 only and runs emulated there: Docker Desktop does that by
itself, and Docker Engine on Linux needs `tonistiigi/binfmt` carried in too, and
`docker run --privileged --rm tonistiigi/binfmt --install amd64` once. An ARM server has not been tried on a closed
network.

On the closed computer, which needs [Docker](https://docs.docker.com/get-docker/) 23 or newer with the Compose plugin, and
Python 3.9 or newer:

```sh
docker load -i opendmtq-images.tar.gz
tar -xzf opendmtq-source.tar.gz
cd openDMTQ-1.2.3
printf 'OPENDMTQ_SERVER_IMAGE=ghcr.io/kanggu12/opendmtq-server:1.2.3\nOPENDMTQ_TOOLS_IMAGE=ghcr.io/kanggu12/opendmtq-tools:1.2.3\n' > .env
./opendmtq setup --from <folder with your game files> --songs
```

Those two lines in `.env` tell `./opendmtq` to run these images instead of building its own, which would need the internet.
The tools image holds the runtime for newer phones.

## Kubernetes

Five images go into your registry. The last is only for the chart's own object store: leave it out when the cluster has
S3-compatible storage of its own. The tools image exists for x86-64 only, so the builder job and the admin pages need such a node.

```sh
V=1.2.3
for image in ghcr.io/kanggu12/opendmtq-server:$V ghcr.io/kanggu12/opendmtq-tools:$V \
    nginxinc/nginx-unprivileged:1.27.5-alpine litestream/litestream:0.3.13 chrislusf/seaweedfs:3.97; do
  docker pull --platform linux/amd64 "$image"
  docker tag "$image" "registry.example.internal/${image##*/}"
  docker push "registry.example.internal/${image##*/}"
done
helm pull oci://ghcr.io/kanggu12/charts/opendmtq --version $V
```

A values file, `closed-network.yaml` here, says where they are now:

```yaml
image:
  server: {repository: registry.example.internal/opendmtq-server}
  tools: {repository: registry.example.internal/opendmtq-tools}
  router: {repository: registry.example.internal/nginx-unprivileged}
  litestream: {repository: registry.example.internal/litestream}
objectStore:
  image: {repository: registry.example.internal/seaweedfs}
```

Then install as [Kubernetes](kubernetes.md#install-on-a-cluster) says, from the file `helm pull` left and with these values:
`helm install opendmtq opendmtq-1.2.3.tgz -n opendmtq -f closed-network.yaml ...`. The volume holds `content/` and `apk/base/`
as usual. The builder job takes the runtime for newer phones from its image. A registry that asks for a password needs a pull
secret on the namespace's default service account:
`kubectl -n opendmtq patch serviceaccount default -p '{"imagePullSecrets": [{"name": "<secret>"}]}'`.

Without a registry, the images can go straight onto every node instead, and the file of values is not needed: `docker save -o
opendmtq-images.tar <the five images>` on the computer with internet, `ctr -n k8s.io images import opendmtq-images.tar` on each
node.

## A Linux host install

Everything goes into one folder, `kit`. First the system's packages, fetched on a clean copy of the same system and version as
the server. In a container, for Ubuntu 24.04 (for an ARM server, add `--platform linux/arm64` after `docker run`):

```sh
mkdir -p kit/debs
docker run --rm -v "$PWD/kit/debs:/debs" ubuntu:24.04 sh -c 'apt-get update && \
  apt-get install -y --download-only --no-install-recommends -o Dir::Cache::archives=/debs \
    apache2 libapache2-mod-php php-cli php-sqlite3 php-mbstring default-jre-headless python3 python3-venv \
    python3-flask python3-waitress python3-lz4 python3-pil python3-qrcode ca-certificates curl xz-utils && \
  rm -rf /debs/partial /debs/lock && chmod -R a+rX /debs'
```

If the closed network has a mirror of your distribution's packages, the system finds them itself: leave out `debs`. Use
a mirror too if the server refuses these packages because they depend on versions other than the ones it has.

And these, into `kit` under these names:

| File | From |
|---|---|
| `apktool.jar` | `https://github.com/iBotPeaches/Apktool/releases/download/v2.12.1/apktool_2.12.1.jar` |
| `uber-apk-signer.jar` | `https://github.com/patrickfav/uber-apk-signer/releases/download/v1.3.0/uber-apk-signer-1.3.0.jar` |
| `7zip.tar.xz` | `https://www.7-zip.org/a/7z2501-linux-x64.tar.xz` (`7z2501-linux-arm64.tar.xz` on an ARM server) |
| `opendmtq-arm32-runtime.zip` | `https://github.com/kanggu12/openDMTQ/releases/download/v1.2.3/opendmtq-arm32-runtime.zip` |
| `OpenDMTQ-Setup.exe` | `https://github.com/kanggu12/openDMTQ/releases/download/v1.2.3/OpenDMTQ-Setup.exe` |
| `OpenDMTQ-Setup.exe.version` | `https://github.com/kanggu12/openDMTQ/releases/download/v1.2.3/OpenDMTQ-Setup.exe.version` |
| `opendmtq-source.tar.gz` | `https://github.com/kanggu12/openDMTQ/archive/refs/tags/v1.2.3.tar.gz` |

On the closed computer, as the user who will run the server, beside the `kit` folder:

```sh
tar -xzf kit/opendmtq-source.tar.gz
cd openDMTQ-1.2.3
host/install.sh --from ../kit
./opendmtq setup
```

`host/install.sh` checks each of the three programs against the hash of the copy that was tested. The one command of the quick
start needs the internet, so it is not for here.

## macOS

The host install takes Apache, PHP, Java and Python from Homebrew and the Python libraries from PyPI, and neither installs from
files carried in. This cannot be done on a closed network: run Docker Compose on the Mac instead.

## Updates

Your settings and data are in the folder of the first install, so the new source goes over it. Fetch the new release as above,
and carry it in. Below, `<first install>` is that folder: `openDMTQ-` and the version you first installed.

- **Windows:** close the server's window, and unpack the new zip where you unpacked the first.
- **Docker Compose:** load the new images and unpack the source over the first install's folder. Then, in that folder's `.env`,
  put the new version in the two image lines, and start it:

  ```sh
  docker load -i opendmtq-images.tar.gz
  tar -xzf opendmtq-source.tar.gz --strip-components=1 -C <first install>
  cd <first install>
  ./opendmtq up
  ```

- **Kubernetes:** the new images, then `helm upgrade` from the new chart's file.
- **A Linux host install:** with the new `kit` beside the first install's folder:

  ```sh
  <first install>/opendmtq stop
  tar -xzf kit/opendmtq-source.tar.gz --strip-components=1 -C <first install>
  cd <first install>
  host/install.sh --from ../kit
  ./opendmtq start
  ```

## The phones

Phones reach the server by its address, so they only have to be on its network. Three things are different without internet:

- **Android may say the Wi-Fi has no internet.** Choose to stay connected. If the game then cannot reach the server,
  turn mobile data off: with it on, Android may keep sending everything there.
- **Give the server a fixed address.** The app has it built in, and a closed network often has nothing that keeps it the
  same. Set it on the computer or in the router's settings before the setup. A computer on several networks has to be
  told which one the phones are on: on Windows and on a host install in the setup's address step, with Docker Compose
  with `./opendmtq setup --host <address>`.
- **Play Protect may say it cannot check the app.** Install anyway, as with an app from anywhere but a store.

## What does not work

| What | Why | Instead |
| :--- | :--- | :--- |
| The one command, `git pull`, `./opendmtq` building its own images | They fetch from the internet | The steps above, with each new release |
| `./opendmtq runtime --build` | It fetches Android's tools | The release's `opendmtq-arm32-runtime.zip` in `data/apk`, or a release's tools image |
| The PC client's installer on a host install without the kit's copy | The builder fetches it from the latest release, and after a fetch that failed it waits a day to try again | The release's `OpenDMTQ-Setup.exe` and `OpenDMTQ-Setup.exe.version` in `data/apk` ([the PC client](windows-player.md)). They stay there: once they are a week old the builder looks for a newer one, at most once a day, and keeps them when there is none to be had |
| Playing from outside, `./opendmtq expose` | There is no outside | |

If the runtime for newer phones did not make it, the app is still built and runs on phones that run 32-bit apps. The setup says
why, and with Docker Compose `./opendmtq doctor` too. Put `opendmtq-arm32-runtime.zip` in `data/apk`, and build the app again: the
server takes the file from there.

## How this was tried

`tests/closed/run.sh` goes through the steps above on a network with no way out, for Docker Compose, a host install and
Kubernetes, and `CLOSED=1 tests/windows/wine.sh` for the Windows bundle under Wine. Each first checks that the internet really
is out of reach. `tests/closed/game.sh` tries the game the same way, on an emulator that can reach the server and nothing else:
install, first start, a song downloaded and played to its result, the shop. What Android says on a real phone about a Wi-Fi
without internet differs from phone to phone, and has not been gone through on each.
