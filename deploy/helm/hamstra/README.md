# Hamstra Helm chart

Installs [Hamstra](https://github.com/coddan/hamstra) on Kubernetes (1.25+).

Hamstra uses one SQLite database and one torrent session, so it runs as **one replica with a Recreate update strategy**.
The chart does not offer a replica count on purpose.

## Install

```bash
helm install hamstra ./deploy/helm/hamstra -n media --create-namespace \
  --set secrets.tmdbApiKey=YOUR_TMDB_READ_TOKEN \
  --set media.nfs.server=192.168.1.5 --set media.nfs.path=/volume1/media
```

Then open the UI (see the notes helm prints) and **create the admin account first**.

## The two volumes
| Volume | Purpose | Values |
|---|---|---|
| **config** (PVC, kept on uninstall) | database, backups, torrent state | `persistence.config.*` |
| **media** (mounted once at `/media`) | library **and** downloads, so they share a filesystem | `media.existingClaim`, `media.nfs.*`, `media.hostPath` |

For an SMB share use a CSI driver (e.g. csi-driver-smb) to make a PVC and pass it as `media.existingClaim`.
SMB/NFS shares usually do not support hardlinks; imports then fall back to size-checked copies.
Folder locations inside the volume are set with `config.tvRoot`, `config.moviesKidsRoot`, `config.moviesAdultsRoot`, `config.musicRoot`, `config.downloadsDir`.
The files must be writable by the user the pod runs as: use `podSecurityContext` (`runAsUser`, `runAsGroup`, `fsGroup`) to match your share.

## Common setups
Ingress with TLS (also switches on secure cookies):

```yaml
ingress:
  enabled: true
  className: nginx
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: 10m   # .torrent uploads
  hosts:
    - host: hamstra.example.com
      paths: [{path: /, pathType: Prefix}]
  tls:
    - secretName: hamstra-tls
      hosts: [hamstra.example.com]
```

Expose the BitTorrent port (better speeds when seeding):

```yaml
torrent:
  service:
    enabled: true
    type: NodePort
    nodePort: 30881        # forward this port on your router to a node
```

Keep secrets outside the values: create a Secret with the keys `tmdbApiKey` (and optionally `apiKey`) and set `secrets.existingSecret`.

## Values
See [`values.yaml`](values.yaml); every option is commented.

## VPN sidecar (experimental, untested)
`vpn.enabled=true` adds a [gluetun](https://github.com/qdm12/gluetun) container to the pod. All containers of a pod share one network namespace,
so the whole pod, including the web UI, uses the VPN. Needs `NET_ADMIN` and access to `/dev/net/tun`.
After enabling, set Settings → Downloads & seeding → VPN interface to `tun0` (or `wg0`) to get the kill switch.

## Upgrade / uninstall
`helm upgrade hamstra ./deploy/helm/hamstra -n media -f my-values.yaml` — database migrations run automatically at start.
`helm uninstall` keeps the config PVC (`helm.sh/resource-policy: keep`); delete it yourself if you really want to remove the data.
