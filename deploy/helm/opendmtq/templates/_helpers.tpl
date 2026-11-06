{{/* Base name for every object. */}}
{{- define "opendmtq.fullname" -}}
{{- if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 50 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 50 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{/* Labels on every object; pass (dict "ctx" $ "component" "api"). */}}
{{- define "opendmtq.labels" -}}
app.kubernetes.io/name: {{ .ctx.Chart.Name }}
app.kubernetes.io/instance: {{ .ctx.Release.Name }}
app.kubernetes.io/version: {{ .ctx.Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .ctx.Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .ctx.Chart.Name .ctx.Chart.Version }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/* Selector labels; pass (dict "ctx" $ "component" "api"). */}}
{{- define "opendmtq.selector" -}}
app.kubernetes.io/name: {{ .ctx.Chart.Name }}
app.kubernetes.io/instance: {{ .ctx.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/* image reference; pass (dict "img" .Values.image.server "ctx" $). */}}
{{- define "opendmtq.image" -}}
{{- printf "%s:%s" .img.repository (default .ctx.Chart.AppVersion .img.tag) -}}
{{- end -}}

{{/* The game-files volume (claim or host path). */}}
{{- define "opendmtq.dataVolume" -}}
- name: data
{{- if .Values.data.existingClaim }}
  persistentVolumeClaim:
    claimName: {{ .Values.data.existingClaim }}
{{- else if .Values.data.hostPath }}
  hostPath:
    path: {{ .Values.data.hostPath }}
    type: Directory
{{- else }}
{{- fail "set data.existingClaim or data.hostPath (where the content and apk folders live)" }}
{{- end }}
{{- end -}}

{{/* Locked-down container: no root, no capabilities, read-only root filesystem. */}}
{{- define "opendmtq.containerSecurity" -}}
securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities: {drop: [ALL]}
{{- end -}}

{{/* S3 endpoint: the bundled store when enabled, otherwise the configured one. */}}
{{- define "opendmtq.s3Endpoint" -}}
{{- if .Values.objectStore.enabled -}}
{{- printf "http://%s-s3:8333" (include "opendmtq.fullname" .) -}}
{{- else -}}
{{- required "litestream.s3.endpoint is required when objectStore.enabled is false" .Values.litestream.s3.endpoint -}}
{{- end -}}
{{- end -}}

{{/* Secret holding the S3 credentials. */}}
{{- define "opendmtq.s3Secret" -}}
{{- default (printf "%s-s3" (include "opendmtq.fullname" .)) .Values.litestream.s3.existingSecret -}}
{{- end -}}

{{/* Whether the server passes the admin pages (/opendmtq/admin) on through the router: "yes" or "no". admin.onPublicPort
     when set; otherwise "yes" with router.tls (HTTPS) or for a private IPv4 publicHost (plain HTTP
     on the local network) and "no" for anything else, where the server would refuse them in clear
     anyway (reach the pages with kubectl port-forward instead, see NOTES.txt). */}}
{{- define "opendmtq.adminOnPublicPort" -}}
{{- $v := .Values.admin.onPublicPort -}}
{{- /* An unquoted yes or no in a values file arrives as a boolean (YAML 1.1). */ -}}
{{- $set := ternary (ternary "yes" "no" (eq (toString $v) "true")) (toString (default "" $v)) (kindIs "bool" $v) -}}
{{- if or (eq $set "yes") (eq $set "no") -}}
{{- $set -}}
{{- else if $set -}}
{{- fail (printf "admin.onPublicPort %q must be yes, no or empty (automatic)" $set) -}}
{{- else if .Values.router.tls.secretName -}}
yes
{{- else if regexMatch "^(10\\.|192\\.168\\.|172\\.(1[6-9]|2[0-9]|3[01])\\.|127\\.)" (include "opendmtq.publicHost" .) -}}
yes
{{- else -}}
no
{{- end -}}
{{- end -}}

{{/* live.default as the server reads it, "on" or "off". An unquoted on or off in a values file arrives as a boolean
     (YAML 1.1), which the server would take for off whatever it says. */}}
{{- define "opendmtq.liveDefault" -}}
{{- $v := .Values.live.default -}}
{{- if kindIs "bool" $v -}}
{{- ternary "on" "off" $v -}}
{{- else -}}
{{- default "off" $v -}}
{{- end -}}
{{- end -}}

{{/* publicHost, validated: an IPv4 address or a host name, with :port when it is not 80, as the app patcher takes it. */}}
{{- define "opendmtq.publicHost" -}}
{{- $h := required "publicHost is required: the address phones use to reach the router (IPv4 or host name, optionally :port)" .Values.publicHost -}}
{{- if not (regexMatch "^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:[0-9]{1,5})?$" $h) -}}
{{- fail (printf "publicHost %q must be an IPv4 address or host name, optionally with :port" $h) -}}
{{- end -}}
{{- $h -}}
{{- end -}}
