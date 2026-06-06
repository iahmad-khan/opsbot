{{- define "opsbot.fullname" -}}
{{- printf "%s" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "opsbot.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{ include "opsbot.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "opsbot.selectorLabels" -}}
app.kubernetes.io/name: opsbot
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
