# Zabbix 7.0 HA 통합 모니터링 인프라

![Zabbix](https://img.shields.io/badge/Zabbix-7.0%20LTS-red?style=flat&logo=zabbix)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue?style=flat&logo=postgresql)
![TimescaleDB](https://img.shields.io/badge/TimescaleDB-2.x-fdb515?style=flat&logo=timescale)
![Patroni](https://img.shields.io/badge/Patroni-HA-green?style=flat)
![HAProxy](https://img.shields.io/badge/HAProxy-Primary%20Router-blue?style=flat)

Zabbix 6.0과 Nagios로 분리되어 있던 모니터링 환경을 **Zabbix 7.0 LTS 기반 단일 플랫폼**으로 통합하고, Server·Database·Proxy 계층을 이중화한 프로젝트입니다. PostgreSQL 16과 TimescaleDB로 시계열 데이터 처리 기반을 개선했으며, Patroni·etcd·HAProxy를 조합해 쓰기 가능한 Primary DB로 자동 연결되도록 구성했습니다.

> 이 저장소의 주소·계정·비밀번호는 `<MASKED_...>` 형태로 비식별화되어 있습니다. 배포 전에 환경별 값으로 교체하고 비밀정보는 Git이 아닌 Vault, systemd credential, Ansible Vault 등의 별도 저장소에서 관리하세요.

## 목차

- [프로젝트 개요](#프로젝트-개요)
- [아키텍처](#아키텍처)
- [주요 성과](#주요-성과)
- [저장소 구성](#저장소-구성)
- [구축 및 포팅 매뉴얼](#구축-및-포팅-매뉴얼)
- [Zabbix 및 Nagios 마이그레이션](#zabbix-및-nagios-마이그레이션)
- [부하 테스트](#부하-테스트)
- [Failover 검증](#failover-검증)
- [트러블슈팅](#트러블슈팅)
- [운영·보안 체크리스트](#운영보안-체크리스트)

## 프로젝트 개요

| 구분 | 내용 |
| --- | --- |
| 프로젝트명 | Zabbix 7.0 기반 통합 모니터링 시스템 구축 및 Nagios 마이그레이션 |
| 수행 기간 | 2026.07.15 ~ 2026.08.05 |
| 기존 환경 | Zabbix 6.0 LTS, MySQL 8.0, Zabbix Agent, Nagios, 단일 VM 중심 구성 |
| 개선 환경 | Zabbix 7.0 LTS, PostgreSQL 16, TimescaleDB, Agent 2, Patroni, etcd, HAProxy, Proxy Group |
| 수행 범위 | 아키텍처 설계, 구축·업그레이드, Nagios 항목 분석·이관, 외부검사 개발, 부하 및 Failover 테스트, 문서화 |
| 핵심 목표 | 플랫폼 단일화, 계층별 SPOF 축소, 장애 대응 자동화, 시계열 데이터 확장성 확보 |

기존 환경에서는 동일한 호스트와 검사 항목을 Zabbix와 Nagios에서 중복 관리하고, 알림·임계치·장애 대응 기준도 플랫폼별로 운영해야 했습니다. 본 프로젝트에서는 호스트명과 IP를 함께 대조해 대상을 정규화하고, HTTP·SSL·ICMP는 Zabbix 기본 기능으로, DNS·RTMP는 External Check로 이관했습니다.

## 아키텍처

![전체 아키텍처](AD1.png)

![HA 및 장애조치 흐름](AD2.png)

```text
Monitoring targets
    │ Agent 2 / SNMP / ICMP / HTTP / External Check
    ▼
Zabbix Proxy Group
    ├─ Proxy 1 (active mode, SQLite)
    └─ Proxy 2 (active mode, SQLite)
    │
    ▼
Zabbix Server Native HA
    ├─ Server 1 (Active 또는 Standby)
    └─ Server 2 (Active 또는 Standby)
    │ 127.0.0.1:5432
    ▼
Local HAProxy on each server
    │ Patroni REST API /primary health check
    ▼
PostgreSQL 16 + TimescaleDB
    ├─ DB1 (Primary 또는 Replica)
    └─ DB2 (Primary 또는 Replica)
       └─ Patroni + 3-node etcd quorum
```

### 노드 역할

| 계층 | 호스트명 | 주요 역할 |
| --- | --- | --- |
| Web / App 1 | `vm-zabbix-server1` | Nginx, PHP 8.3, Zabbix Server, Local HAProxy, etcd member 3 |
| Web / App 2 | `vm-zabbix-server2` | Nginx, PHP 8.3, Zabbix Server, Local HAProxy |
| Database 1 | `vm-zabbix-db1` | PostgreSQL 16, TimescaleDB, Patroni, etcd member 1 |
| Database 2 | `vm-zabbix-db2` | PostgreSQL 16, TimescaleDB, Patroni, etcd member 2 |
| Proxy 1 | `vm-zabbix-proxy1` | Zabbix Proxy active mode, SQLite, Proxy Group member |
| Proxy 2 | `vm-zabbix-proxy2` | Zabbix Proxy active mode, SQLite, Proxy Group member |

### 계층별 고가용성

- **Zabbix Server:** 두 서버가 같은 DB를 사용하며 한 노드만 Active로 동작합니다. Active 노드의 heartbeat가 끊기면 Standby가 자동 승격됩니다.
- **Database:** Patroni가 etcd의 분산 상태를 기준으로 Primary를 선출하고 PostgreSQL Streaming Replication을 관리합니다.
- **DB 연결:** 각 Zabbix Server의 Local HAProxy가 Patroni `/primary` API에서 HTTP 200을 반환하는 노드에만 DB 연결을 전달합니다.
- **Proxy:** Zabbix 7.0 Proxy Group이 수집 부하를 분산하며 장애 Proxy의 호스트를 생존 Proxy로 재할당합니다.
- **Frontend:** `$ZBX_SERVER`를 고정하지 않아 DB의 HA 노드 정보를 바탕으로 현재 Active Zabbix Server를 찾도록 구성합니다.

## 주요 성과

| 검증 항목 | 결과 |
| --- | ---: |
| Nagios 전수 비교 대상 | 259 hosts |
| 부하 테스트 대상 | 2,000 dummy hosts |
| Host당 Item / Trigger | 25 / 25 |
| 전체 Item | 약 50,000 |
| 수집 주기 | 10초 |
| 목표 수집량 | 약 5,000 NVPS |
| DB Failover 연결 복구 | 18.62초 |
| Zabbix Server Active 승격 | 2.55초 |
| Zabbix Server 전체 서비스 복구 | 6.61초 |
| Proxy 장애 감지 | 63.35초 |
| Proxy Host 이관 완료 | 70.77초 |

데이터 손실 수치는 테스트 로그와 History 저장 결과에서 **관찰되지 않은 범위**를 의미합니다. 비정상 전원 차단, 네트워크 분할, 동기 복제 설정 등 모든 장애 조건에서의 절대적인 RPO 0을 보장하는 표현은 아닙니다.

## 저장소 구성

```text
zabbix-ha-infrastructure/
├─ HAproxy/
│  └─ haproxy.cfg                 # Patroni Primary 기반 DB 라우팅
├─ Nginx/
│  └─ zabbix.conf                 # Zabbix Web frontend
├─ patroni/
│  ├─ DB1_patroni.yml             # DB1 Patroni 설정
│  └─ DB2_patroni.yml             # DB2 Patroni 설정
├─ Zabbix/
│  ├─ zabbix_server.conf          # Zabbix Server HA 설정
│  ├─ zabbix_proxy.conf           # Active Proxy 설정
│  ├─ zabbix_agent2.conf          # Agent 2 설정
│  ├─ zabbix.conf.php             # Web frontend DB/HA 설정
│  ├─ DNS_Check.sh                # DNS 검사 예제와 설치 메모
│  └─ RTMP_Check.sh               # RTMP 검사 예제와 설치 메모
├─ Load_Test/
│  ├─ create_hosts.py             # Dummy host 생성
│  ├─ add_triggers.py             # Trigger 생성
│  ├─ load_generator.py           # zabbix_sender 부하 생성
│  └─ delete_hosts.py             # Dummy host 정리
├─ docs/                          # 발표·보고 자료
├─ AD1.png
├─ AD2.png
└─ README.md
```

> `DNS_Check.sh`와 `RTMP_Check.sh`에는 현재 설치 절차와 실행 코드가 함께 들어 있습니다. 운영 서버의 ExternalScripts 디렉터리에 그대로 복사하지 말고, `#!/bin/bash`부터 검사 로직만 별도 `check_dns.sh`, `check_rtmp.sh`로 분리한 뒤 배포하세요.

## 구축 및 포팅 매뉴얼

이 절차는 Ubuntu 계열 Linux와 systemd를 기준으로 합니다. 패키지 저장소 등록 방식과 PHP socket 경로는 OS 및 Zabbix 패키지 버전에 맞게 조정해야 합니다.

### 0. 배포 전 준비

먼저 다음 값을 환경별로 확정합니다.

```text
<DB1_IP>       <DB2_IP>
<SERVER1_IP>   <SERVER2_IP>
<PROXY1_IP>    <PROXY2_IP>
<SERVICE_CIDR>
<DB_PASSWORD>  <REPLICATION_PASSWORD>  <MONITOR_PASSWORD>
```

필수 포트는 최소 범위의 방화벽 정책으로 허용합니다.

| Port | Source → Destination | 용도 |
| ---: | --- | --- |
| 80/443 | User → Web nodes | Zabbix UI |
| 10050 | Server/Proxy → Agent | Passive check |
| 10051 | Proxy/Agent → Zabbix Server | Active proxy/check 및 trapper |
| 5432 | Zabbix Server → Local HAProxy, DB peer | PostgreSQL |
| 8008 | HAProxy/DB admin network → Patroni | Patroni REST health check |
| 2379 | Patroni nodes → etcd members | etcd client |
| 2380 | etcd members ↔ etcd members | etcd peer |

배포 전 공통 확인:

```bash
timedatectl status
hostnamectl
getent hosts vm-zabbix-db1 vm-zabbix-db2 vm-zabbix-server1 vm-zabbix-server2
```

모든 노드의 시간 동기화와 정방향 이름 해석이 정상이어야 합니다.

### 0-1. Zabbix 7.0 공식 패키지 설치

현재 저장소의 Nginx·PHP 경로와 구축 환경에 맞춰 **Ubuntu 24.04 LTS / Zabbix 7.0 LTS / PostgreSQL / Nginx** 조합을 기준으로 합니다. Ubuntu 기본 저장소의 Zabbix 패키지는 버전이 오래되거나 필요한 기능이 빠질 수 있으므로 [Zabbix 공식 저장소](https://repo.zabbix.com/zabbix/7.0/ubuntu/)를 사용합니다.

먼저 각 노드의 OS와 CPU architecture를 확인합니다.

```bash
. /etc/os-release
printf 'OS=%s VERSION=%s ARCH=%s\n' "$ID" "$VERSION_ID" "$(dpkg --print-architecture)"
```

아래 저장소 패키지는 Ubuntu 24.04 `amd64` 기준입니다. Ubuntu 20.04/22.04 또는 `arm64`를 사용한다면 파일명을 임의로 바꾸지 말고 [Zabbix 다운로드 페이지](https://www.zabbix.com/download?zabbix=7.0)에서 OS와 architecture에 맞는 7.0 LTS 저장소를 선택합니다.

#### 모든 Zabbix 구성 노드에 공식 저장소 등록

Server, Proxy, DB와 Agent 2를 설치할 모든 모니터링 대상에서 실행합니다.

```bash
sudo apt update
sudo apt install -y wget ca-certificates gnupg

wget -O /tmp/zabbix-release.deb \
  https://repo.zabbix.com/zabbix/7.0/ubuntu/pool/main/z/zabbix-release/zabbix-release_latest_7.0+ubuntu24.04_all.deb
sudo dpkg -i /tmp/zabbix-release.deb
sudo apt update
rm -f /tmp/zabbix-release.deb

apt-cache policy zabbix-server-pgsql zabbix-proxy-sqlite3 zabbix-agent2
```

`apt-cache policy`의 Candidate가 `repo.zabbix.com/zabbix/7.0`에서 제공되는지 확인한 뒤 역할별 패키지를 설치합니다.

#### Server1·Server2: Zabbix Server, Web frontend, Agent 2

두 Zabbix Server 노드에 동일하게 설치합니다.

```bash
sudo apt install -y \
  zabbix-server-pgsql \
  zabbix-frontend-php \
  php8.3-pgsql \
  zabbix-nginx-conf \
  zabbix-sql-scripts \
  zabbix-agent2 \
  zabbix-get \
  zabbix-sender \
  fping

zabbix_server --version
zabbix_agent2 --version
nginx -v
php -v
```

패키지 설치 직후에는 아직 DB와 HA node 값이 설정되지 않았으므로 Zabbix Server를 시작하지 않습니다. 자동으로 시작되었다면 설정 배포 단계까지 중지합니다.

```bash
sudo systemctl stop zabbix-server
```

각 패키지의 역할은 다음과 같습니다.

| 패키지 | 역할 |
| --- | --- |
| `zabbix-server-pgsql` | PostgreSQL backend용 Zabbix Server |
| `zabbix-frontend-php` | Zabbix Web frontend PHP 파일 |
| `php8.3-pgsql` | PHP에서 PostgreSQL에 접속하기 위한 확장 |
| `zabbix-nginx-conf` | Nginx·PHP-FPM용 기본 설정과 socket 구성 |
| `zabbix-sql-scripts` | Server schema와 TimescaleDB schema |
| `zabbix-agent2` | Server 노드 자체 모니터링 |
| `zabbix-get`, `zabbix-sender` | Agent 통신 점검과 trapper 부하 테스트 도구 |

#### Proxy1·Proxy2: SQLite 기반 Zabbix Proxy와 Agent 2

두 Proxy 노드에 동일하게 설치합니다.

```bash
sudo apt install -y \
  zabbix-proxy-sqlite3 \
  zabbix-sql-scripts \
  zabbix-agent2 \
  zabbix-get \
  zabbix-sender \
  fping \
  dnsutils \
  rtmpdump

zabbix_proxy --version
zabbix_agent2 --version
sudo systemctl stop zabbix-proxy
```

`zabbix-proxy-sqlite3`는 각 Proxy가 사용하는 로컬 SQLite backend 패키지입니다. Server DB와 Proxy DB를 공유하지 않습니다. `dnsutils`와 `rtmpdump`는 이 프로젝트의 DNS·RTMP External Check에 필요합니다.

#### DB1·DB2: Agent 2와 PostgreSQL plugin

DB 노드 자체의 OS와 PostgreSQL 상태를 수집하기 위해 설치합니다.

```bash
sudo apt install -y \
  zabbix-agent2 \
  zabbix-agent2-plugin-postgresql \
  zabbix-get

zabbix_agent2 --version
dpkg -l | grep -E '^ii\s+zabbix-(agent2|agent2-plugin-postgresql)'
```

#### 나머지 Linux 모니터링 대상: Agent 2

```bash
sudo apt install -y zabbix-agent2
sudo systemctl stop zabbix-agent2
zabbix_agent2 --version
```

Agent는 [7. Agent 2 연결](#7-zabbix-agent-2-연결)의 `Server`, `ServerActive`, `Hostname`을 설정한 후 시작합니다.

#### 설치 결과 확인

Server 노드에서 다음 패키지가 확인되어야 합니다.

```bash
dpkg -l | grep -E '^ii\s+(zabbix|php8.3-pgsql)'
ls -l /usr/share/zabbix-sql-scripts/postgresql/server.sql.gz
ls -l /usr/share/zabbix-sql-scripts/postgresql/timescaledb/schema.sql
```

서비스는 아직 모두 실행될 필요가 없습니다. 이후 단계에서 DB와 설정 파일을 먼저 준비하고 다음 순서로 시작합니다.

```text
etcd → Patroni/PostgreSQL → HAProxy → Zabbix Server/Web → Proxy → Agent 2
```

### 1. etcd 3-node quorum 구성

DB1, DB2, Server1에 etcd를 설치합니다.

```bash
sudo apt update
sudo apt install -y etcd-server etcd-client
```

각 노드의 `/etc/default/etcd`에 고유한 `ETCD_NAME`, peer/client listen 주소를 지정하고, 세 노드 모두 동일한 초기 멤버 목록과 cluster token을 사용합니다.

```ini
ETCD_INITIAL_CLUSTER="db1=http://<DB1_IP>:2380,db2=http://<DB2_IP>:2380,server1=http://<SERVER1_IP>:2380"
ETCD_INITIAL_CLUSTER_STATE="new"
ETCD_INITIAL_CLUSTER_TOKEN="etcd-zabbix-cluster"
```

노드별 예시는 다음 원칙을 따릅니다.

```ini
ETCD_NAME="db1"
ETCD_DATA_DIR="/var/lib/etcd/db1.etcd"
ETCD_LISTEN_PEER_URLS="http://<DB1_IP>:2380"
ETCD_LISTEN_CLIENT_URLS="http://<DB1_IP>:2379,http://127.0.0.1:2379"
ETCD_INITIAL_ADVERTISE_PEER_URLS="http://<DB1_IP>:2380"
ETCD_ADVERTISE_CLIENT_URLS="http://<DB1_IP>:2379"
```

```bash
sudo systemctl enable --now etcd
etcdctl member list
etcdctl endpoint health --cluster
```

기존 클러스터에 노드를 다시 붙이는 경우 `ETCD_INITIAL_CLUSTER_STATE="existing"` 여부와 기존 member 상태를 먼저 확인해야 합니다. 운영 중인 etcd data directory를 임의로 삭제하지 마세요.

### 2. PostgreSQL 16, TimescaleDB, Patroni 구성

DB1과 DB2에 OS 버전에 맞는 PostgreSQL·TimescaleDB 공식 저장소를 등록한 후 필요한 패키지를 설치합니다.

```bash
sudo apt update
sudo apt install -y postgresql-16 postgresql-client-16 \
  timescaledb-2-postgresql-16 patroni python3-psycopg2
sudo systemctl disable --now postgresql
```

Patroni가 PostgreSQL 프로세스를 직접 관리하므로 기본 `postgresql.service`는 중지합니다. 저장소의 설정 파일을 각 DB 노드에 복사하고 마스킹 값을 교체합니다.

```bash
sudo install -o postgres -g postgres -m 0640 patroni/DB1_patroni.yml /etc/patroni/patroni.yml
# DB2에서는 DB2_patroni.yml 사용
sudo ln -sfn /etc/patroni/patroni.yml /etc/patroni/config.yml
sudo chown -R postgres:postgres /etc/patroni /var/lib/postgresql
```

설정 핵심값:

- 두 노드의 `scope`, `namespace`, etcd hosts는 동일해야 합니다.
- `name`, `restapi.listen`, `connect_address`는 노드별로 고유해야 합니다.
- `shared_preload_libraries: timescaledb`와 `data-checksums`를 유지합니다.
- `pg_hba`의 `<MASKED_SUBNET>`은 필요한 서비스망으로 최소화합니다.
- `restapi`와 etcd에 TLS 또는 인증을 적용하지 않는 경우 방화벽으로 관리망 접근만 허용합니다.

> **데이터 삭제 주의:** Patroni 최초 bootstrap을 위해 기존 PostgreSQL data directory를 비워야 할 수 있습니다. `rm -rf /var/lib/postgresql/16/main`은 해당 경로가 새 구축 대상이며 백업과 복구 절차가 확인된 경우에만 실행하세요. 운영 DB 또는 경로가 불명확한 환경에서는 실행하면 안 됩니다.

DB1을 먼저 시작하고 Leader 선출을 확인한 뒤 DB2를 시작합니다.

```bash
sudo systemctl enable --now patroni
sudo patronictl -c /etc/patroni/patroni.yml list
curl -fsS http://<DB1_IP>:8008/primary
curl -fsS http://<DB2_IP>:8008/replica
```

`bootstrap.dcs`와 `bootstrap.pg_hba`는 최초 cluster bootstrap에 사용됩니다. 이미 생성된 클러스터의 동적 설정은 파일만 수정하지 말고 `patronictl edit-config`로 변경하세요.

### 3. Zabbix DB와 TimescaleDB schema 생성

Primary DB에서 계정과 DB를 생성합니다. 예시 비밀번호를 그대로 사용하지 마세요.

```sql
CREATE USER zabbix WITH PASSWORD '<DB_PASSWORD>';
CREATE DATABASE zabbix OWNER zabbix;
\c zabbix
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE USER zbx_monitor WITH PASSWORD '<MONITOR_PASSWORD>';
GRANT pg_read_all_stats TO zbx_monitor;
```

Zabbix Server 패키지가 설치된 노드에서 schema를 주입합니다.

```bash
zcat /usr/share/zabbix-sql-scripts/postgresql/server.sql.gz \
  | PGPASSWORD='<DB_PASSWORD>' psql -h <DB1_IP> -U zabbix -d zabbix

cat /usr/share/zabbix-sql-scripts/postgresql/timescaledb/schema.sql \
  | PGPASSWORD='<DB_PASSWORD>' psql -h <DB1_IP> -U zabbix -d zabbix
```

비밀번호에 `!`, `$`, 공백 등의 문자가 있으면 shell history expansion과 quoting에 주의합니다. 가능하면 `.pgpass`, password file, secret manager를 사용하세요.

### 4. Local HAProxy로 Primary DB 라우팅

Server1과 Server2에 HAProxy를 설치하고 저장소 설정을 배포합니다.

```bash
sudo apt install -y haproxy
sudo install -o root -g root -m 0644 HAproxy/haproxy.cfg /etc/haproxy/haproxy.cfg
sudoedit /etc/haproxy/haproxy.cfg   # DB1/DB2 주소 교체
sudo haproxy -c -f /etc/haproxy/haproxy.cfg
sudo systemctl enable --now haproxy
```

HAProxy는 `127.0.0.1:5432`에서 대기하고, Patroni의 `/primary`가 HTTP 200인 DB에만 연결을 전달합니다.

```bash
PGPASSWORD='<DB_PASSWORD>' psql -h 127.0.0.1 -U zabbix -d zabbix \
  -c 'SELECT inet_server_addr(), pg_is_in_recovery();'
```

`pg_is_in_recovery()` 결과가 `f`여야 쓰기 가능한 Primary DB로 연결된 것입니다.

### 5. Zabbix Server Native HA와 Web frontend 구성

Server1과 Server2에 Zabbix 7.0 Server, SQL scripts, Nginx, PHP-FPM을 설치한 뒤 설정을 배포합니다.

```bash
sudo install -o root -g zabbix -m 0640 Zabbix/zabbix_server.conf /etc/zabbix/zabbix_server.conf
sudo install -o root -g root -m 0644 Nginx/zabbix.conf /etc/nginx/conf.d/zabbix.conf
sudo install -o root -g www-data -m 0640 Zabbix/zabbix.conf.php /etc/zabbix/web/zabbix.conf.php
```

각 서버에서 반드시 다르게 설정할 값:

```ini
# Server1
HANodeName=zabbix-server1
NodeAddress=<SERVER1_IP>:10051

# Server2
HANodeName=zabbix-server2
NodeAddress=<SERVER2_IP>:10051
```

공통 DB 연결은 Local HAProxy를 사용합니다.

```ini
DBHost=127.0.0.1
DBPort=5432
DBName=zabbix
DBUser=zabbix
DBPassword=<DB_PASSWORD>
```

Frontend의 `$ZBX_SERVER`와 `$ZBX_SERVER_PORT`는 지정하지 않습니다. 그래야 DB의 HA 노드 정보로 현재 Active Server를 자동 탐색할 수 있습니다. 저장소의 `$DB['PORT']='0'`은 PostgreSQL 기본 포트를 의미하며, 명시하려면 `'5432'`로 바꿀 수 있습니다.

```bash
sudo nginx -t
sudo php -l /etc/zabbix/web/zabbix.conf.php
sudo zabbix_server -T -c /etc/zabbix/zabbix_server.conf
sudo systemctl restart haproxy php8.3-fpm nginx zabbix-server
sudo zabbix_server -R ha_status
```

두 서버가 동일한 DB를 사용하되 서로 다른 `HANodeName`과 `NodeAddress`를 갖는지 확인합니다.

### 6. Zabbix Proxy Group 구성

Proxy1과 Proxy2에 Zabbix Proxy(SQLite)를 설치하고 설정을 배포합니다.

```bash
sudo install -o root -g zabbix -m 0640 Zabbix/zabbix_proxy.conf /etc/zabbix/zabbix_proxy.conf
sudoedit /etc/zabbix/zabbix_proxy.conf
sudo zabbix_proxy -T -c /etc/zabbix/zabbix_proxy.conf
sudo systemctl enable --now zabbix-proxy
```

Active Proxy가 동일 Zabbix Server HA cluster를 바라볼 때 서버 주소는 **세미콜론**으로 구분합니다.

```ini
ProxyMode=0
Server=<SERVER1_IP>;<SERVER2_IP>
Hostname=zabbix-proxy1  # Proxy2에서는 zabbix-proxy2
DBName=/var/lib/zabbix/zabbix_proxy.db
ProxyBufferMode=hybrid
ProxyMemoryBufferSize=16M
```

Web UI에서 다음 순서로 등록합니다.

1. `Administration → Proxy groups → Create proxy group`
2. Group name을 `ixcloud-proxy-group`으로 지정
3. Failover period `1m`, Minimum online proxies `1` 설정
4. Proxy1과 Proxy2를 각각 생성하고 동일 그룹에 할당

2,000 hosts / 5,000 NVPS 테스트에서는 Proxy configuration cache가 부족해질 수 있었습니다. 환경 규모에 맞춰 별도 include 파일로 조정합니다.

```ini
# /etc/zabbix/zabbix_proxy.d/10-capacity.conf
CacheSize=256M
```

메모리 값은 테스트 결과와 호스트·아이템 수를 기준으로 산정하고 변경 후 프로세스 busy, queue, cache 사용률을 다시 확인하세요.

### 7. Zabbix Agent 2 연결

Agent 설정에서 Passive check 허용 대상은 쉼표로, 동일 HA cluster 또는 Proxy Group의 Active check 대상은 세미콜론으로 구분합니다.

```ini
Server=<PROXY1_IP>,<PROXY2_IP>
ServerActive=<PROXY1_IP>;<PROXY2_IP>
Hostname=<EXACT_ZABBIX_HOST_NAME>
```

```bash
sudo zabbix_agent2 -T -c /etc/zabbix/zabbix_agent2.conf
sudo systemctl enable --now zabbix-agent2
sudo journalctl -u zabbix-agent2 -n 100 --no-pager
```

`Hostname`은 Web UI에 등록한 Host name과 대소문자까지 일치해야 합니다. Agent가 Server에 직접 연결되는 구조라면 Proxy IP 대신 Server1/Server2 주소를 같은 구분자 규칙으로 지정합니다.

### 8. DNS·RTMP External Check 포팅

#### DNS Check

`dig`로 지정 DNS Server의 A record를 질의하고 JSON을 반환합니다.

```json
{"response":"success","time":0.023,"ip":"192.0.2.10"}
```

권장 Item 설계:

- Master Item: `check_dns.sh["{$DNS.SERVER}","{$DNS.DOMAIN}"]`, Text
- Dependent Item: `$.response`, Text
- Dependent Item: `$.time`, Numeric(float), unit `s`
- Dependent Item: `$.ip`, Text

운영 적용 시 `dig` 종료 코드, `SERVFAIL`, `NXDOMAIN`, 복수 A record를 구분하고 인자를 검증해야 합니다.

#### RTMP Check

`rtmpdump`로 짧은 미디어 구간을 실제 수신하고, 수신 파일이 존재하면 `1`, 실패하면 `0`을 반환합니다. 1차 실패 시 재시도하며 Trigger는 최근 2분간 성공 여부로 오탐을 줄입니다.

```text
max(/RTMP Stream Monitoring/check_rtmp.sh["{$RTMP.URL}"],2m)=0
```

운영 스크립트는 다음 조건을 만족해야 합니다.

- `mktemp`로 임시 파일 생성
- `trap`으로 정상·비정상 종료 시 파일 삭제
- `timeout`으로 최대 실행시간 제한
- Zabbix `Timeout`보다 짧은 실행시간 보장
- URL 입력 검증 및 실행 오류 로그 분리

배포 예시:

```bash
sudo install -o zabbix -g zabbix -m 0750 check_dns.sh /usr/lib/zabbix/externalscripts/check_dns.sh
sudo install -o zabbix -g zabbix -m 0750 check_rtmp.sh /usr/lib/zabbix/externalscripts/check_rtmp.sh
sudo -u zabbix /usr/lib/zabbix/externalscripts/check_dns.sh <DNS_SERVER> example.com
sudo -u zabbix /usr/lib/zabbix/externalscripts/check_rtmp.sh '<RTMP_URL>'
```

### 9. 통합 검증

```bash
# etcd
etcdctl endpoint health --cluster

# Patroni/PostgreSQL
sudo patronictl -c /etc/patroni/patroni.yml list
PGPASSWORD='<DB_PASSWORD>' psql -h 127.0.0.1 -U zabbix -d zabbix \
  -c 'SELECT pg_is_in_recovery();'

# Zabbix Server HA
sudo zabbix_server -R ha_status

# 서비스 및 최근 오류
systemctl --no-pager --full status patroni haproxy zabbix-server zabbix-proxy zabbix-agent2
journalctl -p warning..alert --since '-30 min' --no-pager
```

Web UI에서는 다음을 확인합니다.

- `Reports → System information`: Zabbix Server Active/Standby 상태
- `Administration → Proxies`: 두 Proxy의 online 상태와 group 배정
- `Monitoring → Latest data`: Agent, DNS, RTMP 데이터 갱신
- `Monitoring → Queue`: 지연 Item 유무
- DB/Proxy internal item: cache, process busy, NVPS, replication lag

### 10. Rollback 기준

- 신규 환경의 수집·알림이 검증되기 전 기존 Server 데몬을 제거하지 않습니다.
- 병행 운영 중 중복 알림을 방지하도록 한쪽 Action 또는 Media Type을 비활성화합니다.
- 전환 실패 시 Agent의 `Server`와 `ServerActive`를 기존 주소로 복구하고 Agent를 재시작합니다.
- 기존 DB와 VM은 보존 기간 동안 read-only 조회 또는 snapshot 복구 용도로 유지합니다.
- 신규 데이터와 기존 데이터가 동시에 쓰이지 않도록 활성 Server를 명확히 한 뒤 rollback합니다.

## Zabbix 및 Nagios 마이그레이션

### 호스트 정규화

Nagios의 259개 호스트를 다음 순서로 기존 Zabbix 대상과 대조했습니다.

1. Nagios host/service 목록과 Zabbix host 목록 추출
2. Hostname 기준 1차 비교
3. IP 주소 기준 2차 교차검증
4. 서로 다른 이름으로 등록된 동일 대상 매핑
5. 중복 객체 병합 및 누락 대상 신규 등록
6. 기존 임계치·알림 조건을 서비스별로 재검증

### 검사 항목 치환

| Nagios 검사 | Zabbix 구현 |
| --- | --- |
| HTTP 상태·응답시간 | HTTP Agent Item |
| 웹 로그인 흐름 | Web Scenario |
| SSL 인증서 만료 | Agent 2 Certificate Template |
| ICMP Ping | ICMP Ping Template |
| CPU·Memory·Filesystem | Agent 2 OS Template |
| DNS 질의·응답 IP | External Check + Dependent Item |
| RTMP Stream 상태 | `rtmpdump` External Check |

### Import와 Cut-over 순서

```text
Template → Host Group → Host → Item/Trigger 검증 → Action/Media Type
```

1. 기존 Zabbix 설정을 JSON/YAML로 export합니다.
2. 신규 Zabbix 7.0에 의존성 순서대로 import합니다.
3. 일부 대상부터 Agent 2와 Proxy Group으로 전환합니다.
4. 1~4주간 기존 시스템과 병행 운영하며 수집 누락과 알림 오탐을 비교합니다.
5. 안정화 후 기존 Zabbix Server 데몬을 중지합니다.
6. 과거 History/Trend 조회가 필요하면 구형 Web·DB만 제한적으로 유지합니다.
7. 보존 기간 종료 후 snapshot 또는 백업을 확인하고 기존 자원을 폐기합니다.

## 부하 테스트

`Load_Test` 스크립트는 Dummy Trapper 환경에서 처리량과 장애 시 버퍼 동작을 확인하기 위해 사용했습니다.

```text
2,000 hosts × 25 items = 50,000 values
50,000 values ÷ 10 seconds = 5,000 NVPS
```

권장 실행 순서:

1. Dummy Trapper Template과 25개 Item을 준비합니다.
2. `create_hosts.py`로 Dummy Host를 생성합니다.
3. `add_triggers.py`로 25개 Trigger를 추가합니다.
4. 4개 load generator에서 host ID 범위를 500개씩 나눠 실행합니다.
5. Server/Proxy busy, queue, cache, DB write I/O와 slow query를 관찰합니다.
6. 테스트 후 `delete_hosts.py`로 생성한 대상을 정리합니다.

```bash
python3 Load_Test/load_generator.py 1 500
python3 Load_Test/load_generator.py 501 1000
```

> 현재 API 스크립트에는 테스트 당시 API endpoint, group ID, proxy group ID와 토큰 값이 하드코딩되어 있습니다. 실행 전 토큰을 폐기·재발급하고 환경변수로 분리하며, ID는 API 조회 결과를 사용하도록 수정해야 합니다. 테스트는 운영 환경과 분리된 staging에서 수행하세요.

## Failover 검증

### DB Failover

```text
Primary DB 중지
  → Patroni 장애 감지 및 Replica 승격
  → HAProxy /primary 200 확인
  → Zabbix DB session 재연결
```

- 연결 복구: **18.62초**
- Standby 승격 및 HAProxy routing 전환: 성공
- 테스트 범위에서 History 누락: 관찰되지 않음

수동 switchover는 다음 명령으로 수행합니다.

```bash
sudo patronictl -c /etc/patroni/patroni.yml switchover
```

### Zabbix Server Failover

```text
Active Server 중지
  → heartbeat 갱신 중단
  → Standby가 Active로 승격
  → Proxy Group manager 및 수집 프로세스 시작
```

- Active 승격: **2.55초**
- 전체 서비스 복구: **6.61초**
- 정상 종료 시 History·Trend flush: 확인

### Proxy Failover

```text
Proxy 1 중지
  → 1분 failover period 경과
  → Server가 offline 판정
  → Proxy 2로 Host 재할당 및 configuration 전송
```

- Proxy 장애 감지: **63.35초**
- Host 이관 완료: **70.77초**
- Active Check: Agent/Proxy buffer로 보존 가능
- Passive Check: 전환 시간 동안 일부 수집 공백 가능

운영 전에는 정상 service stop뿐 아니라 VM power-off, network partition, etcd quorum 손실, replication lag 상태, Proxy 동시 장애, HAProxy 장애와 Frontend 장애도 별도로 검증해야 합니다.

## 트러블슈팅

### Patroni가 Leader를 선출하지 못함

**증상:** 두 DB 노드가 모두 Replica로 표시되거나 cluster initialize lock 획득에 실패합니다.

**확인:** 기존 PostgreSQL data directory, etcd cluster scope, 파일 권한, `config.yml` 경로와 systemd 조건을 확인합니다.

```bash
sudo journalctl -u patroni -n 200 --no-pager
sudo patronictl -c /etc/patroni/patroni.yml list
etcdctl get /service/zabbix-ha/ --prefix
```

새 구축임이 확인된 경우에만 백업 후 data directory를 초기화하고 DB1 → DB2 순서로 bootstrap합니다.

### HAProxy는 살아 있지만 DB가 read-only임

- 단순 TCP 5432가 아닌 Patroni `/primary`를 health check하는지 확인합니다.
- 두 backend가 동시에 UP인지 확인합니다.
- `SELECT pg_is_in_recovery();`가 `f`인지 확인합니다.
- Patroni REST API의 주소와 HAProxy `check port 8008` 연결을 확인합니다.

### Proxy가 Server HA cluster에 연결되지 않음

- Active Proxy의 `Server` 주소가 세미콜론으로 구분됐는지 확인합니다.
- Proxy `Hostname`과 Web UI 등록 이름이 정확히 일치하는지 확인합니다.
- 10051/TCP와 TLS/PSK 설정이 양쪽에서 동일한지 확인합니다.

### Agent active check가 중복되거나 수신되지 않음

- Passive 허용 목록인 `Server`는 쉼표를 사용합니다.
- 동일 HA cluster 또는 Proxy Group인 `ServerActive`는 세미콜론을 사용합니다.
- 서로 독립된 여러 Server/cluster를 병렬 사용하려는 경우에만 쉼표를 사용합니다.

### Proxy shared memory 부족

2,000 hosts / 5,000 NVPS 테스트에서 기본 configuration cache가 부족해 Proxy가 종료되는 현상이 있었습니다. `CacheSize=256M`으로 상향 후 재발하지 않았지만, 이 값은 고정 권장값이 아니라 해당 테스트 규모의 결과입니다.

```bash
grep -Ei 'cannot allocate|out of memory|cache' /var/log/zabbix/zabbix_proxy.log
```

## 운영·보안 체크리스트

- [ ] 저장소와 Git history에 실제 API token·DB password가 없는가?
- [ ] Zabbix API와 Web UI가 HTTPS를 사용하는가?
- [ ] Server↔Proxy↔Agent 통신에 PSK 또는 certificate TLS를 적용했는가?
- [ ] Patroni REST API 8008과 etcd 2379/2380을 관리망으로 제한했는가?
- [ ] PostgreSQL 5432와 `pg_hba`가 필요한 source CIDR만 허용하는가?
- [ ] `local ... trust` 정책이 운영 보안 기준에 부합하는가?
- [ ] etcd 및 Patroni 설정 백업과 복구 절차가 있는가?
- [ ] PostgreSQL base backup, WAL 보존 및 복구 테스트가 완료됐는가?
- [ ] Zabbix DB schema upgrade 전 snapshot/backup을 확보했는가?
- [ ] External Check 입력 검증, timeout, 임시 파일 정리를 적용했는가?
- [ ] Failover 이후 replication lag, timeline, queue, unsupported item을 확인했는가?
- [ ] 운영 변경과 장애 테스트의 실행 시각·RTO·결과를 로그로 남겼는가?

## 향후 개선

- Ansible로 Agent 2·Proxy·Server 설정 배포 자동화
- Vault 기반 secret 관리와 TLS/PSK 표준화
- Nagios configuration parser 및 Host/Template 등록 API 자동화
- DNS 다중 IP·RCODE 처리, RTMP bitrate/codec/수신 byte 측정
- Proxy별 NVPS와 Host 분배량 기반 capacity tuning
- DB replication lag, WAL 증가율과 etcd quorum 자체 모니터링
- VM power-off, network partition, 동시 다중 장애 chaos test
- Runbook과 장애 알림 자동 연결

---

이 프로젝트의 수치는 특정 테스트 환경에서 수집한 결과이며, 실제 운영 RTO/RPO는 네트워크 지연, 데이터량, 복제 모드, 하드웨어, Zabbix process tuning과 장애 유형에 따라 달라질 수 있습니다.
