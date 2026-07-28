# 🚀 Enterprise Zabbix 7.0 High Availability (HA) Infrastructure

![Zabbix](https://img.shields.io/badge/Zabbix-7.0%20LTS-red?style=flat&logo=zabbix)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue?style=flat&logo=postgresql)
![Patroni](https://img.shields.io/badge/Patroni-HA-green?style=flat)
![Nginx](https://img.shields.io/badge/Nginx-1.24-brightgreen?style=flat&logo=nginx)
![HAProxy](https://img.shields.io/badge/HAProxy-LB-blue?style=flat&logo=haproxy)

> **단일 장애점(SPOF)을 배제한 Zabbix 7.0 모니터링 인프라 구축 프로젝트**

---

## 📌 1. 프로젝트 개요 (Project Overview)

본 프로젝트는 대규모 모니터링 환경에서 특정 서버, DB, 네트워크 장비가 다운되더라도 **24/7 중단 없는 모니터링 및 알림 연동**을 유지하기 위한 **고가용성(HA) 인프라 구축**을 목적으로 진행되었습니다.

- **목표:** 전 계층(Web, App, DB, Proxy)에 대한 자동 장애 조치(Failover) 및 부하 분산 구현
- **주요 구성:** Zabbix 7.0 Native HA + Patroni (PostgreSQL 16 + TimescaleDB) + etcd Quorum + Local HAProxy + Zabbix Proxy Group

---

## 📐 2. 아키텍처 다이어그램 (Architecture Diagram)
![alt text](AD1.png)
![alt text](AD2.png)

---

## 🖥️ 3. 서버 및 네트워크 토폴로지 (Server & Network Topology)

| 계층 (Tier) | 호스트명 (Hostname) | 주요 역할 및 탑재 서비스 |
| :--- | :--- | :--- |
| **Web / App 1** | `vm-zabbix-server1` | Nginx, PHP 8.3, Zabbix Server 1 (Active), Local HAProxy, etcd Node 3 |
| **Web / App 2** | `vm-zabbix-server2` | Nginx, PHP 8.3, Zabbix Server 2 (Standby), Local HAProxy, Zabbix |
| **Database 1** | `vm-zabbix-DB1` | Patroni (Leader), PostgreSQL 16 + TimescaleDB, etcd Node 1 |
| **Database 2** | `vm-zabbix-DB2` | Patroni (Replica), PostgreSQL 16 + TimescaleDB, etcd Node 2 |
| **Proxy 1** | `vm-zabbix-proxy1` | Zabbix Proxy 1 (Active Mode, SQLite3), `ixcloud-proxy-group` 소속 |
| **Proxy 2** | `vm-zabbix-proxy2` | Zabbix Proxy 2 (Active Mode, SQLite3), `ixcloud-proxy-group` 소속 |

---

## 🛠️ 4. 계층별 상세 구현 및 주요 기술 (Technical Architecture)

### 4.1. App 계층 (Zabbix 7.0 Native HA)
- **Active-Standby 런타임 클러스터:** Zabbix 7.0 자체 HA 엔진 기반 구성. DB 내 `ha_node` 테이블 락(Lock) 상태에 따라 Active/Standby 자동 전환.
- **웹 대시보드 자동 Active 추적:** `zabbix.conf.php` 설정으로 웹 프론트엔드가 현재 `active` 상태인 서버로만 런타임 제어 신호를 동적으로 보낼 수 있도록 동작.

### 4.2. Database 계층 (Patroni + PostgreSQL 16 + TimescaleDB)
- **Patroni 기반 이중화 DB:** PostgreSQL 16 실시간 스트리밍 복제 및 자동 장애 승격(Failover) 구성을 위한 Patroni 적용.
- **etcd 3-Node Quorum:** DB 노드 2개(`DB1`, `DB2`)와 App 노드 1개(`Server1`)에 etcd 분산 배치로 Split-Brain 방지.
- **App 서버 내 Local HAProxy 배치:** 
  - App 서버 내부의 Local HAProxy가 Patroni REST API(`8008/primary`) 헬스체크를 수행하여 항상 200 OK를 반환하는 Leader DB(`5432`)로만 커넥션을 점검.
- **TimescaleDB Extention:** 시계열 하이퍼테이블(Hypertable)을 주입하여 대규모 성능 데이터 집계 및 삭제(Housekeeper) 처리 시 발생할 수 있는 DB I/O 병목 완화.

### 4.3. Proxy 계층 (Zabbix 7.0 Proxy Group & Multi-IP HA)
- **Proxy Group 수집 부하 분산:** Zabbix 7.0 신규 기능인 `Proxy Group`을 구성하여, 단일 프록시 장애 시 타겟 호스트 모니터링 작업을 즉시 남은 프록시가 승계.

---

## 📑 5. 세부 검증 보고서: 장애 절체(Failover) 성능 및 데이터 무결성 검증

### 5.1. [시나리오 1] Patroni DB Cluster Switchover 검증

Primary DB(`vm-zabbix-db1`) 절체 시 HAProxy 라우팅 변경 및 Zabbix Server의 DB 자동 재연동 성능을 검증합니다.

```text
[DB 장애 발생] 15:31:23.333
       │
       ▼ (14.67초 간 DB2 승격 및 HAProxy 감지)
[HAProxy DB2 200 OK] 15:31:38.000
       │
       ▼ (3.96초 간 Zabbix Server 대기 및 세션 재확립)
[Zabbix DB 재연동 완료] 15:31:41.955  <--- RTO: 18.62초
```

#### ⏱️ 5.1.1. 복구 시간(RTO) 측정 및 로그 근거

- **RTO 산출 결과:** 18.62초 (Zabbix DB 접속 끊김 감지 ~ DB 접속 자동 재확립)

##### 📝 로그 근거

1. **DB 접속 끊김 및 Down 최초 감지 (`vm-zabbix-server1` 로그)**

> `56170:20260728:153123.333 connection to database 'zabbix' failed: ... FATAL: the database system is shutting down`  
> `56170:20260728:153123.333 database is down: reconnecting in 10 seconds`

- **분석:** `15:31:23.333`에 Zabbix Server가 DB1의 Shutdown 및 연결 중단을 최초 인지함.

2. **HAProxy 헬스체크 기반 Primary 전환 (`vm-zabbix-server2` HAProxy 로그)**

> `Jul 28 15:31:38 vm-zabbix-server2 haproxy[827]: Server postgres_back/db2 is UP, reason: Layer7 check passed, code: 200`  
> `Jul 28 15:31:41 vm-zabbix-server2 haproxy[827]: Server postgres_back/db1 is DOWN, reason: Layer7 wrong status, code: 503`

- **분석:** Patroni Switchover 실행 후, `15:31:38`에 HAProxy가 DB2의 8008 REST API `/primary` 200 OK 상태를 감지하여 5432 트래픽을 DB2로 즉시 라우팅 변경함.

3. **Zabbix Server DB 연동 완전 복구 (`vm-zabbix-server1` 로그)**

> `56038:20260728:153141.955 database connection re-established`  
> `56070:20260728:153147.167 database connection re-established`

- **분석:** `15:31:41.955`에 최초 DB 연동 세션이 재확립되었으며, `15:31:47.167`에 Server 내부 수집 프로세스 전체 세션이 복구됨.
- **최종 RTO:** $15:31:41.955 - 15:31:23.333 = \mathbf{18.622\,초}$

#### 🛡️ 5.1.2. 데이터 무결성 검토 결과 (RPO = 0 수준으로 평가)

1. **Read-Only(Standby) 순간 재접속 시 Zabbix 자체 버퍼 대기 메커니즘 작동**

> `56042:20260728:153137.189 database is read-only: reconnecting in 10 seconds`

- **평가:** DB2가 Primary로 승격되기 직전의 `15:31:37` 시점에 접속 시도 시, Zabbix Server는 에러 종료하지 않고 Read-Only 상태를 감지한 뒤 메모리 버퍼에 남은 데이터를 유지하며 대기하는 동작을 보였음.

2. **DB 복구 후 수집 아이템의 정상 상태(Supported) 일괄 복원 및 저장**

> `56037:20260728:153225.675 item "vm-zabbix-DB1:pgsql.queries[...] became supported`  
> `56030:20260728:153226.545 item "vm-zabbix-server1:zabbix[cluster,discovery,nodes]" became supported`

- **평가:** DB 접속 재확립 직후, 연결 중단으로 대기 모드(`became not supported`)에 들어갔던 모니터링 아이템들이 `15:32:25`부터 정상 수집 상태로 복구되었고, 이 과정에서 지연된 메트릭이 DB에 정상적으로 반영된 것으로 확인됨.

### 5.2. [시나리오 2] Zabbix Server HA 절체 검증

Active Zabbix Server 1 다운 시 Standby 상태인 Zabbix Server 2의 Active 승격 및 인프라 제어권 승계 성능을 검증합니다.

```text
[Server 1 Stop 명령] 15:35:28.597
       │
       ▼ (2.55초 간 하트비트 중단 감지 및 Standby ➔ Active 승격)
[Server 2 Active 승격] 15:35:31.144  <--- 핵심 RTO: 2.55초
       │
       ▼ (4.06초 간 전체 프로세스/프록시 그룹 모니터링 가동)
[Proxy Group 연동 완료] 15:35:35.209  <--- 서비스 완전 복구 RTO: 6.61초
```

#### ⏱️ 5.2.1. 복구 시간(RTO) 측정 및 로그 근거

- **노드 승격 RTO:** 2.55초 (Server 1 중단 명령 ~ Server 2 Active 모드 전환)
- **전체 서비스 복구 RTO:** 6.61초 (Server 1 중단 명령 ~ Proxy Group 관리 데몬 가동 완료)

##### 📝 로그 근거

1. **Server 1 중단 명령 투입 시각 (`vm-zabbix-server1` 터미널)**

> `ubuntu@vm-zabbix-server1:~$ date "+%Y-%m-%d %H:%M:%S.%3N" && sudo systemctl stop zabbix-server`  
> `2026-07-28 15:35:28.597`

2. **Server 2의 Active 노드 승격 감지 (`vm-zabbix-server2` 로그)**

> `51092:20260728:153531.144 "zabbix-server2" node switched to "active" mode`

- **분석:** Server 1 서비스 종료 시작 후 불과 2.547초 만에 Server 2가 하트비트 이탈을 감지하고 `active` 상태로 승격됨.

3. **내부 관리자 프로세스 및 Proxy Group 가동 완료 (`vm-zabbix-server2` 로그)**

> `53777:20260728:153535.135 server #205 started [proxy group manager #1]`  
> `53777:20260728:153535.209 Proxy "zabbix-proxy2" changed state from unknown to online`  
> `53777:20260728:153535.209 Proxy group "ixcloud-proxy-group" changed state from unknown to online`

- **최종 RTO:** $15:35:35.209 - 15:35:28.597 = \mathbf{6.612\,초}$

#### 🛡️ 5.2.2. 데이터 무결성 검토 결과 (RPO = 0 수준으로 평가)

1. **Server 1 종료 직전 메모리 데이터(History/Trend) DB Flush 완료**

> `56039:20260728:153529.083 syncing history data done`  
> `55992:20260728:153530.450 syncing trend data... 100.000000%`  
> `55992:20260728:153530.450 syncing trend data done`  
> `55992:20260728:153530.554 Zabbix Server stopped.`

- **평가:** Server 1이 종료되면서 기존 메모리 버퍼의 History 및 Trend 데이터가 DB에 100% 저장 완료(`100.000000%`)된 후 프로세스가 정상 종료된 것으로 확인됨.

2. **프록시 세션 즉시 승계 및 데이터 전달 지속**

- Server 2가 승격된 `15:35:35.209` 시점에 `zabbix-proxy1`, `zabbix-proxy2` 제어권이 정상적으로 승계되었고, 프록시 버퍼에 저장되어 있던 메트릭 데이터가 Server 2로 이어져 수집이 지속된 것으로 확인됨.

### 5.3. [시나리오 3] Zabbix Proxy Group Failover 검증

Active Proxy 1 중단 시 Zabbix 7.0 Native Proxy Group 고가용성 기능(`Failover period: 1m`)에 의해 Proxy 1 담당 호스트(1,000대)가 Proxy 2로 이관되어 수집을 지속하는지 검증합니다.

```text
[Proxy 1 Stop 명령] 15:40:16.984
       │
       ▼ (63.35초 간 Failover period 1분 관찰 및 Offline 판정)
[Proxy 1 Offline 감지] 15:41:20.336  <--- 장애 감지 RTO: 63.35초
       │
       ▼ (7.42초 간 Zabbix Server 호스트 자동 재할당 및 Proxy 2 Config 전달)
[Proxy 2 Config 전송] 15:41:27.758  <--- 이관 완료 RTO: 70.77초
       │
       ▼ (12.80초 후 DB 대량 History Bulk Insert 정상 수행)
[DB History Bulk Insert] 15:41:40.557  <--- 데이터 수집/저장 무결성 입증
```

#### ⏱️ 5.3.1. 복구 시간(RTO) 측정 및 로그 근거

- **장애 감지 RTO:** 63.35초 (Proxy 1 중단 ~ Server의 Offline 판정)
- **호스트 이관 RTO:** 70.77초 (Proxy 1 중단 ~ Proxy 2 설정 전송 및 모니터링 이관)

##### 📝 로그 근거

1. **Proxy 1 강제 중단 명령 투입 (`vm-zabbix-proxy1` 터미널)**

> `ubuntu@vm-zabbix-proxy1:~$ date "+%Y-%m-%d %H:%M:%S.%3N" && sudo systemctl stop zabbix-proxy`  
> `2026-07-28 15:40:16.984`

2. **Server 2의 Proxy 1 Offline 판정 (`vm-zabbix-server2` 로그)**

> `53777:20260728:154120.336 Proxy "zabbix-proxy1" changed state from online to offline`

- **분석:** Proxy Group 설정치인 `Failover period: 1m` (60초) 조건에 따라 `15:41:20.336` (63.35초 경과 시점)에 정확히 Offline을 감지함.

3. **Proxy 2로 가상 호스트 이관 및 설정 푸시 (`vm-zabbix-server2` 로그)**

> `53711:20260728:154127.758 sending configuration data to proxy "zabbix-proxy2" at "192.168.20.15", datalen 4101683, bytes 250191 with compression ratio 16.4`

- **분석:** Proxy 1이 다운되자마자 Server 2가 Proxy 1 담당 호스트의 모니터링 구성을 포함한 대용량 Config 데이터(압축 전 4.1MB)를 Proxy 2로 동기화 푸시하여 모니터링 권한을 완전 이관함.
- **최종 RTO:** $15:41:27.758 - 15:40:16.984 = \mathbf{70.774\,초}$

#### 🛡️ 5.3.2. 데이터 무결성 검토 결과 (RPO = 0 수준으로 평가)

1. **Zabbix 7.0 Native Proxy Group의 자동 호스트 재할당(Re-allocation) 메커니즘**

- Zabbix 7.0의 Proxy Group 아키텍처는 장애 발생 프록시를 이탈 처리하고, 그룹 내 가동 중인 타 프록시(`vm-zabbix-proxy2`)로 감지 대상 호스트들을 자동 이관(Self-reassignment)하도록 설계되어 있음.

2. **이관 완료 직후 DB 대용량 History Bulk Insert 정상 수행 입증 (`vm-zabbix-server2` 로그)**

> `53589:20260728:154140.557 slow query: 3.011773 sec, "insert into history (itemid,clock,ns,value) values (240689,1785220893,360488298,48.090000000000003),(240690,1785220893,360491988,48.710000000000001), ... (284438,1785220893,361590882,57.450000000000003);"`

- **평가:** Proxy 1 다운 후 Proxy 2가 모니터링 권한을 인수받은 시점(`15:41:27`) 직후인 `15:41:40`에, 절체 기간 동안 수집된 대량 메트릭(Bulk Values)이 DB `history` 테이블로 정상적으로 일괄 저장(Bulk Insert)된 것으로 확인됨. 이를 통해 데이터 누락은 관찰되지 않았음이 확인됨.

### 5.4. 종합 대조 요약표 (로그 데이터 대조)

| 테스트 시나리오 | 장애 인지 시각 | 복구 완료 시각 | RTO (소요시간) | RPO (손실) | 서버/DB 핵심 로그 근거 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **#1. Patroni DB Failover** | `15:31:23.333` | `15:31:41.955` | **18.62초** | **0 수준** | • HAProxy code: 200 (db2)<br>• `database connection re-established`<br>• `became supported` |
| **#2. Zabbix Server HA** | `15:35:28.597` | `15:35:31.144` | **2.55초** | **0 수준** | • `syncing trend data... 100%`<br>• `"zabbix-server2" node switched to "active" mode` |
| **#3. Proxy Group Failover** | `15:40:16.984` | `15:41:27.758` | **70.77초** | **0 수준** | • `Proxy "zabbix-proxy1" changed state to offline`<br>• `sending config to proxy "zabbix-proxy2"`<br>• `insert into history ...` |

---

