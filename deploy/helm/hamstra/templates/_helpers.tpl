{{- define "hamstra.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "hamstra.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "hamstra.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "hamstra.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "hamstra.selectorLabels" -}}
app.kubernetes.io/name: {{ include "hamstra.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "hamstra.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "hamstra.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "hamstra.secretName" -}}
{{- default (include "hamstra.fullname" .) .Values.secrets.existingSecret }}
{{- end }}

{{- define "hamstra.configClaim" -}}
{{- default (printf "%s-config" (include "hamstra.fullname" .)) .Values.persistence.config.existingClaim }}
{{- end }}

{{- define "hamstra.secureCookies" -}}
{{- if kindIs "invalid" .Values.config.secureCookies -}}
{{- if .Values.ingress.tls }}true{{ else }}false{{ end -}}
{{- else -}}
{{- .Values.config.secureCookies | toString -}}
{{- end -}}
{{- end }}
