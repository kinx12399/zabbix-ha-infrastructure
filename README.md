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

```mermaid
graph TD
    subgraph Client ["1. 웹 접속 계층 (Domain Direct)"]
        User["User / Slack Webhook"] --> Domain["Domain: test-zabbix-yb.infra.kinxcdn.com"]
    end

    subgraph App ["2. 서버 & 웹 앱 계층 (Zabbix Server Native HA)"]
        Domain -- "HTTP :80 (직접 접속)" --> S1_Nginx["Server 1 Nginx / PHP"]
        Domain -- "HTTP :80 (직접 접속)" --> S2_Nginx["Server 2 Nginx / PHP"]

        S1_Server["Zabbix Server 1 (Active)"]
        S2_Server["Zabbix Server 2 (Standby)"]

        HAProxy1["Server 1 Local HAProxy<br/>(Patroni 8008 Health Check)"]
        HAProxy2["Server 2 Local HAProxy<br/>(Patroni 8008 Health Check)"]
    end

    subgraph Proxy ["3. 프록시 수집 계층 (Proxy Group)"]
        P1["vm-zabbix-proxy1 (SQLite3)"]
        P2["vm-zabbix-proxy2 (SQLite3)"]
    end

    subgraph DB ["4. 데이터베이스 계층 (Patroni HA + etcd)"]
        DB1["vm-zabbix-DB1<br/>• Patroni (Leader)<br/>• PostgreSQL 16 + TimescaleDB"]
        DB2["vm-zabbix-DB2<br/>• Patroni (Replica)<br/>• PostgreSQL 16 + TimescaleDB"]
    end

    %% Proxy to Zabbix Server Native HA Routing
    P1 -- "Data Push (:10051)<br/>(Active Server 연결)" --> S1_Server
    P1 -. "자동 Failover (:10051)" .-> S2_Server

    P2 -- "Data Push (:10051)<br/>(Active Server 연결)" --> S1_Server
    P2 -. "자동 Failover (:10051)" .-> S2_Server

    %% Server to DB Routing via Local HAProxy
    S1_Server --> HAProxy1
    S2_Server --> HAProxy2

    HAProxy1 -- "Active Primary DB 연결 (TCP 5432)" --> DB1
    HAProxy2 -- "Active Primary DB 연결 (TCP 5432)" --> DB1

    DB1 <== "Streaming Replication" ==> DB2