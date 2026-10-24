#!/usr/bin/env bash
# Verifies the Android app's protocol code against a running hub. Needs: kotlinc, a JDK, org.json (json.jar), and a hub.
#   HUB=http://127.0.0.1:8000 ADMIN_KEY=hma_... JSON_JAR=/path/to/json.jar KOTLINC=/path/to/kotlinc/bin/kotlinc ./run.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$HERE/../../himaya-mobile/app/src"
OUT="$(mktemp -d)"
"${KOTLINC:-kotlinc}" -nowarn -cp "$JSON_JAR" -d "$OUT/classes" \
  "$APP/main/java/com/himaya/agent/DnsPacket.kt" "$APP/main/java/com/himaya/agent/Http.kt" "$APP/main/java/com/himaya/agent/HubClient.kt" \
  "$APP/test/java/com/himaya/agent/JvmTransport.kt" "$HERE/HubContractCheck.kt"
OUT="$OUT/dns" java -cp "$OUT/classes:$JSON_JAR:$(dirname "$(dirname "${KOTLINC:-kotlinc}")")/lib/kotlin-stdlib.jar" HubContractCheckKt
echo "DNS packets written to $OUT/dns (validate with tools/android_contract_check/verify_dns.py)"
