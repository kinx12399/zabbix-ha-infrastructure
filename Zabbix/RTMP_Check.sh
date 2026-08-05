# Zabbix Server 서버 접속
cd /usr/lib/zabbix/externalscripts
sudo nano check_rtmp.sh

#!/bin/bash
STREAM_URL=$1
TEMP_FILE="/tmp/rtmp_check_$RANDOM.flv"

# --- [1차 시도] ---
/usr/bin/rtmpdump -v -r "$STREAM_URL" -B 1 -o "$TEMP_FILE" > /dev/null 2>&1

# --- [1차 실패 시 2초 대기 후 2차 재시도] ---
if [ ! -s "$TEMP_FILE" ]; then
    sleep 2
    /usr/bin/rtmpdump -v -r "$STREAM_URL" -B 1 -o "$TEMP_FILE" > /dev/null 2>&1
fi

# --- [최종 결과 출력] ---
# 1차 또는 2차 중 한 번이라도 성공해서 파일이 생성되었으면 1, 둘 다 실패면 0
if [ -s "$TEMP_FILE" ]; then
    echo 1
else
    echo 0
fi

# 임시 파일 삭제
rm -f "$TEMP_FILE"


sudo chmod +x check_rtmp.sh
sudo chown zabbix:zabbix check_rtmp.sh

sudo apt update
sudo apt install -y rtmpdump

which rtmpdump

sudo nano /etc/zabbix/zabbix_proxy.conf
ExternalScripts=/usr/lib/zabbix/externalscripts 
sudo systemctl restart zabbix-proxy

sudo -u zabbix /usr/lib/zabbix/externalscripts/check_rtmp.sh "rtmp://121.78.33.150/monitoring/mp4:sample_check.mp4"