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

## ⚡ 5. 장애 조치 매커니즘 (Failover Scenarios)

| 장애 발생 시나리오 | 감지 및 판단 주체 | 자동 조치 동작 내용 | 서비스 복구 타임 |
| :--- | :--- | :--- | :--- |
| **Leader DB (`DB1`) 다운** | Patroni & etcd Quorum (REST API `8008`) | `DB2`가 Leader로 즉시 승격 ➔ App 서버 내 Local HAProxy가 이를 감지하고 `DB2:5432`로 커넥션 전환 | **5초 이내** |
| **Active Server (`Server1`) 다운** | Zabbix Native HA (`ha_node`) | `Server1`이 `active` 상태 승격 ➔ 프록시들이 `Server2` 로 데이터 전송 노드 자동 전환 | **30초 이내** |
| **Single Proxy (`Proxy1`) 다운** | Zabbix Server (Proxy Group Health Check) | `Proxygroup` 알고리즘에 의해 `Proxy1` 담당 수집 호스트가 `Proxy2`로 승계 및 이관 | **즉시** |

---

## 📝 6. 핵심 설정 예시 (Key Configuration Snippets)

### ⚙️ Zabbix Web GUI Config (/etc/zabbix/web/zabbix.conf.php)
```nginx
# IP 접근 또는 미허용 도메인 차단 (Catch-all)
server {
    listen       80 default_server;
    server_name  _;
    return       444; # connection closed without response
}

# 정식 도메인 전용 Zabbix 블록
server {
    listen          80;
    server_name     test-zabbix-yb.infra.kinxcdn.com;
    root            /usr/share/zabbix;
    ...
}