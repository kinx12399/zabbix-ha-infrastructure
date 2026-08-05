sudo nano /usr/lib/zabbix/externalscripts/check_dns.sh

#!/bin/bash
DNS_SERVER=$1
DOMAIN=$2

# dig 실행 및 결과 추출
OUTPUT=$(dig @${DNS_SERVER} ${DOMAIN} A +time=10 +tries=1)
TIME_MS=$(echo "$OUTPUT" | grep "Query time:" | awk '{print $4}')
IP=$(echo "$OUTPUT" | grep -A 1 "ANSWER SECTION:" | tail -n 1 | awk '{print $5}')

if [ -n "$TIME_MS" ]; then
  TIME_SEC=$(awk "BEGIN {print $TIME_MS/1000}")
  echo "{\"response\":\"success\",\"time\":$TIME_SEC,\"ip\":\"$IP\"}"
else
  echo "{\"response\":\"failed\",\"time\":0,\"ip\":\"\"}"
fi

sudo chmod +x /usr/lib/zabbix/externalscripts/check_dns.sh
sudo chown zabbix:zabbix /usr/lib/zabbix/externalscripts/check_dns.sh